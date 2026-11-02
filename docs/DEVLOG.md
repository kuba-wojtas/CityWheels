# Dev log

Notes in the order things happened. Short version: tools and tests first, then the agent loop, then the evaluation (baseline run, fixes, control run), then the same eval on Groq and Ollama, then an external review and final runs.

Terms used below:
- baseline run = first full eval run on Gemini, before any fixes.
- control run = full rerun after fixes, to check nothing else broke.
- recheck = scoring saved answers again with newer checks, without calling the model.
- checker = the automatic checks in `eval/run_eval.py`.

### DATA OBSERVATIONS
- Hand-calculated refunds for all bookings (now = 2026-06-10 09:00 +02:00) -> expected values for tests.
- CW-1007 - starts in exactly 48h -> policy says "48 hours or more" -> 100% (EDGE CASE).
- CW-1010 - starts in exactly 24h -> 50% (EDGE CASE). Also booking fee 0 (booked in shop).
- CW-1004 - paid with voucher -> refund as voucher. Policy: deposit refunded "the same way it was paid", but data doesn't say how deposit was paid (UNCLEAR).
- All booking prices match the price list, incl. 15% weekly discount on CW-1009.
- Opening hours depend on season -> agent needs current date.
- Price questions need arithmetic (>6h = day price) -> extra tool `quote_price`, amounts stay in code.

### SETUP
- uv, pyproject.toml, ruff, pytest, empty `citywheels` package, `.env.example`.

### GET_BOOKING
- `data.py`: NOW, bookings loaded once, `find_booking` (internal, returns None).
- `tools/bookings.py`: wraps it into `status` result for the model.
- NOW as fixed +02:00 offset, not ZoneInfo("Europe/Warsaw") -> data already uses +02:00, ZoneInfo needs `tzdata` on Windows.
- Tests: details of CW-1002, loose numbers, unknown, garbage input, cancelled booking still returned.

### CALCULATE_REFUND
- Tiers compared as `timedelta`, not float hours -> exact 48h / 24h boundaries.
- Tests: all confirmed bookings vs hand-calculated table, 1 min past each boundary, 3 non-cancellable statuses, cancel tomorrow, time zones, bad / past / after-start cancel time, rounding to cents, fee never refunded.
- Checked the tests catch the boundary bug: changed `>=` to `>` -> CW-1007 and CW-1010 fail. Reverted.

### SEARCH_POLICIES
- Wrote 23 on-topic + 3 off-topic queries before any code, 10 of them worded differently than the docs (`mismatch`). Added 1 prompt injection query myself.
- Prediction before running: BM25 misses ~half of mismatch queries. Actual: 2/10 missed -> too pessimistic.
- Misses: "Where is the shop?" ("shop" is everywhere, answer section has no "where" words), "flat tyre" (zero shared words).
- Off-topic 1/4 no match -> keyword search can't tell topic, only words.
- Results: `eval/retrieval_results.md`.

### QUOTE_PRICE
- Duration rounded to whole minutes, integer math -> no float issues at the 6h / 24h boundaries.
- Price list quirk: city bike 6h = 24 EUR, 7h = 20 EUR (day price). Same for e-bike (54 vs 40). Shorter rental costs more. Tool follows the price list as written.
- Tests: all 10 bookings recalculated from price list (price, deposit, fee) -> all match. Plus each rule: started hour, exactly 6h, 6h01m, 26h, 31h, 6 vs 7 days, child seat per day, discount on add-ons, bikes x2, invalid input.
- Mutation check: `rest > 6h` -> `>=` -> 6h test fails. Reverted.
- Added missing return types (`compute_price`, `bm25`).

### GITHUB MODELS IS GONE
- Couldn't find the `models:read` permission when creating the token -> searched -> GitHub Models retired 2026-07-30 (changelog + docs).
- Switched third provider to Groq.

