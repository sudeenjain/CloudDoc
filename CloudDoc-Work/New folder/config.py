"""Centralized configuration for CloudDoc AI backend."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_ORIGINS = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_MAX_UPLOAD_MB = int(os.getenv("CLOUDDOC_MAX_UPLOAD_MB", "20"))
MAX_PAGES = int(os.getenv("CLOUDDOC_MAX_PAGES", "500"))
MAX_QUESTION_CHARS = int(os.getenv("CLOUDDOC_MAX_QUESTION_CHARS", "1000"))

# ---- Chunking -------------------------------------------------------------
# ~170 words is roughly 220-250 tokens; 25 words of overlap is ~15 %.
CHUNK_WORDS = int(os.getenv("CLOUDDOC_CHUNK_WORDS", "170"))
CHUNK_OVERLAP = int(os.getenv("CLOUDDOC_CHUNK_OVERLAP", "25"))
# A section is kept whole when it is at most this many words (about 300 tokens).
SECTION_MAX_WORDS = int(os.getenv("CLOUDDOC_SECTION_MAX_WORDS", str(int(CHUNK_WORDS * 1.35))))

# ---- Retrieval --------------------------------------------------------------
TOP_K = int(os.getenv("CLOUDDOC_TOP_K", "5"))
# Floor on the normalised (0..1) fused score. Kept at 0 so weak but correct
# matches are never discarded; the answer layer decides relevance.
MIN_SCORE = float(os.getenv("CLOUDDOC_MIN_SCORE", "0.0"))
RRF_K = int(os.getenv("CLOUDDOC_RRF_K", "60"))
RANK_DEPTH = int(os.getenv("CLOUDDOC_RANK_DEPTH", "50"))
SNIPPET_CHARS = int(os.getenv("CLOUDDOC_SNIPPET_CHARS", "1800"))
DEDUP_THRESHOLD = float(os.getenv("CLOUDDOC_DEDUP_THRESHOLD", "0.85"))

# ---- Extraction / OCR -------------------------------------------------------
OCR_MIN_PAGE_CHARS = int(os.getenv("CLOUDDOC_OCR_MIN_PAGE_CHARS", "50"))
OCR_DPI = int(os.getenv("CLOUDDOC_OCR_DPI", "220"))
OCR_LANG = os.getenv("CLOUDDOC_OCR_LANG", "eng")
# Optional explicit path to tesseract(.exe) when it is not on PATH.
TESSERACT_CMD = os.getenv("CLOUDDOC_TESSERACT_CMD", "").strip()

# ---- Local embeddings (Ollama) ----------------------------------------------
EMBEDDINGS_ENABLED = _flag("CLOUDDOC_EMBEDDINGS", "1")
EMBED_MODEL = os.getenv("CLOUDDOC_EMBED_MODEL", "nomic-embed-text").strip()
EMBED_TIMEOUT = float(os.getenv("CLOUDDOC_EMBED_TIMEOUT", "60.0"))
# Very low floor: semantic similarity below this is treated as "no signal".
EMBED_MIN_SIM = float(os.getenv("CLOUDDOC_EMBED_MIN_SIM", "0.2"))

# ---- Optional local LLM (Ollama) ---------------------------------------------
LLM_PROVIDER = os.getenv("CLOUDDOC_LLM_PROVIDER", "auto").lower().strip()
OLLAMA_URL = os.getenv("CLOUDDOC_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("CLOUDDOC_OLLAMA_MODEL", "llama3.2").strip()
OLLAMA_TIMEOUT = float(os.getenv("CLOUDDOC_OLLAMA_TIMEOUT", "60.0"))
# Let the local LLM propose 3 extra keyword variants for a question (temperature 0).
# Off by default: it costs one extra model call per question.
LLM_QUERY_REWRITE = _flag("CLOUDDOC_LLM_QUERY_REWRITE", "0")

# ---- Diagnostics ---------------------------------------------------------------
DEBUG_ENDPOINTS = _flag("CLOUDDOC_DEBUG_ENDPOINTS", "1")
