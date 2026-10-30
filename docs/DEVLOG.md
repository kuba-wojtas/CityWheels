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
