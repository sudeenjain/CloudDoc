"""Hybrid search index: BM25 + local embeddings merged with Reciprocal Rank Fusion.

HybridIndex is an immutable in-memory index. SearchIndex wraps it with disk
persistence (index/manifest.json plus a per-document embedding cache) and is
rebuilt on upload, delete and re-index.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
from rank_bm25 import BM25Plus

from chunking import clip_text
from config import (
    DEDUP_THRESHOLD,
    EMBED_MIN_SIM,
    MIN_SCORE,
    RANK_DEPTH,
    RRF_K,
    TOP_K,
)
from query_rewrite import QueryPlan
from text_utils import tokenize

logger = logging.getLogger("clouddoc.index")

MANIFEST_VERSION = 1


@dataclass
class IndexedChunk:
    doc_id: str
    filename: str
    page: int
    chunk_id: str
    section: str
    text: str  # prefixed text: what is shown, embedded and sent to the LLM
    body: str  # raw body: used for deduplication
    tokens: list[str]


def chunk_to_entry(meta: dict[str, Any], chunk: dict[str, Any], tokens: Optional[list[str]] = None) -> IndexedChunk:
    body = chunk.get("body") or chunk.get("text", "")
    section = chunk.get("section") or ""
    page = int(chunk.get("page", 1))
    cid = chunk.get("chunk_id") or f"{meta['id']}_p{page}"
    return IndexedChunk(
        doc_id=meta["id"],
        filename=meta.get("filename", "document.pdf"),
        page=page,
        chunk_id=cid,
        section=section,
        text=chunk.get("text", body),
        body=body,
        tokens=tokens if tokens is not None else tokenize(f"{section} {body}"),
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class HybridIndex:
    def __init__(
        self,
        entries: list[IndexedChunk],
        embeddings: Optional[np.ndarray] = None,
        has_embedding: Optional[np.ndarray] = None,
    ):
        self.entries = entries
        self.embeddings = embeddings
        self.has_embedding = has_embedding
        self.bm25: Optional[BM25Plus] = None
        if entries and any(e.tokens for e in entries):
            # delta=0 so a chunk with no query term scores exactly 0 (idf stays positive).
            self.bm25 = BM25Plus([e.tokens or ["_empty_"] for e in entries], delta=0.0)
        self._body_sets = [set(e.body.lower().split()) for e in entries]

    @property
    def semantic_ready(self) -> bool:
        return (
            self.embeddings is not None
            and self.has_embedding is not None
            and bool(self.has_embedding.any())
        )

    # ------------------------------------------------------------------ ranking
    def rank(
        self,
        plan: QueryPlan,
        doc_ids: Optional[set[str]] = None,
        query_vec: Optional[np.ndarray] = None,
    ) -> list[dict[str, Any]]:
        """Return every candidate chunk with raw BM25 / semantic scores and its fused score."""
        n = len(self.entries)
        if n == 0:
            return []

        scope = (
            np.ones(n, dtype=bool)
            if doc_ids is None
            else np.array([e.doc_id in doc_ids for e in self.entries], dtype=bool)
        )
        if not scope.any():
            return []

        # --- lexical list
        bm = np.zeros(n)
        if self.bm25 is not None and plan.bm25_tokens:
            bm = np.asarray(self.bm25.get_scores(plan.bm25_tokens), dtype=float)
        bm = np.where(scope, bm, 0.0)
        bm_order = [int(i) for i in np.argsort(-bm, kind="stable") if bm[i] > 0][:RANK_DEPTH]
        bm_rank = {i: r for r, i in enumerate(bm_order, start=1)}

        # --- semantic list
        sims = np.full(n, np.nan)
        sem_rank: dict[int, int] = {}
        if query_vec is not None and self.semantic_ready:
            raw = self.embeddings @ query_vec
            sims = np.where(scope & self.has_embedding, raw, np.nan)
            valid = [int(i) for i in np.argsort(-np.nan_to_num(sims, nan=-9.0), kind="stable")
                     if not np.isnan(sims[i]) and sims[i] >= EMBED_MIN_SIM][:RANK_DEPTH]
            sem_rank = {i: r for r, i in enumerate(valid, start=1)}

        lists = [r for r in (bm_rank, sem_rank) if r]
        if not lists:
            return []

        fused: dict[int, float] = {}
        for ranking in lists:
            for i, r in ranking.items():
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + r)
        best_possible = len(lists) / (RRF_K + 1)

        ordered = sorted(fused, key=lambda i: (-fused[i], -bm[i], i))
        rows = []
        for i in ordered:
            e = self.entries[i]
            rows.append({
                "idx": i,
                "document_id": e.doc_id,
                "filename": e.filename,
                "page": e.page,
                "chunk_id": e.chunk_id,
                "section": e.section,
                "bm25_score": round(float(bm[i]), 4),
                "bm25_rank": bm_rank.get(i),
                "semantic_score": None if np.isnan(sims[i]) else round(float(sims[i]), 4),
                "semantic_rank": sem_rank.get(i),
                "rrf_score": round(fused[i], 6),
                "score": round(fused[i] / best_possible, 4),
            })
        return rows

    def _dedupe(self, rows: list[dict[str, Any]], threshold: float) -> tuple[list[dict], list[dict]]:
        kept: list[dict] = []
        dropped: list[dict] = []
        for row in rows:
            words = self._body_sets[row["idx"]]
            twin = next(
                (k for k in kept if _jaccard(words, self._body_sets[k["idx"]]) >= threshold),
                None,
            )
            if twin is None:
                kept.append(row)
            else:
                dropped.append({**row, "duplicate_of": twin["chunk_id"]})
        return kept, dropped

    def search(
        self,
        plan: QueryPlan,
        doc_ids: Optional[set[str]] = None,
        query_vec: Optional[np.ndarray] = None,
        top_k: int = TOP_K,
        min_score: float = MIN_SCORE,
        dedup_threshold: float = DEDUP_THRESHOLD,
    ) -> list[dict[str, Any]]:
        rows = [r for r in self.rank(plan, doc_ids, query_vec) if r["score"] >= min_score]
        kept, _ = self._dedupe(rows, dedup_threshold)
        results = []
        for row in kept[:top_k]:
            e = self.entries[row["idx"]]
            results.append({
                "document_id": e.doc_id,
                "filename": e.filename,
                "page": e.page,
                "chunk_id": e.chunk_id,
                "text": clip_text(e.text),
                "score": row["score"],
            })
        return results

    def explain(
        self,
        plan: QueryPlan,
        doc_ids: Optional[set[str]] = None,
        query_vec: Optional[np.ndarray] = None,
        limit: int = 10,
        dedup_threshold: float = DEDUP_THRESHOLD,
    ) -> list[dict[str, Any]]:
        """Top rows with raw scores for the debug endpoint (duplicates are flagged, not hidden)."""
        rows = self.rank(plan, doc_ids, query_vec)
        kept, dropped = self._dedupe(rows, dedup_threshold)
        dup_by_idx = {d["idx"]: d["duplicate_of"] for d in dropped}
        out = []
        for row in rows[:limit]:
            e = self.entries[row["idx"]]
            item = {k: v for k, v in row.items() if k != "idx"}
            item["preview"] = e.text[:300]
            item["near_duplicate_of"] = dup_by_idx.get(row["idx"])
            out.append(item)
        return out

    def scope_size(self, doc_ids: Optional[set[str]]) -> int:
        if doc_ids is None:
            return len(self.entries)
        return sum(1 for e in self.entries if e.doc_id in doc_ids)

    @classmethod
    def from_documents(cls, documents: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> "HybridIndex":
        entries = [
            chunk_to_entry(meta, chunk)
            for meta, chunks in documents
            for chunk in chunks
            if (chunk.get("body") or chunk.get("text", "")).strip()
        ]
        return cls(entries)


class SearchIndex:
    """Persistent, auto-refreshing index over every stored document."""

    def __init__(self, store, data_dir: Path, embedder):
        self.store = store
        self.dir = Path(data_dir) / "index"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder
        self._lock = threading.Lock()
        self._hybrid: Optional[HybridIndex] = None
        self._fingerprint: Optional[list] = None

    @staticmethod
    def _fingerprint_of(metas: list[dict]) -> list:
        return sorted(
            [m["id"], m.get("chunk_count"), m.get("uploaded_at"), m.get("indexed_at")] for m in metas
        )

    # ------------------------------------------------------------------ build
    def rebuild(self, metas: Optional[list[dict]] = None) -> HybridIndex:
        with self._lock:
            return self._rebuild_locked(metas)

    def _load_manifest_tokens(self, fingerprint: list) -> dict[str, list[str]]:
        path = self.dir / "manifest.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if data.get("version") != MANIFEST_VERSION or data.get("fingerprint") != fingerprint:
            return {}
        return {e["chunk_id"]: e["tokens"] for e in data.get("entries", [])}

    def _rebuild_locked(self, metas: Optional[list[dict]]) -> HybridIndex:
        metas = metas if metas is not None else self.store.list_meta()
        fingerprint = self._fingerprint_of(metas)
        cached_tokens = self._load_manifest_tokens(fingerprint)

        entries: list[IndexedChunk] = []
        doc_slices: list[tuple[dict, list[dict], int, int]] = []
        for meta in metas:
            chunks = [c for c in self.store.get_chunks(meta["id"])
                      if (c.get("body") or c.get("text", "")).strip()]
            start = len(entries)
            for chunk in chunks:
                cid = chunk.get("chunk_id")
                entries.append(chunk_to_entry(meta, chunk, cached_tokens.get(cid)))
            doc_slices.append((meta, chunks, start, len(entries)))

        embeddings, has_emb = self._collect_embeddings(entries, doc_slices)
        index = HybridIndex(entries, embeddings, has_emb)
        self._persist_manifest(fingerprint, entries)
        self._hybrid, self._fingerprint = index, fingerprint
        return index

    def _collect_embeddings(self, entries, doc_slices):
        if not entries:
            return None, None
        try:
            usable = self.embedder.is_available()
        except Exception:
            usable = False
        model = getattr(self.embedder, "model", "none")
        matrix: Optional[np.ndarray] = None
        has_emb = np.zeros(len(entries), dtype=bool)

        for meta, chunks, start, end in doc_slices:
            if end == start:
                continue
            vectors = self.store.get_embeddings(meta["id"], model, end - start)
            if vectors is None and usable:
                try:
                    vectors = self.embedder.embed_documents([e.text for e in entries[start:end]])
                    self.store.save_embeddings(meta["id"], vectors, model)
                except Exception as exc:
                    logger.warning("Embedding %s failed (%s); using BM25 only for it.", meta.get("filename"), exc)
                    vectors = None
            if vectors is None:
                continue
            if matrix is None:
                matrix = np.zeros((len(entries), vectors.shape[1]), dtype=np.float32)
            if vectors.shape[1] != matrix.shape[1]:
                continue  # model changed mid-way; ignore this document's vectors
            matrix[start:end] = vectors
            has_emb[start:end] = True
        return matrix, has_emb

    def _persist_manifest(self, fingerprint: list, entries: list[IndexedChunk]) -> None:
        payload = {
            "version": MANIFEST_VERSION,
            "fingerprint": fingerprint,
            "embed_model": getattr(self.embedder, "model", "none"),
            "entries": [{"doc_id": e.doc_id, "chunk_id": e.chunk_id, "tokens": e.tokens} for e in entries],
        }
        tmp = self.dir / "manifest.json.tmp"
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / "manifest.json")
        except OSError as exc:  # index persistence is best-effort
            logger.warning("Could not persist search index: %s", exc)

    # ------------------------------------------------------------------ use
    def get(self, metas: Optional[list[dict]] = None) -> HybridIndex:
        """Return an up-to-date index, rebuilding if documents changed on disk."""
        metas = metas if metas is not None else self.store.list_meta()
        fingerprint = self._fingerprint_of(metas)
        if self._hybrid is not None and fingerprint == self._fingerprint:
            return self._hybrid
        with self._lock:
            if self._hybrid is not None and fingerprint == self._fingerprint:
                return self._hybrid
            return self._rebuild_locked(metas)

    def query_vector(self, index: HybridIndex, question: str) -> Optional[np.ndarray]:
        if not index.semantic_ready:
            return None
        try:
            if not self.embedder.is_available():
                return None
            return self.embedder.embed_query(question)
        except Exception as exc:
            logger.warning("Query embedding failed (%s); using BM25 only.", exc)
            return None

    def search(
        self,
        question: str,
        plan: QueryPlan,
        doc_ids: Optional[set[str]] = None,
        top_k: int = TOP_K,
    ) -> list[dict[str, Any]]:
        index = self.get()
        return index.search(plan, doc_ids, self.query_vector(index, question), top_k=top_k)
