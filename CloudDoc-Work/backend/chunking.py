"""Section-aware chunking.

Resumes (and most structured documents) are split on headings such as
EDUCATION / EXPERIENCE / SKILLS. Every chunk is prefixed with its file name and
section title so that "Education" context is part of the indexed text. Documents
without recognisable headings fall back to overlapping word windows.
"""
from __future__ import annotations

import re

from config import (
    CHUNK_OVERLAP,
    CHUNK_WORDS,
    SECTION_MAX_WORDS,
    SNIPPET_CHARS,
)
from text_utils import EMAIL_RE, PHONE_RE, URL_RE

# --------------------------------------------------------------------------- headings
# (section_type, regex matched against the lower-cased heading text)
_SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("education", re.compile(r"\b(educat\w*|academics?|qualifications?|schooling)\b")),
    ("experience", re.compile(
        r"\b(experience|employment|work history|internships?|career history|professional background)\b")),
    ("skills", re.compile(
        r"\b(skills?|technologies|tech stack|competenc\w+|expertise|tools|programming languages)\b")),
    ("projects", re.compile(r"\bprojects?\b")),
    ("certifications", re.compile(
        r"\b(certifications?|certificates?|licen[cs]es?|courses?|training)\b")),
    ("achievements", re.compile(
        r"\b(achievements?|awards?|honou?rs?|accomplishments?|extra[\s-]?curricular\w*|activities|"
        r"positions? of responsibility|responsibilit\w+)\b")),
    ("contact", re.compile(
        r"\b(contacts?|contact (info\w*|details)|personal (details|information|info)|reach me|links)\b")),
    ("summary", re.compile(
        r"\b(summary|objective|profile|about( me)?|career objective)\b")),
    ("other", re.compile(
        r"\b(languages?|interests?|hobbies|references?|declaration|publications?|volunteer\w*|coursework)\b")),
]

# Words that may appear in a plain (not UPPERCASE) heading such as "Technical Skills".
_HEADING_VOCAB = frozenset(
    """
    and of my key core technical professional work relevant academic personal educational career
    additional other details information qualification qualifications background summary history
    profile experience skills skill projects project certifications certification certificates
    achievements awards education internships internship contact objective about me languages
    interests hobbies references declaration publications volunteer training courses course
    activities extracurricular responsibility responsibilities links coursework employment
    programming tools technologies
    """.split()
)
_ROLE_WORDS = frozenset(
    "manager engineer developer lead analyst consultant designer architect specialist executive "
    "associate officer director intern trainee".split()
)


_NUMBERED_RE = re.compile(r"^(?:\d+(?:\.\d+)+\.?|\d+[.)])\s+(?P<rest>\S.*)$")
_SMALL_WORDS = frozenset("a an the of in on at by for to and or vs with from into as".split())


def _capitalised_ratio(words: list[str]) -> float:
    """Share of the meaningful words that start with a capital letter (title-case test)."""
    core = [w.strip("()[]\"'.,:;!?") for w in words]
    core = [w for w in core if w and w[0].isalpha() and w.lower() not in _SMALL_WORDS]
    if not core:
        return 0.0
    return sum(1 for w in core if w[0].isupper()) / len(core)


def _numbered_heading(raw: str) -> tuple[str, str] | None:
    """Headings such as '2. Major Challenges in NLP Systems' or '3.1 Parsing Methods'."""
    match = _NUMBERED_RE.match(raw.strip())
    if not match:
        return None
    rest = match.group("rest").strip()
    if rest.endswith(":"):
        rest = rest[:-1].rstrip()
    words = rest.split()
    if (
        not words
        or len(words) > 12
        or len(rest) > 80
        or re.search(r"\d|:", rest)  # list items like "1. Idea: explanation" are not headings
        or rest.endswith((".", ",", ";"))
    ):
        return None
    if _capitalised_ratio(words) < 0.6:
        return None
    low = " ".join(words).lower()
    stype = next((t for t, pat in _SECTION_PATTERNS if pat.search(low)), None)
    if stype is None and len(words) < 2:
        return None
    return rest, stype or "section"


