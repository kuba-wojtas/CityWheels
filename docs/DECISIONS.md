# Decisions

### uv + pyproject.toml (no requirements.txt)
- One tool for Python version, venv and lock file.
- `pip install -e .` still works without uv.

### No agent framework
- Loop is ~50 lines, easy to write and test by hand.
- LangChain etc. would hide the part I need to explain.
- Would reconsider with many tools / multiple agents.

### One OpenAI-compatible client
- Gemini, GitHub Models and Ollama all expose OpenAI chat completions format.
- Only base URL, key and model name change -> one code path, easy model comparison.
- Rejected: native SDKs (3x the same loop), LiteLLM (extra dependency for 3 config entries).

### CLI only
- Task asks for CLI. Web/TUI considered, dropped -> time goes to agent, tests, eval.

### argparse
- 2 commands, no need for Typer/Click.

### Booking as dataclass, not Pydantic
- bookings.json is our own static file -> validation adds nothing.
- Validate where untrusted data comes in = tool arguments from the model (decide in agent stage).

### Tool results always have `status`
- `ok`, `not_found`, later e.g. `not_cancellable`.
- Same shape on success and failure -> easy for the model to read and for tests to check.
- Tools don't raise on domain errors (unknown booking etc.), exceptions only for real bugs.

### Loose booking numbers
- `cw-1002`, ` CW-1002 `, `1002` -> `CW-1002`. Customers often type just the number.

### calculate_refund takes only booking id (+ optional cancel time)
- Model never passes amounts or percentages -> nothing for it to calculate.
- Tool returns hours before start + percent so the model can explain the result without math.
- Two layers: `compute_refund` (pure rules, easy to test) and `calculate_refund` (lookup, validation, status).

### Float + round() for money
- Decimal is the textbook choice for money (float errors like 0.1 + 0.2).
- Here all prices are whole or half euros -> exact in float, round(x, 2) keeps cents clean.
- Would switch to Decimal with real prices (cents, VAT splits).

### Deposit refund method not guessed
- Policy: deposit comes back "the same way it was paid". Bookings only have `paid_with` for the booking.
- Tool returns `deposit_refund_method: same_as_paid` for every booking, rental method = `paid_with`.
- Applied to card bookings too -> the rule in the policy is the same for both.

### search_policies: BM25 over `##` sections
- All 3 policy files are ~2-3k tokens -> could go straight into the system prompt, no search needed. Task asks for a search tool, so built one. Would matter with hundreds of docs.
- Chunks = `##` sections (FAQ questions, price tables). ~22 sections.
- Compared variants on 27 queries (`eval/retrieval.py`): BM25 21/23 hit@3 vs plain word overlap 20/23, and 21 vs 16 at hit@1.
- Hand-written BM25 (~15 lines). Rejected: `rank_bm25` (dependency, barely maintained), embeddings (overkill for 3 files).

### Crude stemming + stopwords
- Strip -ing/-ed/-s, trailing e, doubled letter -> cancel/cancelled/cancelling, year/years match.
- Without it hit@3 drops 21 -> 19. NLTK stemmer = overkill.

### Heading weight x2
- FAQ headings are the questions themselves -> strong signal.
- x1 / x1.5 -> 20/23 hit@1, x2 / x3 -> 21/23. Plateau from x2, picked x2.
- No finer tuning (x1.75 etc.): 23 own queries, differences of 1 query = overfitting.

### No tuning for off-topic queries
- Off-topic no match only 1/4 ("recommend" -> helmet section, "all" -> prices).
- Could add stopwords / score threshold, but that's fitting to our own test set.
- `no_match` is a hint, refusing is the model's job -> check in agent eval.

### cancel_at rules
- In the past -> `invalid_cancel_time` (can't cancel yesterday).
- At or after rental start -> `not_cancellable` (policy only covers cancelling before start).
- No time zone -> shop time (+02:00).
