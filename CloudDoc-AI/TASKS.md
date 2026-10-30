# Tasks (target: 8–10 hours, four people)

Rule: each person edits only their own paths. Contract changes go through `API_CONTRACT.md` first.
Status key: `[ ]` todo, `[x]` done. Nothing below is done yet.

## Person A — PDF + chunking (`backend/app/pdf_extract.py`, `chunking.py`)
- [ ] `extract_pages()` with PyMuPDF; raise `ValueError` on corrupt/encrypted
- [ ] `chunk_pages()` per interface in `ARCHITECTURE.md`
- [ ] Manual check on 2 sample PDFs (one multi-page text PDF, one scanned/no-text PDF)

## Person B — Retrieval (`backend/app/retrieval.py`)
- [ ] `Retriever.rebuild()` and `search()` per interface; handle empty chunk list
- [ ] Filter by `document_id`; return only score > 0, rounded to 4 decimals, max `TOP_K`
- [ ] Manual check with hand-made chunks: a relevant query ranks the right chunk first

## Person C — API + storage (`backend/app/main.py`, `config.py`, `schemas.py`, `storage.py`, `requirements.txt`, `backend/__init__.py`, `backend/app/__init__.py`)
- [ ] `requirements.txt`, `config.py`, `schemas.py` first (unblocks everyone; target hour 1)
- [ ] Routes and status codes exactly per `API_CONTRACT.md`
- [ ] `storage.py` validation, persistence, restart reload
- [ ] Static mount of `frontend/` after API routes
- [ ] Chat `answer` string per contract (literal prefix, empty/no-match cases)

## Person D — Frontend (`frontend/index.html`, `styles.css`, `app.js`)
- [ ] Layout with the required DOM ids
- [ ] The four `app.js` functions; error messages show the server `detail`
- [ ] Render sources with `textContent`; label as "Retrieved passages"
- [ ] Develop against a stub returning contract-shaped JSON until backend is ready

## Timeline (adjust, but keep order)
| Hour | Milestone |
|---|---|
| 0–1 | Docs reviewed; C pushes skeleton (`requirements.txt`, `config.py`, `schemas.py`, `/api/health`) |
| 1–4 | A, B, D build in parallel against interfaces |
| 4–6 | C wires A + B into routes; D switches from stub to real API |
| 6–8 | Integration pass using `INTEGRATION_CHECKLIST.md`; fix bugs |
| 8–10 | Buffer, demo rehearsal with non-sensitive PDFs, README polish |

## Acceptance tests (manual; no automated tests exist yet)
Server running on 127.0.0.1:8000, `sample.pdf` = any text PDF, `scan.pdf` = image-only PDF.

| # | Action | Expected |
|---|---|---|
| 1 | `curl -s localhost:8000/api/health` | `{"status":"ok"}` |
| 2 | `curl -s -F file=@sample.pdf localhost:8000/api/documents` | 201, `DocumentMeta` with all 6 fields |
| 3 | `curl -s localhost:8000/api/documents` | array containing the uploaded document |
| 4 | Upload `notes.txt` renamed to `notes.pdf` | 400 |
| 5 | Upload a PDF over 20 MB | 413 |
| 6 | Upload `scan.pdf` | 422 |
| 7 | `curl -s -X POST localhost:8000/api/chat -H 'Content-Type: application/json' -d '{"question":"<a phrase from sample.pdf>","document_id":null}'` | 200; `answer` starts with `Retrieved passages (no AI-generated answer):`; ≥1 source with correct `page` |
| 8 | Same with `"document_id":"0000000000000000000000000000dead"` | 404 |
| 9 | Chat with `"question":"   "` | 422 |
| 10 | Chat with a nonsense query (`"zzzqxv"`) | 200, `No relevant passages found.`, `sources: []` |
| 11 | Stop and restart server, repeat #3 and #7 | Documents and results persist |
| 12 | Browser: upload, pick document, ask question | Sources shown with filename, page, score, text; no HTML injected from PDF text |
