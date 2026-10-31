"""Run the agent on eval/cases.toml and write eval/results.md.

Run:    uv run python eval/run_eval.py [--provider gemini] [--model ...] [--runs 3]
Report: uv run python eval/run_eval.py --report eval/runs/<file>.json [more files...]
"""

import argparse
import json
import re
import statistics
import subprocess
import time
import tomllib
from datetime import datetime
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from openai import RateLimitError

from citywheels.agent import ToolCall, new_conversation, run_agent
from citywheels.llm import make_client, resolve_provider

EVAL_DIR = Path(__file__).parent
STAFF_CONTACT = ("help@citywheels.example", "+48 000 000 000")

# Seconds to wait per model request, to stay under each free tier's requests per minute.
PACE = {"gemini": 4.5, "groq": 2.0, "ollama": 0.0}

AMOUNT = re.compile(
    r"(?:€|\beur\b)\s*(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s*(?:€|\beur\b|\beuros?\b)",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def to_number(text: str) -> float:
    return round(float(text.replace(",", ".")), 2)


def numbers_in(value) -> set[float]:
    """Every number in a tool result, including numbers inside text (policy sections)."""
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        return set().union(*(numbers_in(v) for v in value))
    if isinstance(value, str):
        return {to_number(n) for n in NUMBER.findall(value)}
    if isinstance(value, int | float) and not isinstance(value, bool):
        return {round(float(value), 2)}
    return set()


def unsupported_amounts(answer: str, calls: list[ToolCall]) -> list[str]:
    allowed = numbers_in([c.result for c in calls])
    amounts = [a or b for a, b in AMOUNT.findall(answer)]
    return sorted({a for a in amounts if to_number(a) not in allowed})


def check(case: dict, answer: str, calls: list[ToolCall]) -> list[str]:
    failures = []
    text = answer.lower()
    called = {c.name for c in calls}

    for tool in case.get("tools", []):
        if tool not in called:
            failures.append(f"{tool} not called")
    if "tools_any" in case and not called & set(case["tools_any"]):
        failures.append(f"none of {case['tools_any']} called")
    for item in case.get("must_contain", []):
        options = item if isinstance(item, list) else [item]
        if not any(option.lower() in text for option in options):
            failures.append(f"missing {' / '.join(options)}")
    for item in case.get("must_not_contain", []):
        if item.lower() in text:
            failures.append(f"contains {item}")
    if case.get("refuse") and not any(c in text for c in STAFF_CONTACT):
        failures.append("no staff contact")
    if case.get("clarify"):
        if "?" not in answer:
            failures.append("didn't ask a question")
        if "quote_price" in called:
            failures.append("quoted a price without asking")
    if case.get("language") == "pl" and not re.search("[ąćęłńóśźż]", text):
        failures.append("not in Polish")
    if unsupported := unsupported_amounts(answer, calls):
        failures.append(f"unsupported amounts {', '.join(unsupported)}")
    return failures


def run_case(client, model: str, case: dict, pace: float) -> dict:
    messages = new_conversation()
    calls: list[ToolCall] = []
    record = {"id": case["id"], "steps": 0, "input_tokens": 0, "output_tokens": 0}
    started = time.monotonic()
    for question in case.get("turns", [case.get("question")]):
        turn_start = len(messages)
        try:
            result = run_agent(client, model, messages, question)
        except RateLimitError:
            del messages[turn_start:]
            print("  rate limited, waiting 60 s", flush=True)
            time.sleep(60)
            try:
                result = run_agent(client, model, messages, question)
            except RateLimitError:
                record |= {"answer": "", "tool_calls": [], "failures": ["rate limited"]}
                return record
        calls += result.tool_calls
        record["steps"] += result.steps
        record["input_tokens"] += result.input_tokens
        record["output_tokens"] += result.output_tokens
        time.sleep(pace * result.steps)

    record["seconds"] = round(time.monotonic() - started - pace * record["steps"], 1)
    record["answer"] = result.answer
    record["gave_up"] = result.gave_up
    record["tool_calls"] = [{"name": c.name, "arguments": c.arguments} for c in calls]
    record["failures"] = check(case, result.answer, calls)
    return record


def git_commit() -> str:
    out = subprocess.run(
        ["git", "describe", "--always", "--dirty"], capture_output=True, text=True, check=False
    )
    return out.stdout.strip()


def write_report(runs: list[dict], cases: list[dict]) -> str:
    questions = {c["id"]: c.get("question") or " / ".join(c["turns"]) for c in cases}
    lines = [
        "# Evaluation results",
        "",
        f"{len(cases)} cases from `eval/cases.toml`, each run {runs[0]['runs']} times.",
        "A case passes in a run when all its checks pass. Stable = passed in every run.",
        "",
        "| provider | model | stable cases | passed runs | unsupported amounts "
        "| median time | avg tokens | commit |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
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
        tokens = [r["input_tokens"] + r["output_tokens"] for r in results]
        lines.append(
            f"| {run['provider']} | {run['model']} | {stable}/{len(by_case)} "
            f"| {passed}/{len(results)} | {made_up} | {statistics.median(times):.1f} s "
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
    parser.add_argument("--only", nargs="+", help="case ids to run")
    parser.add_argument("--report", nargs="+", type=Path, help="rebuild results.md from runs")
    args = parser.parse_args()

    cases = tomllib.loads((EVAL_DIR / "cases.toml").read_text())["case"]
    if args.report:
        runs = [json.loads(path.read_text()) for path in args.report]
        (EVAL_DIR / "results.md").write_text(write_report(runs, cases))
        return

    load_dotenv(find_dotenv(usecwd=True))
    provider = resolve_provider(args.provider)
    client, model = make_client(provider, args.model)
    selected = [c for c in cases if not args.only or c["id"] in args.only]

    results = []
    for n in range(1, args.runs + 1):
        for case in selected:
            record = run_case(client, model, case, PACE.get(provider, 0.0))
            record["run"] = n
            results.append(record)
            status = "PASS" if not record["failures"] else "FAIL " + "; ".join(record["failures"])
            print(f"[{n}/{args.runs}] {case['id']}: {status}", flush=True)

    run = {
        "provider": provider,
        "model": model,
        "runs": args.runs,
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "commit": git_commit(),
        "results": results,
    }
    runs_dir = EVAL_DIR / "runs"
    runs_dir.mkdir(exist_ok=True)
    path = runs_dir / f"{datetime.now():%Y%m%d-%H%M}-{provider}.json"
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    if not args.only:
        (EVAL_DIR / "results.md").write_text(write_report([run], selected))
    print(f"saved {path}")


if __name__ == "__main__":
    main()
