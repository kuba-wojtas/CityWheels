import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import cache

from pydantic import BaseModel, Field

from citywheels.data import POLICIES_DIR


class SearchPoliciesArgs(BaseModel):
    query: str = Field(description="What to look for, in English")


STOPWORDS = frozenset(
    "a an the is are am be do does did i you we me my your our it its to of in on at for "
    "and or if can could will would what when where which who how much this that there "
    "with from get".split()
)

HEADING_WEIGHT = 2.0


@dataclass(frozen=True)
class Section:
    source: str
    heading: str
    text: str


@cache
def load_sections() -> tuple[Section, ...]:
    sections = []
    for path in sorted(POLICIES_DIR.glob("*.md")):
        heading, lines = None, []
        for line in [*path.read_text(encoding="utf-8").splitlines(), "# end"]:
            if line.startswith("#"):
                text = "\n".join(lines).strip()
                if heading and text:
                    sections.append(Section(path.name, heading, text))
                heading, lines = line.lstrip("#").strip(), []
            else:
                lines.append(line)
    return tuple(sections)


def stem(word: str) -> str:
    # Crude suffix stripping, just enough to match cancel/cancelled/cancelling, year/years,
    # change/changed. A real stemmer (NLTK) would be overkill for three documents.
    for suffix in ("ing", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)]
            break
    if word.endswith("e") and len(word) > 3:
        word = word[:-1]
    if len(word) > 3 and word[-1] == word[-2]:
        word = word[:-1]
    return word


def tokenize(text: str, use_stem: bool = True) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]
    return [stem(w) for w in words] if use_stem else words


def term_counts(section: Section, heading_weight: float, use_stem: bool = True) -> Counter:
    counts = Counter(tokenize(section.text, use_stem))
    for term in tokenize(section.heading, use_stem):
        counts[term] += heading_weight
    return counts


def bm25(
    query_terms: set[str], docs: list[Counter], k1: float = 1.5, b: float = 0.75
) -> list[float]:
    n = len(docs)
    lengths = [sum(doc.values()) for doc in docs]
    avg_length = sum(lengths) / n
    doc_freq = Counter(term for doc in docs for term in doc)
    scores = []
    for doc, length in zip(docs, lengths, strict=True):
        score = 0.0
        for term in query_terms & doc.keys():
            idf = math.log(1 + (n - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            tf = doc[term]
            score += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_length))
        scores.append(score)
    return scores


def search_policies(query: str, top_k: int = 3) -> dict:
    sections = load_sections()
    docs = [term_counts(s, HEADING_WEIGHT) for s in sections]
    scores = bm25(set(tokenize(query)), docs)
    ranked = sorted(zip(scores, sections, strict=True), key=lambda pair: pair[0], reverse=True)
    hits = [section for score, section in ranked if score > 0][:top_k]
    if not hits:
        return {"status": "no_match", "query": query}
    return {
        "status": "ok",
        "results": [{"source": s.source, "section": s.heading, "text": s.text} for s in hits],
    }
