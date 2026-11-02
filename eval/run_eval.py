"""Run the agent on eval/cases.toml.

Run:    uv run python eval/run_eval.py [--provider gemini] [--model ...] [--runs 3]
        Saves eval/runs/<time>-<provider>-<cases file>.json and a report next to it (.md).
Report: uv run python eval/run_eval.py --report eval/runs/<file>.json [more files...] [--recheck]
        Writes the combined eval/results.md.
"""

import argparse
import json
import re
import statistics
import subprocess
import time
import tomllib
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from openai import APIError, RateLimitError

from citywheels.agent import (
    STAFF_EMAIL,
    STAFF_PHONE,
    AgentResult,
    ToolCall,
    new_conversation,
    run_agent,
    run_tool,
)
from citywheels.llm import make_client, resolve_provider

EVAL_DIR = Path(__file__).parent

# Seconds to wait per model request, to stay under each free tier's limits.
# Gemini Flash-Lite: 15 requests/min. Groq: 8000 tokens/min, one request is ~1200 tokens.
PACE = {"gemini": 4.5, "groq": 10.0, "ollama": 0.0}

AMOUNT = re.compile(
    r"(?:€|\beur\b)\s*(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s*(?:€|\beur\b|\beuros?\b)",
    re.IGNORECASE,
)
REFUSAL = (
    "can't help", "cannot help", "can't assist", "cannot assist", "unable to help",
    "not able to help", "can only help", "only help with", "can't answer", "cannot answer",
    "not related to citywheels", "nie mogę",
)  # fmt: skip
CLAIMED_ACTION = re.compile(
    r"\b(?:has|have) been (?:cancell?ed|changed)\b|\bi(?:'ve| have) (?:cancell?ed|changed)\b"
    r"|\bis now cancell?ed\b"
)

# Some models write typographic apostrophes and hyphens ("couldn’t", "CW‑1002").
TYPOGRAPHY = str.maketrans(
    {"\u2019": "'", "\u2018": "'", "\u2010": "-", "\u2011": "-", "\u2013": "-"}
)


def to_number(text: str) -> float:
    return round(float(text.replace(",", ".")), 2)


def amounts_in(text: str) -> set[float]:
    return {to_number(a or b) for a, b in AMOUNT.findall(text)}


def allowed_amounts(value, key: str = "") -> set[float]:
    """EUR amounts a tool returned: `*_eur` fields, and amounts written in policy text."""
    if isinstance(value, dict):
        return set().union(*(allowed_amounts(v, k) for k, v in value.items()))
    if isinstance(value, list):
        return set().union(*(allowed_amounts(v, key) for v in value))
    if isinstance(value, str):
        return amounts_in(value)
    if isinstance(value, int | float) and not isinstance(value, bool) and key.endswith("_eur"):
        return {round(float(value), 2)}
    return set()


def unsupported_amounts(answer: str, calls: list[ToolCall]) -> list[str]:
    allowed = allowed_amounts([c.result for c in calls])
    return sorted(f"{a:g}" for a in amounts_in(answer) - allowed)


def contains(text: str, phrase: str) -> bool:
    # Whole words only: "ID" must not match "valid", "50" must not match "150".
    return re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", text) is not None


