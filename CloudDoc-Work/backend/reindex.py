"""Re-index every stored document with the current extraction / chunking / search pipeline.

Uses the original.pdf files already in data/documents, so nothing needs re-uploading.

    python reindex.py                 # all documents in ./data
    python reindex.py --data-dir D    # another data directory
    python reindex.py --id <uuid>     # one document
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import BASE_DIR, EMBEDDINGS_ENABLED
from embeddings import NullEmbedder, OllamaEmbedder
from extraction import ExtractionError
from index import SearchIndex
from ingest import process_pdf
from ocr import is_ocr_available
from storage import Store


def reindex(data_dir: Path, only_id: str | None = None, embedder=None, out=print) -> dict:
    store = Store(data_dir)
    if embedder is None:
        embedder = OllamaEmbedder() if EMBEDDINGS_ENABLED else NullEmbedder()

    out(f"Data directory : {data_dir}")
    out(f"OCR available  : {is_ocr_available()}")
    out(f"Semantic search: {'on (' + embedder.model + ')' if embedder.is_available() else 'off (BM25 + synonyms only)'}")

    summary = {"reindexed": 0, "failed": 0}
    for meta in store.list_meta():
        if only_id and meta["id"] != only_id:
            continue
        pdf = store.get_pdf_bytes(meta["id"])
        name = meta.get("filename", meta["id"])
        if pdf is None:
            out(f"  SKIP  {name}: original.pdf is missing")
            summary["failed"] += 1
            continue
        try:
            result, chunks = process_pdf(pdf, meta["id"], name)
        except ExtractionError as exc:
            out(f"  FAIL  {name}: {exc.detail}")
            summary["failed"] += 1
            continue

        new_meta = {
            **meta,
            "page_count": len(result.records),
            "chunk_count": len(chunks),
            "ocr_applied": bool(result.ocr_pages),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        store.replace_content(meta["id"], new_meta, chunks, pages=result.page_dicts())
        sections = sorted({c["section"] for c in chunks})
        out(
            f"  OK    {name}: {len(result.records)} page(s), "
            f"{[r.chars for r in result.records]} chars/page, OCR pages {result.ocr_pages or 'none'}, "
            f"{len(chunks)} chunks, sections {sections}"
        )
        summary["reindexed"] += 1

    SearchIndex(store, data_dir, embedder).rebuild()
    out(f"Search index rebuilt. {summary['reindexed']} re-indexed, {summary['failed']} failed.")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default=os.getenv("CLOUDDOC_DATA_DIR") or str(BASE_DIR / "data"))
    parser.add_argument("--id", dest="only_id", default=None, help="re-index a single document id")
    args = parser.parse_args(argv)
    summary = reindex(Path(args.data_dir), args.only_id)
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
