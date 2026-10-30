"""Resume screening: rank the uploaded resumes against the skills named in a question.

Deterministic on purpose (no LLM): every score can be traced to words found in the resume,
so the ranking cannot be hallucinated. It counts how many of the requested skills each
resume contains, weighting the Skills section highest.
"""
from __future__ import annotations

import re
from typing import Any

from chunking import clip_text
from text_utils import raw_words, stem

# "who is the best for...", "rank the candidates", "shortlist", "filter resumes", ...
RANK_RE = re.compile(
    r"\b(rank|ranking|shortlist|short-list|filter|screen|screening|"
    r"best\s+(?:candidate|resume|fit|person|match)|top\s+\d*\s*(?:candidate|resume|profile)s?|"
    r"most\s+(?:suitable|qualified|skilled|relevant)|"
    r"who\s+(?:is|are|was|were)\s+(?:the\s+)?(?:best|better|good|suitable|fit|right|qualified)|"
    r"(?:suitable|good|best|right|fit)\s+(?:candidates?\s+)?for|"
    r"(?:hire|hiring|recruit|select)\b|which\s+(?:candidate|resume))",
    re.I,
)

# Words that describe the ask, not a skill.
NOISE = frozenset("""
rank ranking ranked shortlist filter screen screening best better good top most suitable qualified
relevant fit right candidate candidates resume resumes cv cvs profile profiles person people
who which whom role roles job jobs position positions opening vacancy hire hiring recruit select
need needs needed want wants require requires required requirement requirements looking look
experience experienced skill skills skilled knowledge knows know proficient proficiency
developer developers engineer engineers among them all of the for with and or in on at to a an
is are was were be me us please give show tell find list based using use having have has had
good great strong
""".split())

# Skill spellings that should count as the same thing.
ALIASES = {
    "js": ["javascript"], "javascript": ["js"],
    "sql": ["mysql", "postgresql", "sqlite", "mssql"],
    "node": ["nodejs", "node.js"], "nodejs": ["node"],
    "react": ["reactjs"], "reactjs": ["react"],
    "ml": ["machine", "learning"],
    "ai": ["artificial"],
    "k8s": ["kubernetes"], "kubernetes": ["k8s"],
    "ux": ["ui", "user"], "ui": ["ux"],
}

_WEIGHT_SKILLS, _WEIGHT_WORK, _WEIGHT_OTHER = 3, 2, 1

# Multi-word skills are matched as one phrase, not as separate words.
PHRASES = [
    "data science", "data analysis", "data analytics", "machine learning", "deep learning",
    "natural language processing", "computer vision", "computer science", "user research",
    "power bi", "adobe xd", "full stack", "front end", "back end", "rest api", "ci cd",
    "node js", "version control", "cloud computing",
]


def extract_requirements(question: str) -> list[str]:
    seen: list[str] = []
    norm = " " + " ".join(raw_words(question)) + " "
    for ph in PHRASES:
        if f" {ph} " in norm:
            seen.append(ph)
            norm = norm.replace(f" {ph} ", " ")
    for w in norm.split():
        if w in NOISE or w.isdigit() or len(w) < 2:
            continue
        s = stem(w)
        if s not in seen:
            seen.append(s)
    return seen


def wants_ranking(question: str) -> bool:
    return bool(RANK_RE.search(question))


def candidate_name(filename: str) -> str:
    stem_ = re.sub(r"\.pdf$", "", filename, flags=re.I)
    stem_ = re.sub(r"[_\-]+", " ", stem_)
    stem_ = re.sub(r"\b(resume|cv|curriculum vitae)\b", "", stem_, flags=re.I)
    return re.sub(r"\s+", " ", stem_).strip() or filename


def _chunk_tokens(text: str) -> tuple[set[str], str]:
    words = raw_words(text)
    return {stem(w) for w in words}, " " + " ".join(words) + " "