### LLM CLIENT
- Checked current docs before writing config: endpoints, model names. Gemini 2.5 models (what I'd have guessed) are already legacy.
- Free tier limits only visible in AI Studio: 3.8 Flash 5 RPM / 20 RPD, 3.5 Flash-Lite 15 RPM / 500 RPD -> Flash-Lite as default.
- `llm.py`: provider table + `make_client`, missing key / unknown provider -> `ConfigError` with a clear message.
- Smoke test with Gemini: tool call `get_booking({"booking_id":"CW-1002"})` -> answer "confirmed". Works.
- Gemini 3 thought signatures: tool calls come with `extra_content.google.thought_signature`. Sent history without it -> 400 Bad Request. With full `message.model_dump()` -> OK. Agent loop must append the model's message as returned.
- `load_dotenv()` looks for `.env` next to the calling script, not in the current dir -> didn't find it from a script outside the repo. Keep in mind for the CLI.

### AGENT LOOP
- `agent.py`: loop, tool table, prompt. Pydantic args model next to each tool.
- Fake model test builds real `ChatCompletion` objects -> `model_dump()` behaves like live. Tests: full round trip (tool result in 2nd request, thought signature kept), refund amount from code, not found, bad args / unknown tool / broken JSON, max steps, follow-up sees history.
- Mutation check: rebuilt the assistant message by hand instead of `model_dump()` -> round trip test fails on missing `extra_content`. Reverted.
- Live try with Gemini, 5 questions from the data README: all correct content, refusal with contact for "capital of Australia".
- "e-bike for a whole day" answered from search_policies (40 EUR), not quote_price -> eval should accept both.

### LANGUAGE BUG
- English refund question -> answer in Spanish. Repeated 4x: German, Dutch, 1x English (+ hit 429).
- 1st guess: "Reply in the customer's language" is vague -> changed to "language of the customer's last message". Still 2/5 English. Guess was wrong.
- Compared variants, 5 runs each: no language line 5/5 English, "Reply in English, unless the customer writes in another language" 5/5. Picked the 2nd (keeps other languages).
- Polish and German questions still answered in Polish / German, Polish query searched in English.
- Small sample (5 runs) -> recheck in eval.
- Polish "O której otwieracie w sobotę?" -> gave both seasons instead of using today's date. Eval case.

### RATE LIMITS
- 429 after ~17 requests in ~1.5 min (limit 15 RPM). Built-in retry in `openai` waits too short.
- CLI needs a readable message instead of a stack trace, eval needs pacing.

### CLI
- `cli.py` + `[project.scripts]` -> `uv run citywheels`.
- Moved fake client to `tests/fakes.py`, it can now raise scripted errors.
- Tests: answer + tool lines, `-q`, config error, connection error hint, conversation memory, 429 mid-conversation drops the turn.
- openai 3.x is built on `httpx2`, not `httpx` -> first version of the CLI tests failed on import.
- Live: follow-up "what if I cancel on 12 June at 10:00?" -> `cancel_at: 2026-06-12T10:00:00+02:00` -> exactly 24h before CW-1001 starts -> 50% -> 70 EUR. Correct.
- Live: missing Groq key and Ollama not running -> one-line messages.

### MANUAL TESTING
- Storm question ("storm in 2 days, rental tomorrow for 3 days, refund?") -> correct answer, says "contact the staff", but no email / phone.
- Cause: prompt gives the contact only in the refusal line, the "staff decide" line just says "contact the staff".
- Plan: add as eval case first, see it fail, then fix the prompt and rerun everything.

### EVAL: PREDICTION (written before the first run)
- 26 cases, Gemini 3.5 Flash-Lite, 3 runs each. Guess: ~19-21 stable.
- Sure fail: `storm` (no contact, known prompt gap).
- Likely fail: `late-return-fee` (no tool for late fees -> model does the math -> unsupported amount 18).
- Flaky: `open-saturday-pl` (gave both seasons before), `price-two-city-8h` / `price-week-child-seat` (model may add price + fee itself), `change-booking` (needs booking + policy), `price-family-clarify` (may assume 1 bike instead of asking), `weather-tomorrow` (search hits "Bad weather").
- Should pass: refunds incl. 48h / 24h edges (math is in code), off-topic, not found.

### EVAL: BASELINE
- 22/26 stable, 68/78 runs passed. Better than predicted (19-21).
- `storm` 0/3 and `stolen-bike` 0/3: same prompt gap, contact missing. Stolen bike wasn't in my prediction -> confirms the cause is systematic, not one question.
- `late-return-fee` 0/3: model computed 18 EUR itself (correct number, broken rule). Prompt rule ignored.
- `open-saturday` 2/3: one run gave both seasons.
- Checker limitation: "6.00 EUR" (1.5 x 4, also model math) not flagged, because 6 appears in the price list text ("longer than 6 hours"). Any number from tool results counts as supported.
- Runner bug: progress not visible when output goes to a file (print buffering) -> `flush=True`.

### EVAL: FIXES
- Prompt: contact added to the "staff decide" line. New line: "When the answer depends on the date, like opening hours, use today's date."
- New tool `calculate_late_fee`. Eval case changed to expect the tool + 18 EUR.
- Rerun of the 5 changed cases x3: all 15 pass (were 2/3, 3/3, 0/3, 0/3, 0/3).

### EVAL: HUNG CONTROL RUN
- Control run froze at case 40/78 (39/40 passed so far, 1 fail: `open-saturday` with winter hours again). Laptop went to sleep, request never returned.
- Results were only saved at the end -> the 40 answers were lost.
- Fixes: client timeout 120 s (default is 10 min), results saved after every case, failed request = failed case instead of a crash.
- Use `caffeinate -i` for long runs on macOS.

### EVAL: CONTROL RUN
- Clean commit 0ffb0b8, `caffeinate -i`, 14 min, no 429, no hangs.
- 26/26 stable, 78/78 runs, 0 unsupported amounts (baseline: 22/26, 68/78, 3). Median 1.3 s. Tokens 2261 -> 2518 (longer prompt + 5th tool).
- Not reading this as "done": `open-saturday` failed 1/7 runs since the fix (in the hung run). Cases written by me, the 4 baseline fails were fixed on purpose. Checks are lenient (substring, contact = refusal, any number from tools = supported).
- Next: Groq + Ollama on the same cases for a real spread.

### GROQ + OLLAMA SETUP
- Smoke test: both call `get_booking` and answer. Groq 1.6 s total, Ollama 55 s (incl. loading the model).
- Groq writes "CW‑1002" with a non-breaking hyphen (U+2011). No eval check looks for booking numbers, but worth knowing.
- Groq limits (from response headers): 1000 requests/day, 8000 tokens/min. One request ~1200 tokens -> ~6/min -> pace 10 s.
- Ollama `qwen3:4b`, refund question: thinking on (default) 123 s, correct. `reasoning_effort="none"` (fix suggested in a GitHub issue) 299 s, more tokens, and the reasoning leaked into the answer ("Okay, let me process this step by step..."). Kept the default.
- ~2 min per question -> Ollama gets 1 eval run (~1 h), not 3. Gemini and Groq 3 runs.

### EVAL: GROQ (same prompt as Gemini)
- `gpt-oss-120b`, 3 runs, 26 min. 20/26 stable, 66/78. Faster (0.8 s) and fewer tokens (1793) than Gemini.
- Ignores today's date: `open-saturday` 0/3 and `-pl` 0/3, gives winter hours (sometimes only winter = wrong in June).
- Polish question -> English answer 3/3. The language line that fixed Gemini is read as "always English".
- Asks "how many bikes?" for "a city bike for a week" (0/3) and "an e-bike for a day" (1/3 asked). Our "ask if bikes missing" rule taken too literally.
- `change-booking` 1/3: once said changes are "decided by staff" without searching. Wrong.
- 0 unsupported amounts, same as Gemini -> the code guardrail holds across models, prompt rules don't.
- `unknown-booking` 1/3 was a checker bug: "couldn’t" with a typographic apostrophe. Fixed (normalize ’ and non-breaking hyphens) -> 21/26, 67/78.
- Decided: keep the prompt as is for the comparison (same prompt, different models). No Groq-specific tuning.

### EVAL: RECHECK
- Runs now save tool results too. `--report ... --recheck` scores saved answers with the current checks.
- Older runs have no tool results -> rebuilt by running the tools again with saved arguments (tools are deterministic).
- Gemini control rechecked = same 26/26 -> recheck reproduces scores.

### EVAL: OLLAMA
- `qwen3:4b`, 1 run, 31 min, no timeouts. 23/26 (24/26 after checker fix). Median 67 s per case (max 193 s), ~4700 tokens (thinking counts).
- Better than Groq on behaviour: Polish question -> Polish answer with summer hours.
- `documents`: answered about parental consent instead of ID / passport. Real model miss.
- `unknown-booking`: "wasn't found" not in my phrase list -> checker bug #2. Phrase lists are brittle; checking the tool's `not_found` status would be more robust.
- `refund-bare-number`: called `search_policies("cancellation")` -> `no_match`. Stemmer only stripped -ing/-ed/-s, so "cancellation" never became "cancel". Model gave up and sent the customer to staff. Gemini and Groq went straight to calculate_refund, so they never hit it. Retrieval eval didn't catch it either (no query had "cancellation").

### FIXES AFTER OLLAMA
- Checker: added "wasn't found" / "was not found".
- Stemmer: strip -ation / -ations. Added "What is your cancellation policy?" to retrieval queries. Old stemmer: no match. New: found, BM25 x2 22/24 hit@1 and hit@3, nothing else changed.
- Provider runs were all done before the stemmer fix -> still comparable with each other. Not rerun (1h+ for one word the cloud models never used).
- Reran `refund-bare-number` on Ollama: passed, but it skipped search this time and called calculate_refund directly -> the pass says nothing about the fix. Also said refund comes "within 2 business days" (policy: 5 working days) without looking it up. Checker only checks amounts, so invented non-amount facts pass.
- Combined report: `--report` with Gemini control, Groq, Ollama + `--recheck`. Added "runs" column (Ollama has 1).

### CI
- `.github/workflows/tests.yml`: uv sync --locked, ruff check + format check, pytest. On push and pull requests.
- Action versions from current uv docs, pinned to commit hashes (a tag can be moved, a hash can't).
- Checked locally in a copy of the project without `.env` -> 129 passed, no test depends on API keys.

### EXTERNAL REVIEW
- Asked a fresh Claude agent (no memory of the project) and Codex to review the repo read-only, as a strict reviewer. Same prompt for both.
- Both: SOLUTION.md missing, eval checks too lenient (substrings, refusal = contact only, weak amount check), tool exception crashes the CLI, invented non-amount facts not caught, results.md hard to reproduce (rechecked, different commits).
- Claude only: agent implied it cancelled a booking (checked: Groq "has been canceled", scored PASS), data README not in repo, `cw1002` / `CW 1002` not found, no limits in quote_price, timeout shows Ollama hint, runner overwrites results.md, stale numbers in docs.
- Codex only: fixed UTC+02 wrong in winter, search returns something for off-topic queries, pricing assumptions shown as policy.
- Decided which to fix, see DECISIONS "Changed after the external review".

### FIXES AFTER REVIEW: AGENT
- Live check on Groq after prompt changes: "contact our staff to process the cancellation" instead of "has been canceled". "A city bike for a week" -> quote 136.85 + the note about the discount, no "how many?".
- Same check, new invented fact: "136.85 ... includes a €50 deposit and a €2 fee" (it doesn't). Next try said "plus". Amounts from tools, wording invented.
- 144 tests (tool error, limits, notes, empty provider response, timeout message, winter time, date-only cancel time, more booking id formats, follow-up test checks content).

### FIXES AFTER REVIEW: EVAL
- Whole-word matching ("ID" no longer matches "valid", "no" no longer matches "know").
- `amounts`: EUR amounts pulled from the answer and compared as numbers ("50" no longer passes on "50%").
- `statuses`: tool must have returned a given status (unknown booking checks `not_found` instead of a phrase list).
- Refusal = refusal phrase + contact, not contact alone.
- `no_action_claim`: fails on "has been cancelled" style claims. New case `cancel-request`.
- Amount check: only `*_eur` fields and amounts written in policy text count as supported (the "6.00 EUR" from "longer than 6 hours" would now be caught).
- Runner: single runs write their own .md next to the JSON, only `--report` writes results.md. Rate-limit waits not counted as time. `--cases` to run another case file.
- Tried raising the Polish check to 2 diacritics -> a correct short answer ("Otwieramy w sobotę o 08:00.") failed its test. Reverted to 1.
- Rechecked the saved runs: Gemini 78 -> 78, Groq 66 -> 66 (unknown-booking now passes, "has been canceled" now fails), Ollama 23 -> 24. No false alarms on real refusals.

### FINAL RUNS
- All three on commit 0cad7cc, no recheck: Gemini 26/27 stable (80/81), Groq 24/27 (74/81), Ollama 23/27 (1 run).
- Gemini: `refund-voucher` 1/3 missed, right amount but didn't say it comes back as a voucher.
- Groq: date + Polish still 0/3 (no Groq tuning, on purpose), `stolen-bike` 1x no contact.
- Ollama: no voucher mention, no contact on stolen bike, 1 timeout (>120 s), and asked "Please tell me the number of bikes!" with "!" -> my clarify check wants "?". Checker miss.
- Laptop battery died during the Ollama run. MacBook kept running, run finished, slower (memory).

### HELD-OUT SET
- 8 cases written by a separate Claude instance that could only read `data/`. Expected amounts checked by hand. Run once on Gemini (3x), nothing changed after.
- 5/8 stable, 19/24 runs. Much lower than 26/27 on my own cases, which is the point of having it.
- `price-two-ebikes-three-hours` 2/3: once "54 EUR + 2 EUR fee = 56 EUR". Model added two tool amounts itself, caught by the unsupported amount check. New kind of failure.
- `student-discount-not-covered` 2/3: "We do not offer a student discount". Failed the refusal check, but the real problem: docs don't say there is none, they just don't mention it. Missing info turned into a fact.
- `voucher-booking-refund-to-card` 0/3: answers correct ("refunded as a new voucher"), case expected the amount 23 which the question didn't ask for. Case too strict, left as is.

### AI ASSISTANT NOTES
- Claude wrote a refund test that mixed two scenarios (a 100% assert inside a test named after rounding) -> split it.
- Claude suggested GitHub Models from memory (the task description lists it too), incl. endpoint URL and model name. Service was already retired. Noticed only when the token permission didn't exist. Lesson: double check provider docs before writing config.
- Claude's first fix for the language bug (reword the line) was a guess and didn't work. Measuring variants did.
- Claude would have set temperature=0 out of habit; Gemini 3 docs say keep 1.0.
- Claude assumed `openai` uses `httpx` (true for older versions) and imported it in tests -> ImportError. Current version uses `httpx2`.
