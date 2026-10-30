"""Safe persistent storage for uploaded PDFs, chunk indexes, and metadata."""
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Optional

import numpy as np


def safe_filename(name: str) -> str:
    """Create a safe display filename without path components."""
    base = re.split(r"[\\/]", name or "")[-1]
    stem = re.sub(r"[^\w.\- ()]", "_", base).strip(" .")

    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]

    stem = stem.strip(" .")[:96] or "document"
    return stem + ".pdf"


def _write_json(path: Path, payload) -> None:
    """Write JSON atomically to reduce the risk of partial files."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


class Store:
    """Stores each document in its own folder under data/documents/<uuid>."""

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "documents"
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve_folder(self, doc_id: str) -> Optional[Path]:
        """Validate UUID and verify the folder resides inside self.root."""
        try:
            val = str(uuid.UUID(str(doc_id).strip()))
        except (ValueError, TypeError):
            return None

        folder = (self.root / val).resolve()
        if not str(folder).startswith(str(self.root.resolve())):
            return None
        return folder

    def save(
        self,
        meta: dict,
        chunks: list[dict],
        pdf_bytes: bytes,
        pages: Optional[list[dict]] = None,
    ) -> None:
        folder = self._resolve_folder(meta["id"])
        if folder is None:
            raise ValueError(f"Invalid document id: {meta.get('id')}")

        folder.mkdir(parents=True, exist_ok=True)
        try:
            (folder / "original.pdf").write_bytes(pdf_bytes)
            if pages is not None:
                _write_json(folder / "pages.json", pages)
            _write_json(folder / "chunks.json", chunks)
            _write_json(folder / "meta.json", meta)  # written last: marks the document as ready
        except OSError:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def replace_content(
        self,
        doc_id: str,
        meta: dict,
        chunks: list[dict],
        pages: Optional[list[dict]] = None,
    ) -> None:
        """Re-index an existing document in place (original.pdf is untouched)."""
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            raise ValueError(f"Unknown document id: {doc_id}")
        if pages is not None:
            _write_json(folder / "pages.json", pages)
        _write_json(folder / "chunks.json", chunks)
        for stale in ("embeddings.npy", "embeddings.json"):
            (folder / stale).unlink(missing_ok=True)
        _write_json(folder / "meta.json", meta)

    def get_pages(self, doc_id: str) -> Optional[list[dict]]:
        return self._read_json_file(doc_id, "pages.json")

    # ----- per-document embedding cache (used by the search index) -----
    def save_embeddings(self, doc_id: str, matrix: np.ndarray, model: str) -> None:
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            return
        tmp = folder / "embeddings.npy.tmp"
        with open(tmp, "wb") as fh:
            np.save(fh, np.asarray(matrix, dtype=np.float32), allow_pickle=False)
        os.replace(tmp, folder / "embeddings.npy")
        _write_json(folder / "embeddings.json", {"model": model, "count": int(matrix.shape[0])})

    def get_embeddings(self, doc_id: str, model: str, expected_count: int) -> Optional[np.ndarray]:
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            return None
        info = self._read_json_file(doc_id, "embeddings.json")
        if not info or info.get("model") != model or info.get("count") != expected_count:
            return None
        try:
            arr = np.load(folder / "embeddings.npy", allow_pickle=False)
        except (OSError, ValueError):
            return None
        return arr if arr.shape[0] == expected_count else None

    def _read_json_file(self, doc_id: str, name: str):
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            return None
        try:
            return json.loads((folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def get_meta(self, doc_id: str) -> Optional[dict]:
        return self._read_json_file(doc_id, "meta.json")

    def get_chunks(self, doc_id: str) -> list[dict]:
        return self._read_json_file(doc_id, "chunks.json") or []

    def get_pdf_bytes(self, doc_id: str) -> Optional[bytes]:
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            return None
        pdf_path = folder / "original.pdf"
        if pdf_path.is_file():
            try:
                return pdf_path.read_bytes()
            except OSError:
                return None
        return None

    def get_pdf_path(self, doc_id: str) -> Optional[Path]:
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            return None
        pdf_path = folder / "original.pdf"
        return pdf_path if pdf_path.is_file() else None

    def delete(self, doc_id: str) -> bool:
        """Safely delete document folder and all its contents."""
        folder = self._resolve_folder(doc_id)
        if folder is None or not folder.is_dir():
            return False
        shutil.rmtree(folder, ignore_errors=True)
        return not folder.exists()

    def list_meta(self) -> list[dict]:
        if not self.root.is_dir():
            return []

        metas = []
        for folder in self.root.iterdir():
            if folder.is_dir():
                meta = self._read_json_file(folder.name, "meta.json")
                if meta:
                    metas.append(meta)

        return sorted(
            metas,
            key=lambda m: m.get("uploaded_at", ""),
            reverse=True,
        )
