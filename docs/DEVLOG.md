# Dev log

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

### AI ASSISTANT NOTES
- Claude wrote a refund test that mixed two scenarios (a 100% assert inside a test named after rounding) -> split it.
- Claude suggested GitHub Models from memory (the task description lists it too), incl. endpoint URL and model name. Service was already retired. Noticed only when the token permission didn't exist. Lesson: double check provider docs before writing config.
- Claude's first fix for the language bug (reword the line) was a guess and didn't work. Measuring variants did.
- Claude would have set temperature=0 out of habit; Gemini 3 docs say keep 1.0.
- Claude assumed `openai` uses `httpx` (true for older versions) and imported it in tests -> ImportError. Current version uses `httpx2`.
