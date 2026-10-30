"""Specialized document operations grounded strictly in retrieved evidence."""
from __future__ import annotations

from typing import Any
from chunking import make_snippet
from retrieval import retrieve


OPERATION_QUERIES = {
    "summarize": "summary overview introduction purpose main objective conclusion highlights findings",
    "key_points": "key points important core facts critical requirements highlights findings",
    "deadlines": "date deadline due timeline schedule expiry period by days months year duration payable thirty sixty interest",
    "people": "person people responsible responsibility role manager officer team assigned contact party signatory director",
    "costs": "cost price fee total amount payment invoice charge rate dollar currency tax discount payable",
}

OPERATION_TITLES = {
    "summarize": "Document Summary",
    "key_points": "Key Points & Takeaways",
    "deadlines": "Dates & Deadlines",
    "people": "People & Responsibilities",
    "costs": "Costs, Amounts & Fees",
    "compare": "Multi-Document Comparison",
}


def _flat(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse line breaks in chunk text so bullet formatting stays on one line."""
    return [{**s, "text": " ".join(str(s["text"]).split())} for s in sources]


def _get_representative_chunks(
    doc_tuples: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Sample representative passages across pages when keyword queries yield no lexical matches."""
    results: list[dict[str, Any]] = []
    for meta, chunks in doc_tuples:
        seen_pages = set()
        for c in chunks:
            if c["page"] not in seen_pages:
                seen_pages.add(c["page"])
                results.append({
                    "document_id": meta["id"],
                    "filename": meta["filename"],
                    "page": c["page"],
                    "chunk_id": c.get("chunk_id", f"{meta['id']}_p{c['page']}"),
                    "text": make_snippet(c["text"]),
                    "score": 1.0,
                })
            if len(results) >= limit:
                break
    return results


def run_operation(
    operation: str,
    doc_tuples: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    custom_query: str | None = None,
) -> dict[str, Any]:
    """Execute a specialized evidence-grounded document analysis operation."""
    op = operation.lower().strip()
    title = OPERATION_TITLES.get(op, "Document Analysis")

    if not doc_tuples:
        return {
            "operation": op,
            "title": title,
            "result": "No document content available for analysis.",
            "sources": [],
            "mode": "retrieval_only",
        }

    # Handle Multi-Document Comparison
    if op == "compare":
        from candidates import compare_resumes, looks_like_resumes  # local import: avoids a cycle

        if looks_like_resumes(doc_tuples):
            text, srcs = compare_resumes(doc_tuples)
            return {
                "operation": op,
                "title": title,
                "result": text,
                "sources": srcs,
                "mode": "retrieval_only",
            }
        return _run_compare_operation(doc_tuples, custom_query)

    # Standard single or multi-doc targeted retrieval
    query = custom_query or OPERATION_QUERIES.get(op, op)
    sources = _flat(retrieve(query, doc_tuples, top_k=6, min_score=0.03))

    # For summarize and key_points, if lexical match yields 0, fall back to representative page chunks
    if not sources and op in {"summarize", "key_points"}:
        sources = _get_representative_chunks(doc_tuples, limit=5)

    if not sources:
        return {
            "operation": op,
            "title": title,
            "result": f"No specific evidence regarding {title.lower()} was found in the selected document(s).",
            "sources": [],
            "mode": "retrieval_only",
        }

    # Synthesize grounded summary / bullets
    lines = [f"### {title}\n"]

    if op == "summarize":
        lines.append("Based on the core sections of the document:\n")
        for s in sources:
            lines.append(f"• **Page {s['page']} ({s['filename']})**: {s['text']}")
    elif op == "key_points":
        lines.append("Extracted key points and concepts:\n")
        for idx, s in enumerate(sources, 1):
            lines.append(f"{idx}. **[Page {s['page']} · {s['filename']}]** {s['text']}")
    elif op == "deadlines":
        lines.append("Identified dates, periods, and timeline references:\n")
        for s in sources:
            lines.append(f"• **[Page {s['page']}]** {s['text']}")
    elif op == "people":
        lines.append("Identified individuals, roles, and responsibilities:\n")
        for s in sources:
            lines.append(f"• **[Page {s['page']}]** {s['text']}")
    elif op == "costs":
        lines.append("Identified financial terms, fees, and monetary amounts:\n")
        for s in sources:
            lines.append(f"• **[Page {s['page']}]** {s['text']}")
    else:
        for s in sources:
            lines.append(f"• **[Page {s['page']} · {s['filename']}]** {s['text']}")

    return {
        "operation": op,
        "title": title,
        "result": "\n\n".join(lines),
        "sources": sources,
        "mode": "retrieval_only",
    }


def _run_compare_operation(
    doc_tuples: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    query: str | None,
) -> dict[str, Any]:
    """Compare two or more documents by analyzing each document's core content."""
    all_sources: list[dict[str, Any]] = []
    doc_sections = []

    search_query = query or "purpose overview summary main topics details key findings photosynthesis invoice payable amount"

    for meta, chunks in doc_tuples:
        doc_sources = _flat(retrieve(search_query, [(meta, chunks)], top_k=3, min_score=0.03))
        if not doc_sources and chunks:
            doc_sources = _get_representative_chunks([(meta, chunks)], limit=2)
        all_sources.extend(doc_sources)

        passages = [f"  - (Page {s['page']}): {s['text']}" for s in doc_sources]
        passages_text = "\n".join(passages) if passages else "  - No representative passages found."

        doc_sections.append(
            f"#### 📄 Document: {meta['filename']} ({meta['page_count']} pages, {len(chunks)} chunks)\n"
            f"{passages_text}"
        )

    result_text = (
        "### Multi-Document Comparison\n\n"
        + "\n\n".join(doc_sections)
        + "\n\n---\n"
        f"**Comparison Overview:** Analyzed {len(doc_tuples)} documents with {len(all_sources)} total cited evidence passages. "
        "Review the cited sections above to compare terms, context, and structural differences."
    )

    return {
        "operation": "compare",
        "title": "Multi-Document Comparison",
        "result": result_text,
        "sources": all_sources,
        "mode": "retrieval_only",
    }