def _term_in(term: str, tokens: set[str], norm: str) -> bool:
    if " " in term:  # phrase
        return f" {term} " in norm
    return term in tokens or any(stem(a) in tokens for a in ALIASES.get(term, []))


def _weight(section: str) -> int:
    s = (section or "").lower()
    if "skill" in s:
        return _WEIGHT_SKILLS
    if any(k in s for k in ("experience", "project", "certif", "intern", "work")):
        return _WEIGHT_WORK
    return _WEIGHT_OTHER


def score_resume(terms: list[str], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for c in chunks:
        toks, norm = _chunk_tokens(str(c.get("text", "")))
        w = _weight(str(c.get("section", "")))
        for t in terms:
            if _term_in(t, toks, norm) and (t not in best or w > best[t][0]):
                best[t] = (w, c)
    score = sum(w for w, _ in best.values())
    matched = [t for t in terms if t in best]
    evidence = None
    if best:  # the chunk that backs the most terms
        counts: dict[int, int] = {}
        by_id: dict[int, dict[str, Any]] = {}
        for _, c in best.values():
            counts[id(c)] = counts.get(id(c), 0) + 1
            by_id[id(c)] = c
        evidence = by_id[max(counts, key=counts.get)]
    return {
        "score": score,
        "max": _WEIGHT_SKILLS * len(terms),
        "matched": matched,
        "missing": [t for t in terms if t not in best],
        "evidence": evidence,
    }


def rank_candidates(question: str, docs: list[tuple[dict[str, Any], list[dict[str, Any]]]]):
    """Return (answer_markdown, sources)."""
    terms = extract_requirements(question)
    if not terms:
        return (
            "Tell me what you are hiring for, so I can rank the resumes. For example:\n\n"
            "- Rank the candidates for a React developer role\n"
            "- Who is the best fit for a backend role with PHP and MySQL?\n"
            "- Shortlist candidates who know Python and SQL",
            [],
        )

    rows = []
    for meta, chunks in docs:
        r = score_resume(terms, chunks)
        r["meta"] = meta
        rows.append(r)
    rows.sort(key=lambda r: (-r["score"], -len(r["matched"]), candidate_name(r["meta"]["filename"])))

    lines = [f"### Candidate ranking for: {', '.join(terms)}\n"]
    sources: list[dict[str, Any]] = []
    place = 0
    none_matched: list[str] = []
    for r in rows:
        name = candidate_name(r["meta"]["filename"])
        if r["score"] == 0:
            none_matched.append(name)
            continue
        place += 1
        pct = round(100 * r["score"] / r["max"])
        ev = r["evidence"]
        cite = ""
        if ev is not None:
            page = int(ev.get("page", 1))
            cite = f' [Doc: {r["meta"]["filename"]}, Page: {page}]'
            sources.append({
                "document_id": r["meta"]["id"],
                "filename": r["meta"]["filename"],
                "page": page,
                "chunk_id": ev.get("chunk_id") or f'{r["meta"]["id"]}_p{page}',
                "text": clip_text(str(ev.get("text", "")), 600),
                "score": round(r["score"] / r["max"], 4),
            })
        lines.append(f"{place}. **{name}** — {pct}% match ({len(r['matched'])}/{len(terms)} requirements){cite}")
        lines.append(f"   - Has: {', '.join(r['matched'])}")
        if r["missing"]:
            lines.append(f"   - Missing: {', '.join(r['missing'])}")
    if none_matched:
        lines.append(f"\nNo match: {', '.join(none_matched)}")
    if not place:
        lines.insert(1, "No resume mentions any of these requirements.\n")
    lines.append(
        "\n_How this is scored: each requirement found in a resume earns points (Skills section "
        "highest, then Experience, Projects and Certifications). It counts matches only; it does "
        "not judge quality, seniority or years of experience._"
    )
    return "\n".join(lines), sources


# ---------------------------------------------------------------- resume comparison
COMPARE_RE = re.compile(
    r"\b(compare|comparison|comparing|difference|differences|differ|similar|similarity|similarities|"
    r"common|versus|vs)\b",
    re.I,
)


def wants_comparison(question: str) -> bool:
    return bool(COMPARE_RE.search(question))


def _section_text(chunks: list[dict[str, Any]], name: str) -> tuple[str, dict[str, Any] | None]:
    parts, first = [], None
    for c in chunks:
        if str(c.get("section", "")).strip().lower() == name:
            body = [ln for ln in str(c.get("text", "")).split("\n") if not ln.startswith("Document:")]
            parts.append("\n".join(body).strip())
            first = first or c
    return "\n".join(p for p in parts if p), first


def looks_like_resumes(docs: list[tuple[dict[str, Any], list[dict[str, Any]]]]) -> bool:
    if len(docs) < 2:
        return False
    with_skills = sum(1 for _, ch in docs if _section_text(ch, "skills")[0])
    return with_skills >= max(2, (len(docs) + 1) // 2)


def _bullets(text: str) -> list[str]:
    return [re.sub(r"^[-•*]\s*", "", ln).strip() for ln in text.split("\n") if ln.strip().startswith(("-", "•", "*"))]


def compare_resumes(docs: list[tuple[dict[str, Any], list[dict[str, Any]]]]):
    """Side-by-side summary of every resume plus the skills they share. Returns (markdown, sources)."""
    lines = ["### Resume comparison\n"]
    sources: list[dict[str, Any]] = []
    skill_owners: dict[str, list[str]] = {}
    display: dict[str, str] = {}

    for meta, chunks in docs:
        name = candidate_name(meta["filename"])
        first_name = name.split()[0]
        skills_txt, skills_chunk = _section_text(chunks, "skills")
        edu_txt, _ = _section_text(chunks, "education")
        exp_txt, _ = _section_text(chunks, "experience")
        cert_txt, _ = _section_text(chunks, "certifications")

        page = int((skills_chunk or (chunks[0] if chunks else {})).get("page", 1))
        cite = f' [Doc: {meta["filename"]}, Page: {page}]'
        lines.append(f"**{name}**{cite}")

        edu = " · ".join(ln.strip() for ln in edu_txt.split("\n")[:3] if ln.strip())
        if edu:
            lines.append(f"- Education: {edu}")
        roles = [ln.strip() for ln in exp_txt.split("\n")
                 if ln.strip() and not ln.strip().startswith(("-", "•", "*")) and re.search(r"\s-\s", ln)]
        if roles:
            lines.append(f"- Experience: {'; '.join(roles)}")
        if skills_txt:
            lines.append(f"- Skills: {' '.join(skills_txt.split())}")
        certs = _bullets(cert_txt)
        if certs:
            lines.append(f"- Certifications: {'; '.join(certs)}")
        lines.append("")

        for sk in re.split(r"[,;]", skills_txt.replace("\n", " ")):
            sk = sk.strip()
            if sk:
                key = sk.lower()
                display.setdefault(key, sk)
                if first_name not in skill_owners.setdefault(key, []):
                    skill_owners[key].append(first_name)
        if skills_chunk is not None:
            sources.append({
                "document_id": meta["id"], "filename": meta["filename"], "page": page,
                "chunk_id": skills_chunk.get("chunk_id") or f'{meta["id"]}_p{page}',
                "text": clip_text(skills_txt, 400), "score": 1.0,
            })

    shared = sorted(((k, v) for k, v in skill_owners.items() if len(v) >= 2), key=lambda kv: (-len(kv[1]), kv[0]))
    lines.append("**Skills shared by two or more candidates**")
    if shared:
        lines += [f"- {display[k]}: {', '.join(v)}" for k, v in shared]
    else:
        lines.append("- None: the candidates have no skill in common.")
    lines.append("\n_Built directly from each resume's sections, with no AI model involved._")
    return "\n".join(lines), sources