def detect_heading(line: str) -> tuple[str, str] | None:
    """Return (title, section_type) when the line looks like a section heading."""
    numbered = _numbered_heading(line)
    if numbered:
        return numbered

    raw = line.strip()
    if not raw or len(raw) > 60:
        return None
    cleaned = re.sub(r"^[\W_]+|[\W_]+$", "", raw)
    if not cleaned or re.search(r"\d", cleaned) or cleaned.endswith("."):
        return None
    # Letter-spaced headings such as "E D U C A T I O N" (common in design-tool exports).
    if re.fullmatch(r"(?:\S\s+)+\S", cleaned) and len(cleaned.replace(" ", "")) >= 4:
        cleaned = " ".join(g.replace(" ", "") for g in re.split(r"\s{2,}", cleaned))
    words = cleaned.replace("&", " and ").split()
    if len(words) > 5:
        return None

    # A wrapped fragment of a sentence ("languages, focusing on:") is not a heading.
    if "," in cleaned or (cleaned[0].islower() and len(words) > 1):
        return None

    low = " ".join(words).lower()
    stype = next((t for t, pat in _SECTION_PATTERNS if pat.search(low)), None)
    if stype is None:
        return None

    has_colon = raw.endswith(":")
    shouty = cleaned.isupper()
    plain = all(w.lower() in _HEADING_VOCAB for w in words)
    if not (shouty or has_colon or plain):
        return None
    # "PROJECT MANAGER" is a job title, not a "Projects" heading (unless it ends with a colon).
    if not has_colon and any(w.lower() in _ROLE_WORDS for w in words):
        return None

    title = cleaned.title() if (shouty or cleaned.islower()) else cleaned
    return title, stype


def detect_page_title(lines: list[str]) -> str | None:
    """Title of a slide-like page: a short, title-case first line followed by more content."""
    if len(lines) < 2:
        return None
    first = lines[0].strip()
    cleaned = re.sub(r"^[\W_]+|[\W_]+$", "", first)
    words = cleaned.split()
    if (
        not words
        or len(words) > 8
        or len(first) > 70
        or first.endswith((".", ",", ";"))
        or EMAIL_RE.search(first)
        or PHONE_RE.search(first)
    ):
        return None
    if cleaned.isupper() and len(cleaned) >= 3:
        return cleaned.title()
    return cleaned if _capitalised_ratio(words) >= 0.6 and len(words) >= 2 else None


# --------------------------------------------------------------------------- windows
def _wc(text: str) -> int:
    return len(text.split())


def _explode_long_lines(lines: list[str], limit: int, overlap: int = 0) -> list[str]:
    """Split lines longer than `limit` words into overlapping pieces."""
    out: list[str] = []
    step = max(1, limit - overlap)
    for line in lines:
        words = line.split()
        if len(words) <= limit:
            out.append(line)
            continue
        for i in range(0, len(words), step):
            out.append(" ".join(words[i : i + limit]))
            if i + limit >= len(words):
                break
    return out


def _window_spans(lines: list[str], max_words: int, overlap_words: int) -> tuple[list[str], list[tuple[int, int]]]:
    """Group lines into windows of about max_words words with line-level overlap.

    Returns the (possibly re-split) line list and the (start, end) span of every window in it.
    """
    lines = _explode_long_lines(lines, max_words, overlap_words)
    spans: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        count, end = 0, start
        while end < len(lines) and (end == start or count + _wc(lines[end]) <= max_words):
            count += _wc(lines[end])
            end += 1
        spans.append((start, end))
        if end >= len(lines):
            break
        back, carried = end, 0
        while back > start + 1 and carried + _wc(lines[back - 1]) <= overlap_words:
            back -= 1
            carried += _wc(lines[back])
        start = back
    return lines, spans


CONTINUATION_MIN_WORDS = 25
CONTINUATION_MAX_WORDS = 60
_SENTENCE_END = (".", "!", "?")


def _continuation(following: list[str]) -> str:
    """Words that finish the sentence a chunk was cut in the middle of."""
    words: list[str] = []
    for line in following:
        for word in line.split():
            words.append(word)
            if len(words) >= CONTINUATION_MIN_WORDS and word.endswith(_SENTENCE_END):
                return " ".join(words)
            if len(words) >= CONTINUATION_MAX_WORDS:
                return " ".join(words) + "…"
    return " ".join(words)


def split_into_chunks(
    text: str,
    chunk_words: int = CHUNK_WORDS,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """Split text into overlapping word chunks (kept for backwards compatibility)."""
    cleaned = text.strip()
    if not cleaned:
        return []
    words = cleaned.split()
    if len(words) <= chunk_words:
        return [" ".join(words)]

    step = max(1, chunk_words - overlap)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start : start + chunk_words])
        if chunk:
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


