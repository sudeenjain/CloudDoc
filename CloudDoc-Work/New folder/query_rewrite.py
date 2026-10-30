"""Query rewriting: strip pronouns and filler, then expand synonyms.

A resume says "University / B.Tech / CGPA" while people ask about a "college".
The curated concept map below bridges that vocabulary gap deterministically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from text_utils import content_words, stem, tokenize

# concept -> (words in the question that trigger it, terms added to the search)
CONCEPTS: dict[str, tuple[list[str], list[str]]] = {
    "education": (
        [
            "education", "educational", "college", "university", "institute", "institution",
            "school", "degree", "study", "studying", "studied", "studies", "student",
            "graduate", "graduated", "graduation", "bachelor", "master", "btech", "mtech",
            "cgpa", "gpa", "qualification", "qualifications", "academic", "academics",
            "alma", "mater", "diploma", "major", "branch", "stream", "enrolled", "pursuing",
            "attend", "attended", "attending", "campus",
        ],
        [
            "education", "university", "college", "institute", "school", "degree", "bachelor",
            "btech", "mtech", "cgpa", "gpa", "graduation", "academic", "qualification",
            "diploma", "pursuing",
        ],
    ),
    "skills": (
        [
            "skill", "skills", "skilled", "technology", "technologies", "tool", "tools", "stack",
            "proficient", "proficiency", "expertise", "know", "knows", "familiar", "language",
            "languages", "programming", "framework", "frameworks", "tech", "competency",
            "competencies",
        ],
        ["skill", "technical", "programming", "language", "tool", "framework", "proficient",
         "expertise"],
    ),
    "experience": (
        [
            "experience", "experienced", "work", "worked", "working", "job", "jobs", "employer",
            "employed", "employment", "company", "companies", "organization", "organisation",
            "role", "position", "career", "profession", "professional", "designation",
            "responsibility", "responsibilities",
        ],
        ["experience", "work", "employment", "company", "role", "position", "responsibility",
         "internship", "intern", "organization"],
    ),
    "internship": (
        ["intern", "interned", "internship", "internships", "trainee", "apprentice",
         "apprenticeship", "training", "trained"],
        ["internship", "intern", "trainee", "experience", "company", "role", "work"],
    ),
    "projects": (
        ["project", "projects", "built", "build", "developed", "develop", "created", "application",
         "app", "implemented", "designed"],
        ["project", "developed", "built", "application", "implemented"],
    ),
    "contact": (
        [
            "contact", "email", "mail", "phone", "mobile", "number", "call", "reach", "address",
            "linkedin", "github", "location", "city", "live", "lives", "residing", "whatsapp",
        ],
        ["contact", "email", "emailaddr", "phone", "phonenum", "mobile", "linkedin", "github",
         "address", "location"],
    ),
    "certifications": (
        ["certification", "certifications", "certificate", "certificates", "certified", "certify",
         "course", "courses", "credential", "credentials", "license", "licensed", "coursera",
         "udemy", "nptel"],
        ["certification", "certificate", "certified", "course", "credential"],
    ),
    "achievements": (
        ["achievement", "achievements", "award", "awards", "won", "win", "winner", "rank", "ranked",
         "honor", "honour", "prize", "accomplishment", "hackathon", "competition",
         "extracurricular", "activity", "activities"],
        ["achievement", "award", "won", "rank", "honor", "prize", "accomplishment", "hackathon",
         "competition", "extracurricular"],
    ),
    "summary": (
        ["summary", "objective", "profile", "about", "overview", "bio", "introduce",
         "introduction", "describe"],
        ["summary", "objective", "profile", "about", "overview", "career"],
    ),
    "identity": (
        ["name", "called"],
        ["name", "contact", "profile", "summary", "header"],
    ),
}

# stemmed trigger -> concept names
_TRIGGERS: dict[str, list[str]] = {}
for _concept, (_triggers, _expansions) in CONCEPTS.items():
    for _t in _triggers:
        _TRIGGERS.setdefault(stem(_t), []).append(_concept)
    CONCEPTS[_concept] = (_triggers, [stem(e) if e not in {"emailaddr", "phonenum"} else e for e in _expansions])


@dataclass
class QueryPlan:
    original: str
    content_words: list[str]
    tokens: list[str]
    intents: list[str]
    expansion_terms: list[str]
    llm_variants: list[str] = field(default_factory=list)
    bm25_tokens: list[str] = field(default_factory=list)

    def describe(self) -> dict:
        return {
            "original": self.original,
            "terms_after_preprocessing": self.content_words,
            "stemmed_tokens": self.tokens,
            "intents": self.intents,
            "expansion_terms": self.expansion_terms,
            "llm_variants": self.llm_variants,
            "bm25_query": self.bm25_tokens,
        }


def rewrite_query(question: str, llm_variants: list[str] | None = None) -> QueryPlan:
    """Build the lexical query for a question."""
    tokens = tokenize(question)
    words = content_words(question)

    intents: list[str] = []
    for tok in tokens:
        for concept in _TRIGGERS.get(tok, []):
            if concept not in intents:
                intents.append(concept)

    token_set = set(tokens)
    expansion: list[str] = []
    for concept in intents:
        for term in CONCEPTS[concept][1]:
            if term not in token_set and term not in expansion:
                expansion.append(term)

    variant_tokens: list[str] = []
    variants = [v for v in (llm_variants or []) if v and v.strip()][:3]
    for variant in variants:
        for tok in tokenize(variant):
            if tok not in token_set and tok not in expansion and tok not in variant_tokens:
                variant_tokens.append(tok)

    # Words the user actually typed count double; expansions count once.
    bm25_tokens = tokens + tokens + expansion + variant_tokens
    return QueryPlan(
        original=question,
        content_words=words,
        tokens=tokens,
        intents=intents,
        expansion_terms=expansion + variant_tokens,
        llm_variants=variants,
        bm25_tokens=bm25_tokens,
    )
