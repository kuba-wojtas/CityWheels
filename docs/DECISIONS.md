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
