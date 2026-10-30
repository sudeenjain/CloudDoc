"""Resume retrieval regression tests: text PDFs, image-only (OCR) PDFs, scoping, hybrid search."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import extraction  # noqa: E402
import providers  # noqa: E402
from chunking import build_page_chunks, detect_heading, detect_page_title  # noqa: E402
from embeddings import NullEmbedder  # noqa: E402
from extraction import extract_pdf  # noqa: E402
from main import create_app  # noqa: E402
from ocr import is_ocr_available  # noqa: E402
from query_rewrite import rewrite_query  # noqa: E402
from reindex import reindex  # noqa: E402
from sample_pdfs import (  # noqa: E402
    EXPECTED,
    RESUME_LINES,
    make_image_resume,
    make_pdf,
    make_text_resume,
    make_two_column_resume,
)
from storage import Store  # noqa: E402
from text_utils import raw_words, tokenize  # noqa: E402

needs_ocr = pytest.mark.skipif(
    not is_ocr_available(),
    reason="Tesseract OCR is not installed (see README: install tesseract-ocr and pytesseract)",
)

QUESTIONS = [
    ("in which college he is studying?", "college"),
    ("which university did he attend?", "university"),
    ("what is his degree?", "degree"),
    ("what are his skills?", "skills"),
    ("where did he intern?", "intern"),
    ("what is his email?", "email"),
]


def squash(text: str) -> str:
    return "".join(text.lower().split())


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "LLM_PROVIDER", "retrieval")

    def factory(embedder=None, data_dir=None):
        return TestClient(create_app(
            data_dir=data_dir or tmp_path,
            max_upload_bytes=2_000_000,
            embedder=embedder or NullEmbedder(),
        ))

    return factory


@pytest.fixture
def client(make_client):
    return make_client()


def upload(client, data, name):
    res = client.post("/api/documents", files={"file": (name, data, "application/pdf")})
    assert res.status_code == 201, res.text
    return res.json()


def ask(client, question, document_id=None):
    res = client.post("/api/chat", json={"question": question, "document_id": document_id})
    assert res.status_code == 200, res.text
    return res.json()


# ----------------------------------------------------------------------------- the reported bug
@pytest.mark.parametrize("question,key", QUESTIONS)
def test_text_resume_questions_return_the_right_section(client, question, key):
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    body = ask(client, question, doc["id"])

    assert body["sources"], "retrieval returned nothing for a question the resume answers"
    top = body["sources"][0]
    assert EXPECTED[key] in top["text"], f"top source was: {top['text']!r}"
    assert top["filename"] == "resume_text.pdf" and top["document_id"] == doc["id"]
    assert body["mode"] == "retrieval_only"
    assert {"document_id", "filename", "page", "text", "score"} <= set(top)


@needs_ocr
@pytest.mark.parametrize("question,key", QUESTIONS)
def test_image_only_resume_questions_work_after_ocr(client, question, key):
    doc = upload(client, make_image_resume(), "resume_scan.pdf")
    body = ask(client, question, doc["id"])

    assert body["sources"]
    expected = EXPECTED[key]
    if key == "skills":
        expected = "Python, Java"  # OCR may misread "SQL"; the rest is stable
    assert squash(expected) in squash(body["sources"][0]["text"]), body["sources"][0]["text"]


@needs_ocr
def test_image_only_pdf_triggers_ocr(client):
    doc = upload(client, make_image_resume(), "resume_scan.pdf")
    assert doc["ocr_applied"] is True

    info = client.get(f"/api/debug/documents/{doc['id']}").json()
    page = info["pages"][0]
    assert page["native_text_chars"] == 0, "the PDF has no text layer"
    assert page["ocr_used"] is True
    assert page["text_chars"] > 50

    status = client.get("/api/provider/status").json()
    assert status["ocr_available"] is True


def test_image_only_pdf_without_ocr_is_rejected_honestly(client, monkeypatch):
    monkeypatch.setattr(extraction, "is_ocr_available", lambda: False)
    res = client.post("/api/documents", files={"file": ("scan.pdf", make_image_resume(), "application/pdf")})
    assert res.status_code == 422
    assert "tesseract" in res.json()["detail"].lower()


def test_provider_status_reports_real_ocr_state(client, monkeypatch):
    import main
    monkeypatch.setattr(main, "is_ocr_available", lambda: False)
    status = client.get("/api/provider/status").json()
    assert status["ocr_available"] is False
    assert "OCR: off" in status["details"]


@needs_ocr
def test_only_low_text_pages_are_ocred(tmp_path):
    text_pdf = pymupdf.open(stream=make_text_resume(), filetype="pdf")
    scan_pdf = pymupdf.open(stream=make_image_resume(), filetype="pdf")
    text_pdf.insert_pdf(scan_pdf)
    mixed = text_pdf.tobytes()

    result = extract_pdf(mixed)
    assert [r.ocr for r in result.records] == [False, True]
    assert result.records[0].native_chars > 200


# ----------------------------------------------------------------------------- zero chunks / honesty
def test_no_matching_chunks_returns_honest_not_found(client):
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    body = ask(client, "quarterly revenue forecast for Mars colony", doc["id"])
    assert body["sources"] == []
    assert "couldn't find" in body["answer"]
    assert body["mode"] != "generated_ai" and body["model"] is None


def test_zero_chunks_never_reports_generated_ai_even_with_ollama_provider(client, monkeypatch):
    monkeypatch.setattr(providers, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(providers, "OLLAMA_URL", "http://127.0.0.1:9")  # nothing listens here
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    body = ask(client, "quarterly revenue forecast for Mars colony", doc["id"])
    assert body["sources"] == []
    assert body["mode"] == "retrieval_only"
    assert body["provider"] == "retrieval"
    assert body["model"] is None

    direct = providers.OllamaProvider().generate_answer("anything", [], "the selected document")
    assert direct["mode"] == "retrieval_only" and direct["model"] is None


def test_empty_library_is_not_a_search(client):
    body = ask(client, "what is his email?")
    assert body["sources"] == []
    assert body["mode"] == "retrieval_only"


# ----------------------------------------------------------------------------- scoping, dedup, sources
def test_document_id_scope_only_returns_that_document(client):
    text_doc = upload(client, make_text_resume(), "resume_text.pdf")
    two_col = upload(client, make_two_column_resume(), "isha.pdf")

    scoped = ask(client, "what are his skills?", two_col["id"])
    assert scoped["sources"]
    assert {s["document_id"] for s in scoped["sources"]} == {two_col["id"]}
    assert "Rust" in scoped["sources"][0]["text"]

    scoped_other = ask(client, "what are his skills?", text_doc["id"])
    assert {s["document_id"] for s in scoped_other["sources"]} == {text_doc["id"]}

    everywhere = ask(client, "what are his skills?")
    assert {s["document_id"] for s in everywhere["sources"]} == {text_doc["id"], two_col["id"]}
    assert {s["filename"] for s in everywhere["sources"]} == {"resume_text.pdf", "isha.pdf"}


def test_duplicate_resumes_are_deduplicated_but_keep_their_source_document(client):
    a = upload(client, make_text_resume(), "resume_v1.pdf")
    b = upload(client, make_text_resume(), "resume_v2.pdf")
    other = upload(client, make_two_column_resume(), "isha.pdf")

    body = ask(client, "which university did he attend?")
    education_hits = [s for s in body["sources"] if "Sapphire University" in s["text"]]
    assert len(education_hits) == 1, "identical chunks from the same person's resumes must collapse"
    assert education_hits[0]["filename"] in {"resume_v1.pdf", "resume_v2.pdf"}
    assert education_hits[0]["document_id"] in {a["id"], b["id"]}
    assert all(s["filename"] and s["document_id"] for s in body["sources"])
    assert other["id"]  # a different person's resume can still appear as its own source


def test_response_schema_is_unchanged(client):
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    body = ask(client, "what is his email?", doc["id"])
    assert set(body) == {"answer", "sources", "provider", "mode", "model"}
    assert {"document_id", "filename", "page", "text", "score"} <= set(body["sources"][0])
    assert 0 < body["sources"][0]["score"] <= 1


def test_weak_matches_are_not_discarded(client):
    """Only one word overlaps; the old 0.05 threshold dropped this kind of match."""
    doc = upload(client, make_pdf(["The committee reviewed procurement. Budget approved by finance."]), "memo.pdf")
    body = ask(client, "was the budget approved on time by anyone senior at the firm?", doc["id"])
    assert body["sources"], "a weak but real lexical match must still be returned"


# ----------------------------------------------------------------------------- generated answers
def test_llm_prompt_contains_only_retrieved_chunks_and_bad_citations_are_removed(client, monkeypatch):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": (
                "He studies at Sapphire University of Technology [Doc: resume_text.pdf, Page: 1] "
                "and also [Doc: invented.pdf, Page: 7]."
            )}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, **kwargs):
            seen["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(providers, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(providers, "httpx", SimpleNamespace(Client=FakeClient))
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    body = ask(client, "in which college he is studying?", doc["id"])

    assert body["mode"] == "generated_ai" and body["model"]
    assert "[Doc: resume_text.pdf, Page: 1]" in body["answer"]
    assert "invented.pdf" not in body["answer"]
    prompt = seen["payload"]["prompt"]
    assert "Sapphire University of Technology" in prompt
    assert seen["payload"]["options"]["temperature"] == 0
    assert prompt.count("<evidence ") == len(body["sources"])


def test_llm_keyword_variants_are_parsed(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"response": 'Sure! ["university name", "institute degree", "school"]'}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, **kwargs):
            assert json["options"]["temperature"] == 0
            return FakeResponse()

    monkeypatch.setattr(providers, "httpx", SimpleNamespace(Client=FakeClient))
    variants = providers.OllamaProvider().keyword_variants("which college?")
    assert variants == ["university name", "institute degree", "school"]
    plan = rewrite_query("which college?", variants)
    assert plan.llm_variants == variants and "university" in plan.bm25_tokens


# ----------------------------------------------------------------------------- query rewriting
def test_query_rewrite_strips_pronouns_and_filler():
    plan = rewrite_query("in which college he is studying?")
    assert plan.content_words == ["college", "studying"]
    for noise in ("he", "in", "which", "is"):
        assert noise not in plan.bm25_tokens


def test_query_rewrite_expands_synonyms():
    edu = rewrite_query("in which college he is studying?")
    assert "education" in edu.intents
    assert {"university", "institute", "btech", "cgpa"} <= set(edu.expansion_terms)

    assert "contact" in rewrite_query("what is his email?").intents
    assert "emailaddr" in rewrite_query("what is his email?").expansion_terms
    assert "internship" in rewrite_query("where did he intern?").intents
    assert "skills" in rewrite_query("what are his skills?").intents
    assert "projects" in rewrite_query("which projects has he built?").intents
    assert "certifications" in rewrite_query("any certificates?").intents


def test_degree_abbreviations_are_normalised():
    assert "btech" in tokenize("B.Tech in Computer Science")
    assert raw_words("B.Tech")[0] == "btech"


# ----------------------------------------------------------------------------- chunking
def test_chunks_split_on_resume_headings_and_carry_context():
    chunks = build_page_chunks(["\n".join(RESUME_LINES)], "doc1", "resume.pdf")
    assert [c["section"] for c in chunks] == [
        "Contact", "Summary", "Education", "Experience", "Skills", "Projects", "Certifications",
    ]
    for chunk in chunks:
        assert chunk["text"].startswith("Document: resume.pdf | Section: " + chunk["section"])
    education = next(c for c in chunks if c["section"] == "Education")
    assert "Sapphire University of Technology" in education["body"]
    assert "Orion Cloud Labs" not in education["body"]


def test_headingless_text_uses_overlapping_windows():
    lines = [" ".join(f"w{line * 10 + i}" for i in range(10)) for line in range(40)]  # 400 words
    chunks = build_page_chunks(["\n".join(lines)], "doc2", "notes.pdf", chunk_words=170, overlap=25)
    assert len(chunks) >= 3
    assert all(c["section"] == "Document" for c in chunks)
    assert all(c["word_count"] <= 170 for c in chunks)
    first, second = chunks[0]["body"].split(), chunks[1]["body"].split()
    shared = set(first) & set(second)
    assert 0 < len(shared) <= 30  # roughly 15 % overlap
    assert {w for c in chunks for w in c["body"].split()} == {f"w{i}" for i in range(400)}


def test_one_huge_line_still_gets_overlap():
    text = " ".join(f"t{i}" for i in range(500))
    chunks = build_page_chunks([text], "doc3", "blob.pdf", chunk_words=170, overlap=25)
    assert len(chunks) >= 3
    assert len(set(chunks[0]["body"].split()) & set(chunks[1]["body"].split())) > 0


def test_long_section_is_split_but_keeps_its_title():
    body = "\n".join(f"Worked on service {i} using Python and Docker in production" for i in range(60))
    chunks = build_page_chunks(["EXPERIENCE\n" + body], "doc4", "cv.pdf")
    assert len(chunks) > 1
    assert all(c["section"] == "Experience" and "Section: Experience" in c["text"] for c in chunks)


def test_heading_detection():
    assert detect_heading("EDUCATION")[1] == "education"
    assert detect_heading("Technical Skills")[1] == "skills"
    assert detect_heading("Education:")[1] == "education"
    assert detect_heading("WORK EXPERIENCE")[1] == "experience"
    assert detect_heading("Machine Learning Intern") is None
    assert detect_heading("PROJECT MANAGER") is None
    assert detect_heading("E D U C A T I O N")[1] == "education"
    assert detect_heading("W O R K   E X P E R I E N C E")[0] == "Work Experience"
    assert detect_heading("Python, Java, SQL") is None
    assert detect_heading("I gained experience in many projects while studying.") is None


# ----------------------------------------------------------------------------- extraction
def test_two_column_layout_is_read_column_by_column():
    page = extract_pdf(make_two_column_resume()).pages[0]
    assert page.index("Hindi") < page.index("EDUCATION"), "left column must finish before the right starts"
    assert page.index("Riverbend") < page.index("EXPERIENCE") < page.index("PROJECTS")


def test_two_column_resume_answers_education_question(client):
    doc = upload(client, make_two_column_resume(), "isha.pdf")
    body = ask(client, "which institute did she attend?", doc["id"])
    assert "Riverbend Institute of Technology" in body["sources"][0]["text"]


# ----------------------------------------------------------------------------- hybrid search
class ConceptEmbedder:
    """Tiny deterministic stand-in for an embedding model: groups synonyms into the same dimension."""

    model = "concept-test"
    GROUPS = [
        {"education", "university", "college", "school", "alma", "mater", "polytechnic", "study", "studied"},
        {"python", "java", "skill", "programming"},
        {"email", "contact", "phone"},
    ]

    def is_available(self):
        return True

    def _vec(self, text):
        words = raw_words(text)
        v = np.array([sum(w in g for w in words) for g in self.GROUPS] + [0.05], dtype=np.float32)
        return v / np.linalg.norm(v)

    def embed_documents(self, texts):
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


def test_semantic_search_finds_chunks_with_zero_word_overlap(make_client, tmp_path):
    pdf = make_pdf([
        "Alma mater: Greenfield Polytechnic, electronics, 2019.",
        "Python and Java programming for backend services.",
    ])
    question = "where did he study?"

    lexical_only = make_client()
    doc = upload(lexical_only, pdf, "plain.pdf")
    assert ask(lexical_only, question, doc["id"])["sources"] == []

    hybrid = make_client(ConceptEmbedder(), data_dir=tmp_path / "hybrid")
    doc = upload(hybrid, pdf, "plain.pdf")
    body = ask(hybrid, question, doc["id"])
    assert body["sources"] and "Greenfield Polytechnic" in body["sources"][0]["text"]

    debug = hybrid.post("/api/debug/search", json={"question": question, "document_id": doc["id"]}).json()
    assert debug["semantic_search"]["active"] is True
    top = debug["results"][0]
    assert top["bm25_score"] == 0 and top["semantic_score"] > 0.5 and top["rrf_score"] > 0
    assert (tmp_path / "hybrid" / "documents" / doc["id"] / "embeddings.npy").is_file()


def test_reciprocal_rank_fusion_rewards_agreement(make_client, tmp_path):
    hybrid = make_client(ConceptEmbedder(), data_dir=tmp_path / "rrf")
    doc = upload(hybrid, make_text_resume(), "resume.pdf")
    debug = hybrid.post("/api/debug/search", json={"question": "which university did he attend?",
                                                    "document_id": doc["id"]}).json()
    top = debug["results"][0]
    assert top["section"] == "Education"
    assert top["bm25_rank"] == 1 and top["semantic_rank"] is not None  # present in both rankings
    assert top["score"] > 0.9  # close to the best possible fused score (1.0)
    assert top["rrf_score"] == pytest.approx(1 / 61 + 1 / (60 + top["semantic_rank"]), rel=1e-3)
    assert all(r["score"] <= top["score"] for r in debug["results"])


# ----------------------------------------------------------------------------- diagnostics
def test_debug_document_endpoint(client):
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    info = client.get(f"/api/debug/documents/{doc['id']}").json()
    assert info["page_count"] == 1
    assert info["pages"][0]["text_chars"] > 300
    assert info["chunk_count"] == len(info["chunks"]) == doc["chunk_count"] == 7
    assert all(len(c["preview"]) <= 300 for c in info["chunks"])
    assert info["chunks"][2]["section"] == "Education"
    assert client.get("/api/debug/documents/2f6d1f0e-8c53-4f7b-9d0a-6f1c1d9b7a11").status_code == 404


def test_debug_search_endpoint(client):
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    res = client.post("/api/debug/search", json={"question": "in which college he is studying?",
                                                  "document_id": doc["id"]}).json()
    assert res["query"]["terms_after_preprocessing"] == ["college", "studying"]
    assert "education" in res["query"]["intents"]
    assert 0 < len(res["results"]) <= 10
    first = res["results"][0]
    assert {"bm25_score", "bm25_rank", "semantic_score", "rrf_score", "score", "preview", "section"} <= set(first)
    assert first["section"] == "Education" and first["bm25_score"] > 0
    assert res["chunks_in_scope"] == doc["chunk_count"]


# ----------------------------------------------------------------------------- persistence / re-index
def test_index_is_persisted_rebuilt_on_delete_and_survives_restart(make_client, tmp_path):
    client = make_client()
    doc = upload(client, make_text_resume(), "resume_text.pdf")
    manifest = tmp_path / "index" / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert {e["doc_id"] for e in data["entries"]} == {doc["id"]}

    restarted = make_client()  # fresh process, same data directory, no re-upload
    assert "Sapphire University" in ask(restarted, "which university did he attend?")["sources"][0]["text"]

    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert json.loads(manifest.read_text(encoding="utf-8"))["entries"] == []
    assert ask(client, "which university did he attend?")["sources"] == []


def test_reindex_upgrades_legacy_documents_in_place(make_client, tmp_path):
    """A document stored by the old pipeline (80-word blocks, no sections) is re-indexed from its PDF."""
    store = Store(tmp_path)
    pdf = make_text_resume()
    doc_id = "5c1a52b4-47c1-4a43-9f1c-0d0b6a7d2e11"
    words = " ".join(RESUME_LINES).split()
    legacy_chunks = [
        {"page": 1, "chunk_id": f"{doc_id}_p1_c{i + 1}", "text": " ".join(words[s:s + 12]), "word_count": 12}
        for i, s in enumerate(range(0, len(words), 12))
    ]
    meta = {"id": doc_id, "filename": "legacy.pdf", "size_bytes": len(pdf), "page_count": 1,
            "chunk_count": len(legacy_chunks), "uploaded_at": "2026-01-01T00:00:00+00:00",
            "status": "ready", "ocr_applied": False}
    store.save(meta, legacy_chunks, pdf)

    client = make_client()
    legacy_debug = client.get(f"/api/debug/documents/{doc_id}").json()
    assert "legacy" in legacy_debug["extraction_source"]
    assert legacy_debug["pages"][0]["text_chars"] > 300
    ask(client, "which university did he attend?")  # builds the index from the legacy chunks

    lines = []
    summary = reindex(tmp_path, out=lines.append)  # the app keeps running; it must notice the change
    assert summary == {"reindexed": 1, "failed": 0}
    assert any("legacy.pdf" in line for line in lines)

    upgraded = client.get(f"/api/debug/documents/{doc_id}").json()
    assert upgraded["extraction_source"] == "stored extraction"
    assert "Education" in {c["section"] for c in upgraded["chunks"]}
    top = ask(client, "in which college he is studying?", doc_id)["sources"][0]
    assert "Sapphire University of Technology" in top["text"]
    assert top["text"].startswith("Document: legacy.pdf | Section: Education")


# ----------------------------------------------------------------------------- lecture-notes / slide documents
NOTES_PAGE_1 = (
    "Module 1\n"
    "1. Introduction to Language Processing\n"
    "This module introduces the field in a few short paragraphs for new students.\n"
    "2. Major Challenges in NLP Systems\n"
    "Ambiguity The primary hurdle is ambiguity, where one word carries several meanings.\n"
    "Context Dependency Meaning shifts based on the broader discourse or situation.\n"
    "Processing Formal vs. Natural Languages Formal languages are designed with rigid syntax "
    "and a finite vocabulary for deterministic"
)
NOTES_PAGE_2 = (
    "compilation. In contrast, natural languages are organic and stochastic, requiring "
    "probabilistic approaches to handle their inherent variability.\n"
    "3. The Relationship Between Language and Grammar\n"
    "Grammar provides the structural constraints that dictate how symbols are organised."
)


def test_numbered_headings_are_detected():
    assert detect_heading("2. Major Challenges in NLP Systems") == ("Major Challenges in NLP Systems", "section")
    assert detect_heading("3.1 Parsing Methods")[0] == "Parsing Methods"
    assert detect_heading("1. Consonant Doubling: Doubling the final consonant") is None  # list item
    assert detect_heading("1. Insertion") is None
    assert detect_heading("languages, focusing on:") is None  # wrapped sentence fragment
    assert detect_heading("multiple language families:") is None


def test_numbered_headings_become_section_labels():
    chunks = build_page_chunks([NOTES_PAGE_1, NOTES_PAGE_2], "d", "notes.pdf")
    sections = [c["section"] for c in chunks]
    assert "Major Challenges in NLP Systems" in sections
    assert "Introduction to Language Processing" in sections
    assert "Header" not in sections[1:]


def test_slide_titles_do_not_carry_over_to_the_next_slide():
    slides = [
        "3. Context-Free Grammar (CFG)\nA type of grammar where production rules follow a fixed form.",
        "Processing Indian Languages\nIt introduces the special challenges of Indian languages\n"
        "languages, focusing on:\nLack of electronic resources and tools",
        "Challenges of NLP\nNatural languages are complex, ambiguous and context-dependent.",
    ]
    chunks = build_page_chunks(slides, "d", "deck.pdf")
    assert [c["section"] for c in chunks] == [
        "Context-Free Grammar (CFG)", "Processing Indian Languages", "Challenges of NLP",
    ]
    assert detect_page_title(["Photosynthesis is the process by which plants convert", "x"]) is None


def test_sentence_cut_by_a_page_break_is_completed_in_the_chunk():
    chunks = build_page_chunks([NOTES_PAGE_1, NOTES_PAGE_2], "d", "notes.pdf")
    challenges = next(c for c in chunks if c["section"] == "Major Challenges in NLP Systems" and c["page"] == 1)
    assert challenges["body"].endswith("for deterministic")
    assert "compilation." in challenges["text"] and "organic and stochastic" in challenges["text"]
    assert "compilation" not in challenges["body"]  # the body itself stays page-exact


def test_page_straddling_answer_is_retrieved_as_one_passage(client):
    doc = upload(client, make_pdf([NOTES_PAGE_1, NOTES_PAGE_2]), "notes.pdf")
    body = ask(client, "What are the major challenges of an NLP system?", doc["id"])
    # The page-2 continuation may rank first (it carries the same section label); what matters is that
    # the retrieved set contains the whole section, including the fourth challenge and its explanation.
    whole = [s for s in body["sources"]
             if "Processing Formal vs. Natural Languages" in s["text"] and "organic and stochastic" in s["text"]]
    assert whole, [s["text"][:80] for s in body["sources"]]
    assert all(s["document_id"] == doc["id"] for s in body["sources"])


def test_answer_without_citations_gets_a_sources_consulted_line():
    sources = [
        {"filename": "a.pdf", "page": 1, "text": "x", "document_id": "d", "score": 1.0},
        {"filename": "a.pdf", "page": 1, "text": "y", "document_id": "d", "score": 0.9},
        {"filename": "b.pdf", "page": 4, "text": "z", "document_id": "e", "score": 0.8},
    ]
    uncited = providers.ensure_citations("Ambiguity is a challenge.", sources)
    assert uncited.endswith("Sources consulted: [Doc: a.pdf, Page: 1], [Doc: b.pdf, Page: 4]")
    cited = "Ambiguity is a challenge [Doc: a.pdf, Page: 1]."
    assert providers.ensure_citations(cited, sources) == cited
    not_found = providers.NOT_FOUND_SENTENCE
    assert providers.ensure_citations(not_found, sources) == not_found
    assert providers.ensure_citations("Nothing retrieved.", []) == "Nothing retrieved."


def test_round_bracket_citations_are_normalised_to_square_brackets():
    sources = [{"filename": "NLP_Module-1.pdf", "page": 1, "text": "x", "document_id": "d", "score": 1.0}]
    raw = (
        "NLP is a field (Doc: NLP_Module-1.pdf, Page: 1). It helps (doc: nlp_module-1.pdf, page 1), "
        "and also [Doc: NLP_Module-1.pdf, Page: 1] plus (Doc: invented.pdf, Page: 9)."
    )
    clean = providers.sanitize_citations(raw, sources)
    assert clean.count("[Doc: NLP_Module-1.pdf, Page: 1]") == 3
    assert "(Doc:" not in clean and "invented.pdf" not in clean
    # a round-bracket citation counts as a citation, so no "Sources consulted" line is added
    assert providers.ensure_citations(clean, sources) == clean
    assert providers.ensure_citations(
        "No cites here.", sources).endswith("Sources consulted: [Doc: NLP_Module-1.pdf, Page: 1]")


# ----------------------------------------------------------------------------- evidence highlighting in the preview
def _highlights(pdf_bytes, page=1):
    """(annotation types, annotation rects, words under the highlights); plain data, doc closed."""
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc:
        pg = doc[page - 1]
        annots = list(pg.annots() or [])
        types = [a.type[1] for a in annots]
        rects = [pymupdf.Rect(a.rect) for a in annots]
        words = {w[4] for r in rects for w in pg.get_text("words") if pymupdf.Rect(w[:4]).intersects(r)}
    return types, rects, words


def test_file_endpoint_highlights_the_evidence_chunk(client):
    original = make_text_resume()
    doc = upload(client, original, "resume_text.pdf")
    top = ask(client, "in which college he is studying?", doc["id"])["sources"][0]

    res = client.get(f"/api/documents/{doc['id']}/file", params={"highlight": top["chunk_id"]})
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert int(res.headers["x-highlight-count"]) >= 3

    types, _, words = _highlights(res.content)
    assert types and set(types) == {"Highlight"}
    assert {"Sapphire", "University", "CGPA:"} <= words      # the education lines are marked...
    assert "Orion" not in words and "Python," not in words   # ...and other sections are not


def test_file_endpoint_without_highlight_is_the_untouched_original(client):
    original = make_text_resume()
    doc = upload(client, original, "resume_text.pdf")
    plain = client.get(f"/api/documents/{doc['id']}/file")
    assert plain.content == original and plain.headers["x-highlight-count"] == "0"

    unknown = client.get(f"/api/documents/{doc['id']}/file", params={"highlight": "no-such-chunk"})
    assert unknown.status_code == 200 and unknown.content == original

    # asking for a highlight never changes the stored file
    ask(client, "what is his email?", doc["id"])
    client.get(f"/api/documents/{doc['id']}/file", params={"highlight": f"{doc['id']}_p1_c1"})
    assert client.get(f"/api/documents/{doc['id']}/file").content == original


def test_highlight_lands_on_the_page_of_the_evidence(client):
    pages = ["Introduction. Nothing relevant here at all, just filler text on page one.",
             "Photosynthesis converts sunlight, water and carbon dioxide into glucose and oxygen."]
    doc = upload(client, make_pdf(pages), "bio.pdf")
    top = ask(client, "how does photosynthesis convert sunlight?", doc["id"])["sources"][0]
    assert top["page"] == 2
    res = client.get(f"/api/documents/{doc['id']}/file", params={"highlight": top["chunk_id"]})
    assert _highlights(res.content, page=1)[0] == []
    assert "Photosynthesis" in _highlights(res.content, page=2)[2]


@needs_ocr
def test_highlight_works_on_image_only_pages_via_ocr(client):
    doc = upload(client, make_image_resume(), "resume_scan.pdf")
    top = ask(client, "in which college he is studying?", doc["id"])["sources"][0]
    res = client.get(f"/api/documents/{doc['id']}/file", params={"highlight": top["chunk_id"]})
    assert int(res.headers["x-highlight-count"]) >= 2
    types, rects, _ = _highlights(res.content)
    assert types
    # the marked area sits on the Education lines, in the upper half of the page, not on Skills/Projects
    y_mid = (rects[0].y0 + rects[0].y1) / 2
    assert 0.2 * 595 < y_mid < 0.55 * 595
