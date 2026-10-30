"""Stateless retrieval helper (BM25 + synonym expansion, with deduplication).

The chat endpoint uses the persistent hybrid SearchIndex in index.py. This
function serves callers that hand over their own chunks (e.g. operations.py).
"""
from __future__ import annotations

from typing import Any

from config import DEDUP_THRESHOLD, MIN_SCORE, TOP_K
from index import HybridIndex
from query_rewrite import rewrite_query


def _word_jaccard(text1: str, text2: str) -> float:
    s1 = set(text1.lower().split())
    s2 = set(text2.lower().split())
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def retrieve(
    question: str,
    documents: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    top_k: int = TOP_K,
    min_score: float = MIN_SCORE,
    dedup_threshold: float = DEDUP_THRESHOLD,
) -> list[dict[str, Any]]:
    """Rank the given documents' chunks for a question.

    `score` is normalised to 0..1 (1.0 = best possible fused rank). Returns [] only
    when the scope has no chunks or no chunk shares any (expanded) query term.
    """
    index = HybridIndex.from_documents(documents)
    if not index.entries:
        return []
    plan = rewrite_query(question)
    return index.search(plan, top_k=top_k, min_score=min_score, dedup_threshold=dedup_threshold)
