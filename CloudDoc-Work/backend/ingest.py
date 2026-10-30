"""Shared ingestion pipeline: PDF bytes -> extracted pages -> section-aware chunks.

Used by the upload endpoint and by reindex.py so both always behave the same.
"""
from __future__ import annotations

from chunking import build_page_chunks
from extraction import ExtractionError, ExtractionResult, extract_pdf


def process_pdf(data: bytes, doc_id: str, filename: str) -> tuple[ExtractionResult, list[dict]]:
    """Extract (with automatic OCR) and chunk a PDF. Raises ExtractionError when unusable."""
    result = extract_pdf(data)
    chunks = build_page_chunks(result.pages, doc_id=doc_id, filename=filename)
    if not chunks:
        raise ExtractionError(422, "No extractable text found in this PDF.")
    return result, chunks
