import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from embeddings import NullEmbedder  # noqa: E402
from main import create_app  # noqa: E402

LOCAL_ORIGIN = "http://localhost:5173"

BIOLOGY = [
    "Photosynthesis is the process by which plants convert sunlight, water and carbon dioxide "
    "into glucose and oxygen inside chloroplasts.",
    "Cellular respiration releases energy from glucose in the mitochondria.",
]
INVOICE = [
    "Invoice 2041. The total amount is payable within thirty days by bank transfer.",
    "Late payments incur a two percent monthly interest charge.",
]


def make_pdf(pages):
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(72, 72, 523, 770), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def client(tmp_path, monkeypatch):
    import providers
    monkeypatch.setattr(providers, "LLM_PROVIDER", "retrieval")
    return TestClient(create_app(data_dir=tmp_path, max_upload_bytes=200_000, embedder=NullEmbedder()))


def upload(client, pages, name="notes.pdf"):
    return client.post("/api/documents", files={"file": (name, make_pdf(pages), "application/pdf")})


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_rejects_non_pdf_extension(client):
    response = client.post("/api/documents", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400


def test_rejects_pdf_extension_with_non_pdf_content(client):
    response = client.post("/api/documents", files={"file": ("fake.pdf", b"just text", "application/pdf")})
    assert response.status_code == 400


def test_rejects_corrupt_pdf(client):
    response = client.post("/api/documents", files={"file": ("bad.pdf", b"%PDF-1.7 garbage", "application/pdf")})
    assert response.status_code == 400


def test_rejects_oversized_upload(client):
    big = b"%PDF-" + b"0" * 300_000
    response = client.post("/api/documents", files={"file": ("big.pdf", big, "application/pdf")})
    assert response.status_code == 413


def test_upload_returns_metadata_and_stores_by_uuid(client, tmp_path):
    response = upload(client, BIOLOGY, name="biology notes.pdf")
    assert response.status_code == 201
    meta = response.json()
    assert meta["filename"] == "biology notes.pdf"
    assert meta["page_count"] == 2
    assert meta["chunk_count"] >= 2
    assert meta["size_bytes"] > 0
    assert (tmp_path / "documents" / meta["id"] / "original.pdf").is_file()
    assert not list(tmp_path.rglob("biology notes*"))  # uploaded name is never used on disk


def test_filename_is_sanitised(client):
    meta = upload(client, BIOLOGY, name="../../evil name?.pdf").json()
    assert "/" not in meta["filename"] and "\\" not in meta["filename"] and ".." not in meta["filename"]
    assert meta["filename"].endswith(".pdf")


def test_list_documents(client):
    assert client.get("/api/documents").json() == []
    first = upload(client, BIOLOGY, name="a.pdf").json()
    second = upload(client, INVOICE, name="b.pdf").json()
    listed = client.get("/api/documents").json()
    assert {d["id"] for d in listed} == {first["id"], second["id"]}


def test_chat_returns_evidence_sources(client):
    doc = upload(client, BIOLOGY, name="bio.pdf").json()
    response = client.post("/api/chat", json={"question": "How do plants convert sunlight into glucose?", "document_id": None})
    assert response.status_code == 200
    body = response.json()
    assert body["sources"], "expected at least one source"
    top = body["sources"][0]
    assert top["document_id"] == doc["id"]
    assert top["filename"] == "bio.pdf"
    assert top["page"] == 1
    assert "Photosynthesis" in top["text"]
    assert 0 < top["score"] <= 1
    scores = [s["score"] for s in body["sources"]]
    assert scores == sorted(scores, reverse=True)
    assert "page 1" in body["answer"]


def test_chat_scoped_to_document_id(client):
    bio = upload(client, BIOLOGY, name="bio.pdf").json()
    invoice = upload(client, INVOICE, name="invoice.pdf").json()
    question = "What converts sunlight into glucose?"

    scoped_to_bio = client.post("/api/chat", json={"question": question, "document_id": bio["id"]}).json()
    assert scoped_to_bio["sources"]
    assert all(s["document_id"] == bio["id"] for s in scoped_to_bio["sources"])

    scoped_to_invoice = client.post("/api/chat", json={"question": question, "document_id": invoice["id"]}).json()
    assert scoped_to_invoice["sources"] == []


def test_chat_no_match(client):
    upload(client, BIOLOGY)
    response = client.post("/api/chat", json={"question": "quarterly revenue forecast for Mars colony", "document_id": None})
    assert response.status_code == 200
    body = response.json()
    assert body["sources"] == []
    assert "couldn't find" in body["answer"]
    assert body["mode"] != "generated_ai" and body["model"] is None


def test_chat_with_no_documents(client):
    response = client.post("/api/chat", json={"question": "anything", "document_id": None})
    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_chat_unknown_document_is_404(client):
    response = client.post("/api/chat", json={"question": "hello", "document_id": "2f6d1f0e-8c53-4f7b-9d0a-6f1c1d9b7a11"})
    assert response.status_code == 404


def test_chat_rejects_bad_input(client):
    assert client.post("/api/chat", json={"question": "   ", "document_id": None}).status_code == 422
    assert client.post("/api/chat", json={"question": "hi", "document_id": "../etc/passwd"}).status_code == 422
    assert client.post("/api/chat", json={"document_id": None}).status_code == 422


def test_cors_allows_only_local_frontend(client):
    headers = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    allowed = client.options("/api/chat", headers={**headers, "Origin": LOCAL_ORIGIN})
    assert allowed.headers.get("access-control-allow-origin") == LOCAL_ORIGIN
    blocked = client.options("/api/chat", headers={**headers, "Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in blocked.headers


def test_provider_status(client):
    res = client.get("/api/provider/status")
    assert res.status_code == 200
    data = res.json()
    assert "provider" in data
    assert "ollama_available" in data
    assert "ocr_available" in data
    assert "details" in data


def test_delete_document_success_and_404(client, tmp_path):
    doc = upload(client, BIOLOGY, name="to_delete.pdf").json()
    doc_id = doc["id"]
    doc_dir = tmp_path / "documents" / doc_id
    assert doc_dir.is_dir()

    # Delete document
    del_res = client.delete(f"/api/documents/{doc_id}")
    assert del_res.status_code == 200
    assert del_res.json() == {"status": "deleted", "id": doc_id}
    assert not doc_dir.exists()

    # Subsequent delete should return 404
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404
    # Subsequent chat scoped to deleted doc should return 404
    assert client.post("/api/chat", json={"question": "anything", "document_id": doc_id}).status_code == 404
    # List is now empty
    assert client.get("/api/documents").json() == []


def test_get_document_file_serves_pdf(client):
    doc = upload(client, BIOLOGY, name="biology.pdf").json()
    res = client.get(f"/api/documents/{doc['id']}/file")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert b"%PDF-" in res.content
    assert "biology.pdf" in res.headers["content-disposition"]


def test_get_document_file_unknown_id(client):
    res = client.get("/api/documents/2f6d1f0e-8c53-4f7b-9d0a-6f1c1d9b7a11/file")
    assert res.status_code == 404


def test_cross_document_isolation_strict(client):
    bio = upload(client, BIOLOGY, name="biology.pdf").json()
    inv = upload(client, INVOICE, name="invoice.pdf").json()

    # Scoped to bio: asking about invoice gives 0 sources
    res_bio = client.post("/api/chat", json={"question": "Invoice total amount payable", "document_id": bio["id"]}).json()
    assert res_bio["sources"] == []
    assert "couldn't find" in res_bio["answer"]

    # Scoped to invoice: asking about invoice gives invoice sources only
    res_inv = client.post("/api/chat", json={"question": "Invoice total amount payable", "document_id": inv["id"]}).json()
    assert res_inv["sources"]
    assert all(s["document_id"] == inv["id"] for s in res_inv["sources"])
    assert all(s["filename"] == "invoice.pdf" for s in res_inv["sources"])


def test_operations_summarize(client):
    bio = upload(client, BIOLOGY, name="biology.pdf").json()
    res = client.post("/api/operations", json={"operation": "summarize", "document_ids": [bio["id"]]})
    assert res.status_code == 200
    data = res.json()
    assert data["operation"] == "summarize"
    assert data["sources"]
    assert "page" in data["result"].lower()


def test_operations_key_points(client):
    bio = upload(client, BIOLOGY, name="biology.pdf").json()
    res = client.post("/api/operations", json={"operation": "key_points", "document_ids": [bio["id"]]})
    assert res.status_code == 200
    data = res.json()
    assert data["operation"] == "key_points"
    assert data["sources"]


def test_operations_deadlines(client):
    inv = upload(client, INVOICE, name="invoice.pdf").json()
    res = client.post("/api/operations", json={"operation": "deadlines", "document_ids": [inv["id"]]})
    assert res.status_code == 200
    data = res.json()
    assert data["operation"] == "deadlines"
    assert data["sources"]


def test_operations_costs(client):
    inv = upload(client, INVOICE, name="invoice.pdf").json()
    res = client.post("/api/operations", json={"operation": "costs", "document_ids": [inv["id"]]})
    assert res.status_code == 200
    data = res.json()
    assert data["operation"] == "costs"
    assert data["sources"]


def test_operations_compare(client):
    bio = upload(client, BIOLOGY, name="biology.pdf").json()
    inv = upload(client, INVOICE, name="invoice.pdf").json()
    res = client.post("/api/operations", json={"operation": "compare", "document_ids": [bio["id"], inv["id"]]})
    assert res.status_code == 200
    data = res.json()
    assert data["operation"] == "compare"
    assert "biology.pdf" in data["result"]
    assert "invoice.pdf" in data["result"]
    assert len(data["sources"]) >= 2
    doc_ids_in_sources = {s["document_id"] for s in data["sources"]}
    assert bio["id"] in doc_ids_in_sources
    assert inv["id"] in doc_ids_in_sources


def test_operations_rejects_invalid_inputs(client):
    assert client.post("/api/operations", json={"operation": "invalid_op", "document_ids": ["2f6d1f0e-8c53-4f7b-9d0a-6f1c1d9b7a11"]}).status_code == 422
    assert client.post("/api/operations", json={"operation": "summarize", "document_ids": []}).status_code == 422
    assert client.post("/api/operations", json={"operation": "summarize", "document_ids": ["2f6d1f0e-8c53-4f7b-9d0a-6f1c1d9b7a11"]}).status_code == 404


def test_ollama_fallback_when_offline(client, monkeypatch):
    import providers
    monkeypatch.setattr(providers, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(providers, "OLLAMA_URL", "http://127.0.0.1:9999")
    doc = upload(client, BIOLOGY, name="bio.pdf").json()
    res = client.post("/api/chat", json={"question": "What is photosynthesis?", "document_id": doc["id"]})
    assert res.status_code == 200
    body = res.json()
    assert body["sources"]
    assert "photosynthesis" in body["answer"].lower()
    assert "unavailable" in body["answer"].lower() or "retrieval mode" in body["answer"].lower()


def test_chat_greeting(client):
    res = client.post("/api/chat", json={"question": "hi"})
    assert res.status_code == 200
    data = res.json()
    assert "Hello!" in data["answer"] or "CloudDoc AI" in data["answer"]


def test_chat_retrieval_keyword_match(client):
    doc = upload(client, ["Sudheen Kumar is a cloud computing engineer."], name="resume.pdf").json()
    res = client.post("/api/chat", json={"question": "who is Sudheen?", "document_id": doc["id"]})
    assert res.status_code == 200
    body = res.json()
    assert len(body["sources"]) >= 1
    assert "Sudheen" in body["sources"][0]["text"]


def test_near_duplicate_suppression():
    from retrieval import retrieve
    meta = {"id": "doc1", "filename": "test.pdf"}
    chunks = [
        {"page": 1, "chunk_id": "c1", "text": "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"},
        {"page": 1, "chunk_id": "c2", "text": "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu"},
        {"page": 2, "chunk_id": "c3", "text": "Completely different text with delta epsilon zeta and unique words"},
    ]
    results = retrieve("delta epsilon", [(meta, chunks)], top_k=5, min_score=0.01)
    page_1_results = [r for r in results if r["page"] == 1]
    assert len(page_1_results) == 1


def test_rejects_empty_scanned_pdf_without_ocr(client, monkeypatch):
    import extraction
    monkeypatch.setattr(extraction, "is_ocr_available", lambda: False)
    doc = pymupdf.open()
    page = doc.new_page()
    # Draw an empty vector shape / image drawing with zero text
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(10, 10, 200, 200))
    shape.finish(fill=(0.8, 0.8, 0.8))
    shape.commit()
    data = doc.tobytes()
    doc.close()

    res = client.post("/api/documents", files={"file": ("scanned.pdf", data, "application/pdf")})
    assert res.status_code == 422
    assert "no extractable text" in res.json()["detail"].lower()


