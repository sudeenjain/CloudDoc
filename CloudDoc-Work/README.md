# CloudDoc AI — Advanced AI Document Assistant

A production-grade, evidence-grounded document assistant built for high-reliability PDF analysis. CloudDoc AI extracts text page-by-page, builds structured lexical chunk indexes, retrieves precise evidence passages with page citations, allows 1-click navigation inside an embedded PDF viewer, and supports optional local generative AI via Ollama.

Runs **100% locally** with **zero paid APIs, subscriptions, or telemetry**.

---

## Key Features

- **Evidence-Grounded Retrieval**: Passages are ranked using TF-IDF cosine similarity. No fabricated facts, hallucinated page numbers, or fake statistics.
- **Interactive PDF Viewer**: Click any citation badge (e.g. `[Page 2 of report.pdf]`) to open the original PDF directly at that page in a slide-out viewer.
- **Strict Document Scope Isolation**: Search either a single selected document or across all uploaded documents without cross-contamination.
- **Near-Duplicate Suppression**: Filters out repetitive overlapping chunks from the same page, ensuring diverse independent evidence.
- **Quick Analysis Operations**:
  - **Summarize**: Synthesize core themes across pages.
  - **Key Points**: Extract bulleted highlights with page citations.
  - **Dates & Deadlines**: Isolate timelines, payment periods, and schedule references.
  - **Costs & Fees**: Extract monetary terms, invoices, and payment requirements.
  - **Roles & Responsibilities**: Identify stakeholders, managers, and assigned duties.
  - **Multi-Document Comparison**: Compare 2+ documents side-by-side with cross-document source attribution.
- **Optional Local Generative AI (Ollama)**:
  - Works out of the box in **Retrieval-Only Mode** with zero external dependencies.
  - Seamlessly connects to a local Ollama daemon (e.g., Llama 3.2, Mistral) if available.
  - Enforces prompt injection defense via XML boundary fencing.
  - Automatically falls back to retrieval mode if the local model is offline.
- **Document Management**:
  - Live upload progress bar with byte limits and page limits.
  - Filter and search uploaded PDFs by filename.
  - Safe document deletion with disk storage cleanup.
- **Conversation & Export**:
  - Copy answers and formatted citations to clipboard with 1 click.
  - Export session conversation as Markdown (`.md`) with timestamps and sources.
- **Premium SaaS Interface**:
  - Dark slate/obsidian palette, accessible contrast, responsive layout for desktop, tablet, and mobile.
  - Accessible keyboard navigation and reduced-motion support.

---

## Technology Stack