# --------------------------------------------------------------------------- snippets
def make_snippet(text: str, max_chars: int = SNIPPET_CHARS) -> str:
    """Collapse whitespace and limit length at a word boundary."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(" ", 1)[0]
    return (truncated or text[:max_chars]) + "…"


def clip_text(text: str, max_chars: int = SNIPPET_CHARS) -> str:
    """Like make_snippet but keeps line breaks (useful structure for the LLM)."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rsplit(None, 1)[0]
    return (truncated or text[:max_chars]) + "…"


# --------------------------------------------------------------------------- chunk building
def _looks_like_contact(text: str) -> bool:
    return bool(EMAIL_RE.search(text) or PHONE_RE.search(text) or URL_RE.search(text))


def chunk_prefix(filename: str, section: str) -> str:
    return f"Document: {filename or 'document'} | Section: {section}"


SLIDE_MAX_WORDS = 120  # pages with fewer words and no heading are treated as slides


def build_page_chunks(
    pages: list[str],
    doc_id: str,
    filename: str = "",
    chunk_words: int = CHUNK_WORDS,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict]:
    """Create structured chunks from extracted pages.

    Each chunk dict has: page, chunk_id, section, section_type, body (raw text), continuation
    (words that finish a sentence cut at the chunk edge, possibly from the next page),
    text (prefixed with file name + section title; this is what gets indexed and shown)
    and word_count.
    """
    section_max = max(SECTION_MAX_WORDS, chunk_words)

    # Pass 1: segments, one run of lines under one heading on one page.
    segments: list[dict] = []
    current: tuple[str, str] | None = None
    any_heading = False

    for page_num, page_text in enumerate(pages, start=1):
        raw_lines = [ln for ln in (page_text or "").replace("\r", "").split("\n")]
        headings = [detect_heading(ln) for ln in raw_lines]
        non_empty = [ln.strip() for ln in raw_lines if ln.strip()]
        page_words = sum(_wc(ln) for ln in non_empty)

        slide_title: str | None = None
        if not any(headings) and page_words < SLIDE_MAX_WORDS:
            # A short page without headings is a slide: it does not continue the previous section.
            current = None
            slide_title = detect_page_title(non_empty)
            if slide_title:
                current = (slide_title, "slide")

        buffer: list[str] = []
        first_on_page = True

        def flush() -> None:
            nonlocal first_on_page
            lines = [b for b in buffer if b.strip()]
            if lines:
                title, stype = current if current else (None, None)
                segments.append({
                    "title": title, "type": stype, "page": page_num,
                    "lines": lines, "starts_page": first_on_page,
                })
                first_on_page = False
            buffer.clear()

        title_pending = slide_title is not None
        for raw_line, heading in zip(raw_lines, headings):
            if heading:
                flush()
                current = heading
                any_heading = True
                continue
            line = raw_line.strip()
            if not line:
                continue
            if title_pending:
                title_pending = False
                if len(non_empty) > 1:
                    continue  # the title lives in the section name, not in the body
            buffer.append(line)
        flush()

    # Pass 2: window each segment, add continuation text, prefix.
    chunks: list[dict] = []
    per_page_counter: dict[int, int] = {}

    for i, seg in enumerate(segments):
        title, stype, page_num, lines = seg["title"], seg["type"], seg["page"], seg["lines"]
        nxt = segments[i + 1] if i + 1 < len(segments) else None
        continues = bool(
            nxt and nxt["starts_page"] and nxt["page"] == page_num + 1
            and nxt["title"] == title and nxt["type"] == stype
        )

        if title is None:
            joined = " ".join(lines)
            if any_heading:
                title, stype = ("Contact", "contact") if _looks_like_contact(joined) else ("Header", "header")
            else:
                title, stype = "Document", "body"

        if sum(_wc(line) for line in lines) <= section_max:
            work, spans = lines, [(0, len(lines))]
        else:
            work, spans = _window_spans(lines, chunk_words, overlap)

        for start_idx, end_idx in spans:
            window = work[start_idx:end_idx]
            body = "\n".join(window).strip()
            if not body:
                continue

            continuation = ""
            if not body.endswith(_SENTENCE_END + (":", ";")):
                following = list(work[end_idx:])
                if end_idx >= len(work) and continues:
                    following += nxt["lines"]
                continuation = _continuation(following)

            idx = per_page_counter.get(page_num, 0) + 1
            per_page_counter[page_num] = idx
            text = f"{chunk_prefix(filename, title)}\n{body}"
            if continuation:
                text += f" {continuation}"
            chunks.append({
                "page": page_num,
                "chunk_id": f"{doc_id}_p{page_num}_c{idx}",
                "section": title,
                "section_type": stype,
                "body": body,
                "continuation": continuation,
                "text": text,
                "word_count": _wc(body),
            })

    return chunks
