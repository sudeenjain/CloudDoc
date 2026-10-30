"""CloudDoc AI backend: PDF upload, hybrid local retrieval, optional local LLM, and analysis operations."""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import (
    BASE_DIR,
    DEBUG_ENDPOINTS,
    DEFAULT_MAX_UPLOAD_MB,
    DEFAULT_ORIGINS,
    EMBEDDINGS_ENABLED,
    LLM_PROVIDER,
    LLM_QUERY_REWRITE,
    OLLAMA_MODEL,
    OLLAMA_URL,
)
from embeddings import NullEmbedder, OllamaEmbedder
from extraction import ExtractionError
from index import SearchIndex
from highlight import highlight_chunk
from ingest import process_pdf
from models import (
    ChatRequest,
    ChatResponse,
    DebugSearchRequest,
    DocumentMeta,
    OperationRequest,
    OperationResponse,
    ProviderStatus,
)
from ocr import is_ocr_available, ocr_status_detail
from operations import run_operation
from providers import (
    OllamaProvider,
    build_retrieval_answer,
    get_answer_provider,
)
from query_rewrite import rewrite_query
from storage import Store, safe_filename


# Aliases for backwards compatibility with tests and existing imports
build_answer = build_retrieval_answer


def read_limited(upload: UploadFile, limit: int) -> bytes:
    """Read an upload while enforcing the configured size limit."""
    data = bytearray()
    while block := upload.file.read(1024 * 1024):
        data += block
        if len(data) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {limit // (1024 * 1024) or 1} MB).",
            )
    return bytes(data)


