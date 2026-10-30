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

### AI ASSISTANT NOTES
- Claude wrote a refund test that mixed two scenarios (a 100% assert inside a test named after rounding) -> split it.
