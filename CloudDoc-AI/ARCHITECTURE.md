# Architecture (v1 local MVP)

Single FastAPI process serves both the JSON API and the static frontend. No database, no external services.

```
Browser (frontend/)  --fetch /api/*-->  FastAPI (backend/app/main.py)
                                          |- pdf_extract.py  PyMuPDF: PDF -> pages
                                          |- chunking.py     pages -> chunks
                                          |- storage.py      files under ./data/
                                          '- retrieval.py    TF-IDF index + search
```

## Repository layout (exact paths)
```
CloudDoc-AI/
  README.md  ARCHITECTURE.md  API_CONTRACT.md  TASKS.md  INTEGRATION_CHECKLIST.md  .gitignore
  requirements.txt
  backend/
    __init__.py
    app/
      __init__.py
      main.py          # FastAPI app, routes, static mount
      config.py        # constants
      schemas.py       # Pydantic models matching API_CONTRACT.md
      pdf_extract.py
      chunking.py
      storage.py
      retrieval.py
  frontend/
    index.html
    styles.css
    app.js
  data/                # runtime only, git-ignored
    uploads/<document_id>.pdf
    store/<document_id>.json   # DocumentMeta + chunks
```
Specialist workspaces elsewhere are not touched; only the paths above are in scope.

## Dependencies (minimal)
`requirements.txt`: `fastapi`, `uvicorn`, `python-multipart`, `pymupdf`, `scikit-learn`. Pin versions after the first successful install (`pip freeze` for these five and their direct needs only). Nothing else without team agreement.

## Backend interfaces
`config.py`
```python
DATA_DIR = Path("data"); UPLOAD_DIR = DATA_DIR / "uploads"; STORE_DIR = DATA_DIR / "store"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_QUESTION_CHARS = 1000
TOP_K = 5
CHUNK_TARGET_CHARS = 800
```
`schemas.py`: `DocumentMeta`, `Source`, `ChatRequest(question: str, document_id: str | None)`, `ChatResponse(answer: str, sources: list[Source])` exactly as in `API_CONTRACT.md`.

`pdf_extract.py`
```python
@dataclass
class PageText: page: int; text: str          # page is 1-indexed
def extract_pages(pdf_path: Path) -> list[PageText]
# Raises ValueError("unreadable pdf") on corrupt/encrypted files. Returns pages with blank text omitted.
```
`chunking.py`
```python
@dataclass
class Chunk: document_id: str; filename: str; page: int; text: str
def chunk_pages(document_id: str, filename: str, pages: list[PageText]) -> list[Chunk]
# Never crosses a page boundary. Paragraph-based, merged up to CHUNK_TARGET_CHARS; hard-split longer paragraphs.
```
`storage.py`
```python
def save_document(data: bytes, original_filename: str) -> DocumentMeta
#   validates size and %PDF- header, writes uploads/<uuid>.pdf, extracts, chunks, writes store/<uuid>.json.
#   Raises DocumentError(status: int, message: str) -> main.py maps to HTTP (400/413/422).
def list_documents() -> list[DocumentMeta]
def get_document(document_id: str) -> DocumentMeta | None
def load_chunks(document_id: str | None = None) -> list[Chunk]
```
`retrieval.py`
```python
class Retriever:
    def rebuild(self, chunks: list[Chunk]) -> None      # TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    def search(self, question: str, document_id: str | None, top_k: int = TOP_K) -> list[Source]
```
`main.py`: builds the retriever on startup from `load_chunks()` and rebuilds after each successful upload. Routes per `API_CONTRACT.md`. Mounts `frontend/` at `/` **after** the `/api` routes.

## Frontend interface (`frontend/app.js`)
Relative URLs only (`/api/...`), no frameworks, no CDN scripts.
```js
apiHealth()                       // GET /api/health
uploadDocument(file)              // POST /api/documents (FormData field "file")
listDocuments()                   // GET /api/documents
askQuestion(question, documentId) // POST /api/chat, documentId may be null
```
Required DOM ids in `index.html`: `upload-form`, `file-input`, `upload-status`, `doc-list`, `doc-select` (first option value `""` = all documents), `chat-form`, `question-input`, `chat-log`, `sources`.
Each source renders as: filename, `p.<page>`, score, passage text. The UI labels results "Retrieved passages", never "AI answer".

## Privacy and safety requirements
1. Local only: no outbound network calls from backend or frontend; no CDN assets, analytics or fonts.
2. Bind to `127.0.0.1`. No CORS middleware (same-origin only).
3. Never use the client filename for any filesystem path; files are stored as `<uuid>.pdf`. Filename is metadata only.
4. Validate: size ≤ 20 MB, `.pdf` extension, `%PDF-` header, PyMuPDF opens it. Reject otherwise.
5. Treat PDF text as untrusted: frontend renders with `textContent`, never `innerHTML`.
6. Do not log document text or questions.
7. `data/` is git-ignored; never commit real PDFs. Use non-sensitive sample PDFs for the demo.
8. `document_id` is only ever used as a lookup key, validated as 32 hex characters before touching disk.
9. No claim of AI/LLM generation anywhere in code, UI or docs.
10. No delete endpoint in v1; clearing data means deleting `./data/` manually (ask the team first).
