"""Shared tokenisation used for indexing and for queries (they must match)."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    """
    a an the and or but if so than then of to in on at by for with from into onto over under about as
    is are was were be been being am do does did done doing have has had having
    i me my mine we us our you your yours he him his she her hers it its they them their theirs
    this that these those there here
    what which who whom whose where when why how
    can could would should will shall may might must
    please tell give show list find get let say said
    also very just not no yes any some all each every
    """.split()
)

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{3,5}\)?[\s-]?)?\d{3,5}[\s-]?\d{4,5}(?!\d)")
URL_RE = re.compile(r"(?:linkedin\.com|github\.com|https?://)", re.I)

# Degree abbreviations: "B.Tech" -> "btech bachelor", "B.E." -> "bachelor engineering".
_DEGREE_SUBS = [
    (re.compile(r"\bb\s?\.\s?tech\b\.?", re.I), " btech bachelor "),
    (re.compile(r"\bm\s?\.\s?tech\b\.?", re.I), " mtech master "),
    (re.compile(r"\bb\s?\.\s?e\b\.?(?=\s|,|$)", re.I), " bachelor engineering "),
    (re.compile(r"\bm\s?\.\s?e\b\.?(?=\s|,|$)", re.I), " master engineering "),
    (re.compile(r"\bb\s?\.\s?sc\b\.?", re.I), " bsc bachelor "),
    (re.compile(r"\bm\s?\.\s?sc\b\.?", re.I), " msc master "),
    (re.compile(r"\bb\s?\.\s?c\s?\.\s?a\b\.?", re.I), " bca bachelor "),
    (re.compile(r"\bm\s?\.\s?c\s?\.\s?a\b\.?", re.I), " mca master "),
    (re.compile(r"\be[\s-]mail\b", re.I), " email "),
]


def stem(token: str) -> str:
    """Very light plural stemmer, applied identically to documents and queries."""
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def normalize_text(text: str) -> str:
    for pattern, repl in _DEGREE_SUBS:
        text = pattern.sub(repl, text)
    return text


def raw_words(text: str) -> list[str]:
    """Lower-cased words (normalised, not stemmed, stopwords kept)."""
    return re.findall(r"[^\W_]+", normalize_text(text).lower())


def tokenize(text: str) -> list[str]:
    """Normalise, drop stopwords, stem. Adds marker tokens for emails/phones/links."""
    if not text:
        return []
    tokens = [
        stem(w)
        for w in raw_words(text)
        if w not in STOPWORDS
    ]
    if EMAIL_RE.search(text):
        tokens.append("emailaddr")
    if PHONE_RE.search(text):
        tokens.append("phonenum")
    if URL_RE.search(text):
        tokens.append("weblink")
    return tokens


def content_words(text: str) -> list[str]:
    """Question words left after stripping pronouns and filler (unstemmed, for display)."""
    return [w for w in raw_words(text) if w not in STOPWORDS]
