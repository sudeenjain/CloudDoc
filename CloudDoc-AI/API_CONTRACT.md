# API Contract (v1, frozen)

Base: `http://127.0.0.1:8000`. All API routes are under `/api`. JSON in/out except upload (multipart). Errors use FastAPI's default shape: `{"detail": "<message>"}`.
Any change to this file needs agreement from backend **and** frontend owners.

## Types
```
DocumentMeta {
  document_id: string      // UUID4 hex, server-generated
  filename: string         // original client filename, display only, max 255 chars
  size_bytes: integer
  page_count: integer
  chunk_count: integer
  uploaded_at: string      // ISO 8601 UTC
}
Source {
  document_id: string
  filename: string
  page: integer            // 1-indexed
  text: string             // the retrieved passage, max ~800 chars
  score: number            // TF-IDF cosine similarity, 0..1, rounded to 4 decimals
}
```
`DocumentMeta` fields beyond `document_id` and `filename` are our own choice (the brief only says "document metadata"); they are fixed from here on.

## GET /api/health
200 → `{"status": "ok"}`

## POST /api/documents
Multipart form, exactly one field named `file`, one PDF.
- 201 → `DocumentMeta`
- 400 missing `file`, not a PDF (extension `.pdf` AND first bytes `%PDF-`), or unreadable/corrupt PDF
- 413 larger than 20 MB
- 422 PDF has no extractable text (e.g. scanned images; no OCR in v1)

## GET /api/documents
200 → `DocumentMeta[]` (JSON array, newest first; `[]` when empty)

## POST /api/chat
Request: `{"question": string, "document_id": string | null}`
- `question`: trimmed, 1–1000 chars. `document_id`: `null` searches all documents.
- 200 → `{"answer": string, "sources": Source[]}`
- 404 `document_id` given but unknown
- 422 empty/oversized question or malformed body

Behaviour:
- Up to 5 sources, highest score first, only score > 0.
- `answer` is built by the server from the retrieved passages and always begins with the literal prefix `Retrieved passages (no AI-generated answer):`. It must never claim to be generated, summarized or reasoned by a model.
- No documents uploaded → 200, `answer` = `No documents uploaded yet.`, `sources` = `[]`.
- No passage matches → 200, `answer` = `No relevant passages found.`, `sources` = `[]`.