def create_app(
    data_dir=None,
    max_upload_bytes: Optional[int] = None,
    origins: Optional[list[str]] = None,
    embedder=None,
) -> FastAPI:
    data_dir = Path(
        data_dir
        or os.getenv("CLOUDDOC_DATA_DIR")
        or BASE_DIR / "data"
    )

    if max_upload_bytes is None:
        mb = float(
            os.getenv("CLOUDDOC_MAX_UPLOAD_MB", DEFAULT_MAX_UPLOAD_MB)
        )
        max_upload_bytes = int(mb * 1024 * 1024)

    if origins is None:
        raw = os.getenv(
            "CLOUDDOC_FRONTEND_ORIGINS",
            ",".join(DEFAULT_ORIGINS),
        )
        origins = [origin.strip() for origin in raw.split(",") if origin.strip()]

    if embedder is None:
        embedder = OllamaEmbedder() if EMBEDDINGS_ENABLED else NullEmbedder()

    store = Store(data_dir)
    search_index = SearchIndex(store, data_dir, embedder)
    app = FastAPI(title="CloudDoc AI Backend", version="1.1.0")
    app.state.store = store
    app.state.search_index = search_index

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request, exc: HTTPException):
        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled(_request, _exc):
        return JSONResponse(
            {"detail": "Internal server error."},
            status_code=500,
        )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/provider/status", response_model=ProviderStatus)
    def provider_status():
        ollama_provider = OllamaProvider(base_url=OLLAMA_URL, model=OLLAMA_MODEL)
        ollama_ok = ollama_provider.is_available()
        ocr_ok = is_ocr_available()
        semantic_ok = bool(embedder.is_available())

        active_provider = "ollama" if (LLM_PROVIDER == "ollama" or (LLM_PROVIDER == "auto" and ollama_ok)) else "retrieval"

        if active_provider == "ollama":
            details = f"Local AI model '{OLLAMA_MODEL}' (Ollama) is active and connected."
        else:
            details = "Retrieval-only mode active. Reliable local evidence matching with zero model dependencies."

        if semantic_ok:
            details += f" Semantic search: on ({embedder.model} + BM25)."
        else:
            details += " Semantic search: off (BM25 + synonym expansion only)."
        details += " OCR: ready." if ocr_ok else f" OCR: off - {ocr_status_detail()}"

        return {
            "provider": active_provider,
            "ollama_url": OLLAMA_URL,
            "ollama_model": OLLAMA_MODEL,
            "ollama_available": ollama_ok,
            "ocr_available": ocr_ok,
            "details": details,
        }

    @app.post(
        "/api/documents",
        response_model=DocumentMeta,
        status_code=201,
    )
    def upload_document(file: UploadFile = File(...)):
        original_name = file.filename or ""

        if not original_name.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail="Only .pdf files are accepted.",
            )

        data = read_limited(file, max_upload_bytes)

        if not data:
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is empty.",
            )

        if b"%PDF-" not in data[:1024]:
            raise HTTPException(
                status_code=400,
                detail="File is not a valid PDF.",
            )

        doc_id = str(uuid.uuid4())
        filename = safe_filename(original_name)

        try:
            result, chunks = process_pdf(data, doc_id, filename)
        except ExtractionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

        now = datetime.now(timezone.utc).isoformat()
        meta = {
            "id": doc_id,
            "filename": filename,
            "size_bytes": len(data),
            "page_count": len(result.records),
            "chunk_count": len(chunks),
            "uploaded_at": now,
            "indexed_at": now,
            "status": "ready",
            "ocr_applied": bool(result.ocr_pages),
        }

        store.save(meta, chunks, data, pages=result.page_dicts())
        search_index.rebuild()  # index (and embeddings, when available) rebuilt on upload
        return meta

    @app.get(
        "/api/documents",
        response_model=list[DocumentMeta],
    )
    def list_documents():
        return store.list_meta()

    @app.delete("/api/documents/{document_id}")
    def delete_document(document_id: str):
        meta = store.get_meta(document_id)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        deleted = store.delete(document_id)
        if not deleted:
            raise HTTPException(
                status_code=500,
                detail="Could not delete document files.",
            )

        search_index.rebuild()  # index rebuilt on delete
        return {"status": "deleted", "id": document_id}

    @app.get("/api/documents/{document_id}/file")
    def get_document_file(document_id: str, highlight: Optional[str] = None):
        """The original PDF. With ?highlight=<chunk_id> a copy with that evidence highlighted is served."""
        meta = store.get_meta(document_id)
        if meta is None:
            raise HTTPException(
                status_code=404,
                detail="Document not found.",
            )

        pdf_bytes = store.get_pdf_bytes(document_id)
        if pdf_bytes is None:
            raise HTTPException(
                status_code=404,
                detail="Document PDF file is missing.",
            )

        highlighted = 0
        if highlight:
            chunk = next(
                (c for c in store.get_chunks(document_id) if c.get("chunk_id") == highlight),
                None,
            )
            if chunk is not None:
                try:
                    pdf_bytes, highlighted = highlight_chunk(pdf_bytes, chunk)
                except Exception:  # never fail the preview because of a highlight problem
                    highlighted = 0

        filename = meta.get("filename", "document.pdf")
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'inline; filename="{filename}"',
                "X-Highlight-Count": str(highlighted),
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/chat", response_model=ChatResponse)
    def chat(request: ChatRequest):
        if request.document_id:
            meta = store.get_meta(request.document_id)
            if meta is None:
                raise HTTPException(
                    status_code=404,
                    detail="Document not found.",
                )
            metas = [meta]
        else:
            metas = store.list_meta()

        # Friendly conversational greeting check so simple greetings/introductions
        # receive an immediate helpful response instead of failing a document search.
        raw_q = request.question.strip().lower()
        clean_q = re.sub(r"[^\w\s]", "", raw_q).strip()
        greetings = {
            "hi", "hello", "hey", "hola", "howdy", "greetings",
            "good morning", "good afternoon", "good evening",
            "who are you", "what are you", "what is this", "what is clouddoc",
            "what can you do", "help", "thanks", "thank you", "how are you",
        }
        is_greeting = (
            clean_q in greetings
            or clean_q.startswith("hi ")
            or clean_q.startswith("hello ")
            or clean_q.startswith("hey ")
            or clean_q.startswith("who are you")
            or clean_q.startswith("what can you")
        )

        if is_greeting:
            provider = get_answer_provider()
            is_ai = isinstance(provider, OllamaProvider) and provider.is_available()
            if metas:
                doc_str = f"You have {len(metas)} document{'s' if len(metas) != 1 else ''} indexed and ready in the library."
            else:
                doc_str = "No documents are uploaded yet. Click the upload area or drop a PDF to get started."

            if is_ai:
                msg = (
                    f"Hello! I am CloudDoc AI, your document assistant powered by your local {OLLAMA_MODEL} model. "
                    f"{doc_str} "
                    "Ask me any question about your documents, or use the Quick Analysis tools on the left to extract summaries, key points, or deadlines."
                )
                return {
                    "answer": msg,
                    "sources": [],
                    "provider": "ollama",
                    "mode": "generated_ai",
                    "model": OLLAMA_MODEL,
                }
            else:
                msg = (
                    f"Hello! I am CloudDoc AI, your evidence-grounded document assistant. "
                    f"{doc_str} "
                    "Ask me any question about your uploaded documents, or select a Quick Analysis tool on the left to analyze your files."
                )
                return {
                    "answer": msg,
                    "sources": [],
                    "provider": "retrieval",
                    "mode": "retrieval_only",
                    "model": None,
                }

        if not metas:
            return {
                "answer": "No documents have been uploaded yet. Upload a PDF first.",
                "sources": [],
                "provider": "retrieval",
                "mode": "retrieval_only",
                "model": None,
            }

        provider = get_answer_provider()

        variants: list[str] = []
        if LLM_QUERY_REWRITE and isinstance(provider, OllamaProvider):
            variants = provider.keyword_variants(request.question)
        plan = rewrite_query(request.question, variants)

        doc_ids = {m["id"] for m in metas} if request.document_id else None
        sources = search_index.search(request.question, plan, doc_ids=doc_ids)

        scope_desc = (
            "the selected document"
            if request.document_id
            else "the uploaded documents"
        )

        res = provider.generate_answer(
            question=request.question,
            sources=sources,
            scope_description=scope_desc,
        )

        return {
            "answer": res["answer"],
            "sources": sources,
            "provider": res.get("provider", "retrieval"),
            "mode": res.get("mode", "retrieval_only"),
            "model": res.get("model"),
        }

    @app.post("/api/operations", response_model=OperationResponse)
    def perform_operation(request: OperationRequest):
        doc_tuples = []
        for doc_id in request.document_ids:
            meta = store.get_meta(doc_id)
            if not meta:
                raise HTTPException(
                    status_code=404,
                    detail=f"Document with ID {doc_id} not found.",
                )
            chunks = store.get_chunks(doc_id)
            doc_tuples.append((meta, chunks))

        result = run_operation(
            operation=request.operation,
            doc_tuples=doc_tuples,
            custom_query=request.query,
        )

        return result

    # ------------------------------------------------------------------ diagnostics
    if DEBUG_ENDPOINTS:

        @app.get("/api/debug/documents/{document_id}")
        def debug_document(document_id: str):
            """Page count, extracted text length per page, chunk count and chunk previews."""
            meta = store.get_meta(document_id)
            if meta is None:
                raise HTTPException(status_code=404, detail="Document not found.")

            pages = store.get_pages(document_id)
            page_source = "stored extraction"
            if pages is None:
                page_source = "legacy document: re-measured from original.pdf (native text only, no OCR)"
                pages = []
                pdf_bytes = store.get_pdf_bytes(document_id)
                if pdf_bytes:
                    try:
                        with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
                            for number, page in enumerate(doc, start=1):
                                n = len(page.get_text("text").strip())
                                pages.append({"page": number, "chars": n, "native_chars": n,
                                              "ocr": False, "note": ""})
                    except Exception:
                        pages = []

            chunks = store.get_chunks(document_id)
            return {
                "document_id": document_id,
                "filename": meta.get("filename"),
                "page_count": meta.get("page_count", len(pages)),
                "ocr_applied": meta.get("ocr_applied", False),
                "extraction_source": page_source,
                "pages": [
                    {
                        "page": p["page"],
                        "text_chars": p.get("chars", 0),
                        "native_text_chars": p.get("native_chars", p.get("chars", 0)),
                        "ocr_used": p.get("ocr", False),
                        "note": p.get("note", ""),
                    }
                    for p in pages
                ],
                "chunk_count": len(chunks),
                "chunks": [
                    {
                        "chunk_id": c.get("chunk_id"),
                        "page": c.get("page"),
                        "section": c.get("section"),
                        "words": c.get("word_count"),
                        "preview": (c.get("text") or "")[:300],
                    }
                    for c in chunks
                ],
            }

        @app.post("/api/debug/search")
        def debug_search(request: DebugSearchRequest):
            """Top 10 chunks with raw BM25 / semantic / fused scores and the preprocessed query."""
            if request.document_id:
                meta = store.get_meta(request.document_id)
                if meta is None:
                    raise HTTPException(status_code=404, detail="Document not found.")
                metas = [meta]
                doc_ids: Optional[set[str]] = {meta["id"]}
            else:
                metas = store.list_meta()
                doc_ids = None

            plan = rewrite_query(request.question)
            index = search_index.get()
            query_vec = search_index.query_vector(index, request.question)
            return {
                "question": request.question,
                "document_id": request.document_id,
                "query": plan.describe(),
                "semantic_search": {
                    "active": query_vec is not None,
                    "model": getattr(embedder, "model", "none"),
                },
                "chunks_in_scope": index.scope_size(doc_ids),
                "results": index.explain(plan, doc_ids, query_vec, limit=10),
            }

    # Mount static frontend files for single-command full-stack serving
    frontend_dir = BASE_DIR.parent / "frontend"
    if frontend_dir.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return app


app = create_app()
