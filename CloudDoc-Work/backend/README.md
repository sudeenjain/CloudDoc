# CloudDoc AI – backend

Local FastAPI service: upload PDFs, extract text per page (PyMuPDF, with automatic OCR for image-only
pages), and answer questions with **hybrid retrieval** (BM25 + local embeddings, merged with Reciprocal
Rank Fusion). Everything runs on your machine. No cloud APIs, no telemetry.

Requires Python 3.11+.

## System packages

| Package | Needed for | Windows | Linux |
|---|---|---|---|
| **Tesseract OCR** | reading image-only / scanned / Canva PDFs | `winget install UB-Mannheim.TesseractOCR` | `sudo apt install tesseract-ocr` |
| **Ollama** (optional) | answer generation (`llama3.2`) and semantic search | https://ollama.com | same |

Poppler is **not** needed: pages are rendered with PyMuPDF.

On Windows, if Tesseract is not found, set `CLOUDDOC_TESSERACT_CMD`, e.g.
`$env:CLOUDDOC_TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"`.
The default install folders are also checked automatically.

For semantic search pull the embedding model once (about 270 MB). Without it the app still works and
uses BM25 + synonym expansion only:

```powershell
ollama pull nomic-embed-text
ollama pull llama3.2
```

## Setup and run (PowerShell)

```powershell
cd CloudDoc-Work\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m pip install --upgrade pip
pip install -r requirements.txt
python reindex.py                 # re-index documents you uploaded earlier (see below)
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Interactive docs: http://127.0.0.1:8000/docs

## Re-index existing documents

Documents uploaded with the old version keep their old chunks until you re-index. This reads the saved
`original.pdf` files, so nothing has to be uploaded again:

```powershell
python reindex.py                     # every document
python reindex.py --id <document-uuid>  # one document
```

It prints, per file, the characters per page, which pages used OCR, the chunk count and the detected
sections. A running server notices the change automatically.

## Run the tests

```powershell
python -m pytest -q
```

Tests use a temporary data directory and never touch your saved documents. OCR tests are skipped if
Tesseract is missing.

## How retrieval works

1. **Extraction**: text blocks are read in column-aware reading order. Any page with fewer than 50
   characters is OCR'd automatically (Tesseract).
2. **Chunking**: split on headings: resume sections (Education, Experience, Skills, Projects,
   Certifications, Contact, Summary and more) and numbered headings such as `2. Major Challenges in NLP
   Systems`. Short slide-like pages take their first line as the section title and never inherit the
   previous slide's title. Otherwise about 170-word windows with about 15% overlap. A chunk cut in the
   middle of a sentence, including at a page break, is completed with the words that finish that
   sentence from the following text. Every chunk starts with `Document: <file> | Section: <title>`, so
   the section name is part of the indexed text.
3. **Query rewriting**: pronouns and filler words are removed, then a curated synonym map expands the
   question (college/university/institute/degree map to education terms, and likewise for skills,
   experience, internship, projects, contact, certifications). Optionally `llama3.2` adds 3 keyword
   variants at temperature 0 (`CLOUDDOC_LLM_QUERY_REWRITE=1`).
4. **Hybrid ranking**: BM25 and embedding similarity (`nomic-embed-text` via Ollama) are fused with
   Reciprocal Rank Fusion. Near-identical chunks (same person, several resumes) are collapsed.
   The top 5 are returned with no score threshold. The LLM decides relevance.
5. **Answering**: `llama3.2` sees only the retrieved chunks and cites `[Doc: <file>, Page: <n>]`.
   Citations that do not match a retrieved source are stripped. If the model cites nothing, a
   `Sources consulted: [Doc: …, Page: …]` line lists the pages it was given. With zero chunks the mode
   is never `generated_ai`.

The index is saved in `data/index/manifest.json` and per-document `embeddings.npy`. It is refreshed on
upload and delete.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | `{"status": "ok"}` |
| GET | `/api/provider/status` | provider, Ollama state, **real** OCR state, semantic-search state |
| POST | `/api/documents` | multipart field `file` (PDF). `201` + metadata |
| GET | `/api/documents` | saved metadata, newest first |
| DELETE | `/api/documents/{id}` | delete a document and refresh the index |
| GET | `/api/documents/{id}/file` | the original PDF. With `?highlight=<chunk_id>` a copy with that evidence highlighted (text pages, and OCR'd image pages); the stored file is never changed |
| POST | `/api/chat` | `{"question": "...", "document_id": "<uuid>" \| null}` returns `{answer, sources: [{document_id, filename, page, text, score}], provider, mode, model}` |
| POST | `/api/operations` | summarize / key_points / deadlines / people / costs / compare |
| GET | `/api/debug/documents/{id}` | pages, text length per page, OCR use, chunk count, first 300 characters of each chunk |
| POST | `/api/debug/search` | `{question, document_id}` returns top 10 chunks with raw BM25 / semantic / fused scores and the preprocessed query |

`score` is the fused rank normalised to 0..1: it orders the passages, it is not a confidence percentage. Debug endpoints can be turned off with
`CLOUDDOC_DEBUG_ENDPOINTS=0`.

Errors are JSON `{"detail": "..."}`: `400` not a valid PDF, `404` unknown document, `413` too large,
`422` no extractable text.

## Configuration (optional environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `CLOUDDOC_DATA_DIR` | `./data` | Where documents and the index are stored |
| `CLOUDDOC_MAX_UPLOAD_MB` | `20` | Upload size limit |
| `CLOUDDOC_TOP_K` | `5` | Passages returned per question |
| `CLOUDDOC_CHUNK_WORDS` / `CLOUDDOC_CHUNK_OVERLAP` | `170` / `25` | Window size and overlap (words) |
| `CLOUDDOC_OCR_MIN_PAGE_CHARS` | `50` | Pages with less text are OCR'd |
| `CLOUDDOC_TESSERACT_CMD` | auto | Path to tesseract(.exe) |
| `CLOUDDOC_EMBEDDINGS` | `1` | `0` disables semantic search |
| `CLOUDDOC_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `CLOUDDOC_LLM_QUERY_REWRITE` | `0` | `1` lets llama3.2 add keyword variants |
| `CLOUDDOC_OLLAMA_MODEL` / `CLOUDDOC_OLLAMA_URL` | `llama3.2` / `http://127.0.0.1:11434` | Local LLM |
| `CLOUDDOC_FRONTEND_ORIGINS` | local dev origins | Comma-separated CORS origins |

## Storage layout

```
data/documents/<uuid>/original.pdf     # the upload
data/documents/<uuid>/pages.json       # text length per page, OCR flags
data/documents/<uuid>/chunks.json      # section-aware chunks
data/documents/<uuid>/embeddings.npy   # cached vectors (when Ollama embeddings are on)
data/documents/<uuid>/meta.json        # metadata (written last)
data/index/manifest.json               # persisted search index
```

## Limitations

- OCR quality depends on scan quality. Check `/api/debug/documents/{id}` to see which pages used OCR.
- The synonym map is tuned for resumes and general documents. Extend `CONCEPTS` in `query_rewrite.py`
  for other domains.
- Without the embedding model, matching is lexical plus synonyms. It will miss paraphrases the synonym
  map does not cover.
