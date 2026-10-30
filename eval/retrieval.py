"""Compare search_policies variants on eval/retrieval_queries.toml.

Run: uv run python eval/retrieval.py
"""

import tomllib
from collections import Counter
from pathlib import Path

from citywheels.tools.policies import bm25, load_sections, term_counts, tokenize

EVAL_DIR = Path(__file__).parent
TOP_K = 3


def overlap(query_terms: set[str], docs: list[Counter]) -> list[float]:
    # Baseline: how often the query words appear in the section, no weighting of rare words.
    return [sum(doc[t] for t in query_terms) for doc in docs]


def rank(query: str, scorer, heading_weight: float, use_stem: bool) -> list[str]:
    sections = load_sections()
    docs = [term_counts(s, heading_weight, use_stem) for s in sections]
    scores = scorer(set(tokenize(query, use_stem)), docs)
    ranked = sorted(zip(scores, sections, strict=True), key=lambda pair: pair[0], reverse=True)
    return [s.heading for score, s in ranked if score > 0][:TOP_K]


def evaluate(queries: list[dict], scorer, heading_weight: float, use_stem: bool) -> dict:
    on_topic = [q for q in queries if q["expected"]]
    off_topic = [q for q in queries if not q["expected"]]
    hit1 = hit3 = hit3_mismatch = 0
    misses = []
    for q in on_topic:
        found = rank(q["text"], scorer, heading_weight, use_stem)
        if found and found[0] in q["expected"]:
            hit1 += 1
        if set(found) & set(q["expected"]):
            hit3 += 1
            hit3_mismatch += q.get("mismatch", False)
        else:
            misses.append(f"{q['text']} -> {found or 'no match'}")
    no_match = 0
    for q in off_topic:
        found = rank(q["text"], scorer, heading_weight, use_stem)
        if found:
            misses.append(f"(off-topic) {q['text']} -> {found}")
        else:
            no_match += 1
    mismatch_total = sum(q.get("mismatch", False) for q in on_topic)
    return {
        "hit@1": f"{hit1}/{len(on_topic)}",
        "hit@3": f"{hit3}/{len(on_topic)}",
        "hit@3 mismatch": f"{hit3_mismatch}/{mismatch_total}",
        "off-topic no match": f"{no_match}/{len(off_topic)}",
        "misses": misses,
    }


def main():
    queries = tomllib.loads((EVAL_DIR / "retrieval_queries.toml").read_text())["query"]
    variants = [
        ("overlap", overlap, 2.0, True),
        ("bm25, no stemming", bm25, 2.0, False),
        ("bm25, heading x1", bm25, 1.0, True),
        ("bm25, heading x1.5", bm25, 1.5, True),
        ("bm25, heading x2", bm25, 2.0, True),
        ("bm25, heading x3", bm25, 3.0, True),
    ]
    columns = ["hit@1", "hit@3", "hit@3 mismatch", "off-topic no match"]
    lines = [
        "# search_policies variants",
        "",
        f"{len(queries)} queries from `retrieval_queries.toml`, top {TOP_K} results.",
        "",
        "| variant | " + " | ".join(columns) + " |",
        "| --- " * (len(columns) + 1) + "|",
    ]
    results = {}
    for name, scorer, weight, use_stem in variants:
        results[name] = evaluate(queries, scorer, weight, use_stem)
        lines.append(f"| {name} | " + " | ".join(results[name][c] for c in columns) + " |")

    lines += ["", "## Misses, bm25 heading x2 (current default)", ""]
    lines += [f"- {m}" for m in results["bm25, heading x2"]["misses"]]

    report = "\n".join(lines) + "\n"
    (EVAL_DIR / "retrieval_results.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