def check(case: dict, answer: str, calls: list[ToolCall]) -> list[str]:
    failures = []
    text = answer.translate(TYPOGRAPHY).lower()
    called = {c.name for c in calls}

    for tool in case.get("tools", []):
        if tool not in called:
            failures.append(f"{tool} not called")
    if "tools_any" in case and not called & set(case["tools_any"]):
        failures.append(f"none of {case['tools_any']} called")
    for tool, status in case.get("statuses", {}).items():
        if status not in [c.result.get("status") for c in calls if c.name == tool]:
            failures.append(f"{tool} didn't return {status}")
    for value in case.get("amounts", []):
        if round(value, 2) not in amounts_in(answer):
            failures.append(f"missing amount {value:g}")
    for item in case.get("must_contain", []):
        options = item if isinstance(item, list) else [item]
        if not any(contains(text, option) for option in options):
            failures.append(f"missing {' / '.join(options)}")
    for item in case.get("must_not_contain", []):
        if contains(text, item):
            failures.append(f"contains {item}")
    if case.get("refuse"):
        if not (contains(text, STAFF_EMAIL) or contains(text, STAFF_PHONE)):
            failures.append("no staff contact")
        if not any(phrase in text for phrase in REFUSAL):
            failures.append("didn't refuse")
    if case.get("clarify"):
        if "?" not in answer:
            failures.append("didn't ask a question")
        if "quote_price" in called:
            failures.append("quoted a price without asking")
    if case.get("no_action_claim") and CLAIMED_ACTION.search(text):
        failures.append("claims it cancelled or changed the booking")
    if case.get("language") == "pl" and not re.search("[ąćęłńóśźż]", text):
        failures.append("not in Polish")
    if unsupported := unsupported_amounts(answer, calls):
        failures.append(f"unsupported amounts {', '.join(unsupported)}")
    return failures


def run_turn(client, model: str, messages: list[dict], question: str) -> tuple[AgentResult, int]:
    """One agent turn, retried once after a rate limit. Returns the seconds spent waiting."""
    turn_start = len(messages)
    try:
        return run_agent(client, model, messages, question), 0
    except RateLimitError:
        del messages[turn_start:]
        print("  rate limited, waiting 60 s", flush=True)
        time.sleep(60)
        return run_agent(client, model, messages, question), 60


def run_case(client, model: str, case: dict, pace: float) -> dict:
    messages = new_conversation()
    calls: list[ToolCall] = []
    record = {"id": case["id"], "steps": 0, "input_tokens": 0, "output_tokens": 0}
    started = time.monotonic()
    waited = 0.0
    for question in case.get("turns", [case.get("question")]):
        try:
            result, rate_limit_wait = run_turn(client, model, messages, question)
        except APIError as e:
            # A failed request counts as a failed case instead of stopping the whole run.
            failure = f"request failed: {type(e).__name__}"
            record |= {"answer": "", "tool_calls": [], "failures": [failure]}
            return record
        calls += result.tool_calls
        record["steps"] += result.steps
        record["input_tokens"] += result.input_tokens
        record["output_tokens"] += result.output_tokens
        time.sleep(pace * result.steps)
        waited += rate_limit_wait + pace * result.steps

    record["seconds"] = round(time.monotonic() - started - waited, 1)
    record["answer"] = result.answer
    record["gave_up"] = result.gave_up
    record["tool_calls"] = [asdict(c) for c in calls]
    record["failures"] = check(case, result.answer, calls)
    return record


def recheck(run: dict, cases: list[dict]) -> None:
    """Score saved answers again with the current checks, without asking the model again.

    Older runs didn't save tool results. The tools are deterministic (fixed date, fixed
    data), so running them again with the saved arguments gives the same results.
    """
    by_id = {c["id"]: c for c in cases}
    for record in run["results"]:
        if not record["answer"]:
            continue
        calls = [
            ToolCall(
                t["name"], t["arguments"], t.get("result") or run_tool(t["name"], t["arguments"])
            )
            for t in record["tool_calls"]
        ]
        record["failures"] = check(by_id[record["id"]], record["answer"], calls)