- **Backend**: Python 3.11+ / 3.14+, [FastAPI](https://fastapi.tiangolo.com/), [Uvicorn](https://www.uvicorn.org/), [PyMuPDF](https://pymupdf.readthedocs.io/), [scikit-learn](https://scikit-learn.org/), [HTTPX](https://www.python-httpx.org/).
- **Frontend**: Vanilla HTML5, modern CSS3 (custom properties, CSS grid/flexbox), Vanilla JavaScript (ES2022). No heavy framework or build steps required.
- **Storage**: Structured local filesystem (`data/documents/<uuid>/original.pdf`, `chunks.json`, `meta.json`).

## Quick Start (Run with One Line)

You can launch the entire project (backend API + UI) with **a single command**:

### In Windows PowerShell:
```powershell
python run.py
```
*(or run `.\run.ps1`)*

### In Windows CMD / Double-Click:
```cmd
run.bat
```

This single command will:
1. Automatically activate the virtual environment (`backend\.venv`).
2. Start the unified FastAPI server on `http://127.0.0.1:8000`.
3. Serve both the **FastAPI backend endpoints** and the **modern SaaS frontend UI** from the same port.
4. Automatically open `http://127.0.0.1:8000` in your default web browser.

---

## Manual Multi-Terminal Setup (Optional)

If you prefer running the backend and frontend separately:


```powershell
# Navigate to the backend directory
cd backend

# Create virtual environment (if not already created)
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Upgrade pip and install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# Start the FastAPI server
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The backend interactive OpenAPI documentation will be available at:  
👉 **http://127.0.0.1:8000/docs**

### 3. Frontend Setup

In a separate PowerShell terminal:

```powershell
# Navigate to the frontend directory
cd frontend

# Serve with Python's built-in HTTP server
python -m http.server 5173
```

Open your browser and navigate to:  
👉 **http://localhost:5173** (or http://127.0.0.1:5173)

---

## Running Automated Tests

CloudDoc AI includes a comprehensive test suite (29 tests) verifying API endpoints, upload limits, cross-document isolation, deletion, file serving, operations, and fallbacks:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pytest test_api.py -v
```

All tests execute against temporary directories (`tmp_path`) and synthetic deterministic PDFs, leaving your saved documents untouched.

---

## Optional Local AI Setup (Ollama)

To enable generative answer synthesis without sending data to any third-party cloud:

1. Install [Ollama](https://ollama.com/) on your local machine.
2. Pull a lightweight model (e.g. Llama 3.2 3B):
   ```bash
   ollama pull llama3.2
   ```
3. Ensure Ollama is running (`ollama serve`).
4. Set the environment variable before starting the backend:
   ```powershell
   $env:CLOUDDOC_LLM_PROVIDER="ollama"
   $env:CLOUDDOC_OLLAMA_MODEL="llama3.2"
   uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```
5. If Ollama is stopped or unreachable, CloudDoc AI **automatically falls back** to retrieval mode without failing user requests.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health check (`{"status": "ok"}`). |
| `GET` | `/api/provider/status` | Current AI provider and OCR status. |
| `POST` | `/api/documents` | Upload PDF (`multipart/form-data`). Returns metadata (201). |
| `GET` | `/api/documents` | List uploaded document metadata (newest first). |
| `DELETE` | `/api/documents/{id}` | Safely delete a document and clean disk storage. |
| `GET` | `/api/documents/{id}/file` | Stream original PDF file for citation viewing. |
| `POST` | `/api/chat` | Send question (`question`, `document_id` or `null`). Returns answer & sources. |
| `POST` | `/api/operations` | Perform quick analysis (`summarize`, `key_points`, `deadlines`, `people`, `costs`, `compare`). |

### Example Chat Request & Response:

**Request (`POST /api/chat`)**:
```json
{
  "question": "What are the payment terms?",
  "document_id": "a38c00eb-78d3-433a-ba3c-2a3517a71eb2"
}
```

**Response (`200 OK`)**:
```json
{
  "answer": "Most relevant passage (page 1 of \"invoice.pdf\"): Invoice 2041. The total amount is payable within thirty days by bank transfer.",
  "sources": [
    {
      "document_id": "a38c00eb-78d3-433a-ba3c-2a3517a71eb2",
      "filename": "invoice.pdf",
      "page": 1,
      "chunk_id": "a38c00eb_p1_c1",
      "text": "Invoice 2041. The total amount is payable within thirty days by bank transfer.",
      "score": 0.5821
    }
  ],
  "provider": "retrieval",
  "mode": "retrieval_only",
  "model": null
}
```

---

## Configuration (`.env`)

See `.env.example` for full options.

| Variable | Default | Purpose |
|---|---|---|
| `CLOUDDOC_FRONTEND_ORIGINS` | `http://localhost:5500,http://127.0.0.1:5500,http://localhost:5173,http://127.0.0.1:5173` | Allowed CORS origins |
| `CLOUDDOC_DATA_DIR` | `./data` | Local document storage location |
| `CLOUDDOC_MAX_UPLOAD_MB` | `20` | Max PDF file size (MB) |
| `CLOUDDOC_MAX_PAGES` | `500` | Max pages per document |
| `CLOUDDOC_TOP_K` | `4` | Number of evidence passages retrieved |
| `CLOUDDOC_MIN_SCORE` | `0.05` | Minimum cosine relevance score |
| `CLOUDDOC_DEDUP_THRESHOLD` | `0.85` | Near-duplicate suppression threshold |
| `CLOUDDOC_LLM_PROVIDER` | `retrieval` | AI mode: `retrieval` or `ollama` |
| `CLOUDDOC_OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama daemon URL |
| `CLOUDDOC_OLLAMA_MODEL` | `llama3.2` | Ollama model name |

---

## Security & Data Privacy

- **Path Traversal Protection**: Document identifiers are validated UUID v4 strings. File paths are strictly resolved within the storage root.
- **Upload Hardening**: Stream size limiting, `%PDF-` signature inspection, and PyMuPDF structural validation prevent corrupt or malicious file processing.
- **Prompt Injection Defense**: When an LLM is active, document context is encapsulated inside `<document_evidence>` XML tags with strict negative constraints against instruction hijacking.
- **No Remote Data Leaks**: Zero analytics, telemetry, or external API dependencies in default configuration.

---

## Known Limitations & Future Roadmap

1. **Scanned PDFs**: Scanned image-only PDFs require local Tesseract OCR installed on the host. When not installed, the app cleanly detects the scanned condition and alerts the user.
2. **Dense Semantic Embeddings**: TF-IDF provides dependable lexical matching with zero GPU requirements; future iterations can add optional local ONNX sentence-transformer embeddings (e.g. `all-MiniLM-L6-v2`).
3. **Cloud Run Storage**: Deploying to serverless containers requires mounting persistent object storage (e.g., GCS via Cloud Storage FUSE) to retain documents across container restarts (see [ARCHITECTURE.md](ARCHITECTURE.md)).
