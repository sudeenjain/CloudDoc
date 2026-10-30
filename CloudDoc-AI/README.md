# CloudDoc md file

College cloud-computing major project. A **local** web app where you upload PDFs and ask questions; it returns the **most relevant passages** from those PDFs with filename, page number and a similarity score.

## What v1 is (and is not)
- IS: PDF upload, text extraction, TF-IDF passage retrieval, a small browser UI. Runs on one machine.
- IS NOT: an LLM. Answers are retrieved passages, never generated text. The UI and API must not describe them as AI-generated.
- IS NOT: deployed to any cloud, and it calls no external or paid APIs. Cloud deployment is out of scope for this MVP.
- No OCR: scanned/image-only PDFs are rejected with a clear error.

## Stack
Python 3.11+, FastAPI, PyMuPDF, scikit-learn (TF-IDF), HTML/CSS/vanilla JS.

## Setup
```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
Open http://127.0.0.1:8000 (UI) or http://127.0.0.1:8000/docs (auto-generated API docs).

> `requirements.txt` and the code are created by the team per `TASKS.md`; this repo starts with documentation only.

## Documents
| File | Purpose |
|---|---|
| `ARCHITECTURE.md` | Layout, module interfaces, data flow, privacy/safety |
| `API_CONTRACT.md` | Frozen HTTP contract (frontend and backend both code against this) |
| `TASKS.md` | Work split for four people, timeline, acceptance tests |
| `INTEGRATION_CHECKLIST.md` | Merge-time checks before demo |

## Data and privacy
Uploaded PDFs and extracted text live only in `./data/` (git-ignored). Nothing leaves the machine.