def git_commit() -> str:
    out = subprocess.run(
        ["git", "describe", "--always", "--dirty"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def write_report(
    runs: list[dict], cases: list[dict], rechecked: bool = False, cases_file: str = "cases.toml"
) -> str:
    questions = {c["id"]: c.get("question") or " / ".join(c["turns"]) for c in cases}
    scored = f"Rechecked with the checks at commit {git_commit()}." if rechecked else ""
    lines = [
        "# Evaluation results",
        "",
        f"{len(cases)} cases from `eval/{cases_file}`. A case passes in a run when all its checks",
        f"pass. Stable = passed in every run. Commit = the code the model ran on. {scored}",
        "",
        "| provider | model | runs | stable cases | passed runs | unsupported amounts "
        "| median time | avg tokens | commit |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for run in runs:
        results = run["results"]
        by_case: dict[str, list[dict]] = {}
        for r in results:
            by_case.setdefault(r["id"], []).append(r)
        stable = sum(all(not r["failures"] for r in rs) for rs in by_case.values())
        passed = sum(not r["failures"] for r in results)
        made_up = sum(any("unsupported" in f for f in r["failures"]) for r in results)
        times = [r["seconds"] for r in results if "seconds" in r]
        median = f"{statistics.median(times):.1f} s" if times else "n/a"
        tokens = [r["input_tokens"] + r["output_tokens"] for r in results]
        lines.append(
            f"| {run['provider']} | {run['model']} | {run['runs']} | {stable}/{len(by_case)} "
            f"| {passed}/{len(results)} | {made_up} | {median} "
            f"| {statistics.mean(tokens):.0f} | {run['commit']} |"
        )

    for run in runs:
        lines += ["", f"## {run['provider']} / {run['model']} ({run['date']})", ""]
        by_case = {}
        for r in run["results"]:
            by_case.setdefault(r["id"], []).append(r)
        for case_id, rs in by_case.items():
            passed = sum(not r["failures"] for r in rs)
            mark = "PASS" if passed == len(rs) else "FAIL"
            lines.append(f"- {mark} {passed}/{len(rs)} `{case_id}`: {questions[case_id]}")
            failures = [f for r in rs for f in r["failures"]]
            for failure in dict.fromkeys(failures):
                lines.append(f"  - {failure} ({failures.count(failure)}x)")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", type=Path, help="default: cases.toml, or the file the runs used")
    parser.add_argument("--only", nargs="+", help="case ids to run")
    parser.add_argument("--report", nargs="+", type=Path, help="write results.md from runs")
    parser.add_argument("--recheck", action="store_true", help="score saved answers again")
    args = parser.parse_args()

    if args.report:
        runs = [json.loads(path.read_text()) for path in args.report]
        # A report on held-out runs needs holdout.toml, which each run records.
        args.cases = args.cases or EVAL_DIR / runs[0].get("cases_file", "cases.toml")
        cases = tomllib.loads(args.cases.read_text())["case"]
        if args.recheck:
            for run in runs:
                recheck(run, cases)
        report = write_report(runs, cases, args.recheck, args.cases.name)
        (EVAL_DIR / "results.md").write_text(report)
        return

    args.cases = args.cases or EVAL_DIR / "cases.toml"
    cases = tomllib.loads(args.cases.read_text())["case"]
    load_dotenv(find_dotenv(usecwd=True))
    provider = resolve_provider(args.provider)
    client, model = make_client(provider, args.model)
    selected = [c for c in cases if not args.only or c["id"] in args.only]

    run = {
        "provider": provider,
        "model": model,
        "runs": args.runs,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "commit": git_commit(),
        "results": [],
    }
    runs_dir = EVAL_DIR / "runs"
    runs_dir.mkdir(exist_ok=True)
    run["cases_file"] = args.cases.name
    path = runs_dir / f"{datetime.now():%Y%m%d-%H%M}-{provider}-{args.cases.stem}.json"

    for n in range(1, args.runs + 1):
        for case in selected:
            record = run_case(client, model, case, PACE.get(provider, 0.0))
            record["run"] = n
            run["results"].append(record)
            # Saved after every case, so a hang or Ctrl+C doesn't lose what already ran.
            path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
            status = "PASS" if not record["failures"] else "FAIL " + "; ".join(record["failures"])
            print(f"[{n}/{args.runs}] {case['id']}: {status}", flush=True)

    # The combined results.md is only written by --report, so one run can't overwrite it.
    path.with_suffix(".md").write_text(write_report([run], selected, cases_file=args.cases.name))
    print(f"saved {path} and {path.with_suffix('.md').name}")


if __name__ == "__main__":
    main()
