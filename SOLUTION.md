# CityWheels help desk agent: solution

## How to run

Python 3.12 and [uv](https://docs.astral.sh/uv/) (`brew install uv`). Without uv: `pip install -e .` in a virtualenv.

```
uv sync --locked
cp .env.example .env     # fill in GEMINI_API_KEY (GROQ_API_KEY for Groq)

uv run citywheels "I want to cancel booking CW-1002. How much will I get back?"
uv run citywheels        # conversation, follow-up questions keep the context
uv run pytest            # tests, no API key needed
```

The agent prints the tool calls it made above each answer, `-q` hides them. `--provider gemini|groq|ollama` and `--model` override `.env`.

The evaluation calls the real model and takes about 15 minutes on the Gemini free tier:

```
uv run python eval/run_eval.py --provider gemini --runs 3
uv run python eval/run_eval.py --provider gemini --runs 3 --cases eval/holdout.toml
```

Each run is saved to `eval/runs/`. `eval/results.md` is built from saved runs with `--report eval/runs/<file>.json ...`.



## Model and provider

The default is Gemini 3.5 Flash-Lite on the Google AI Studio free tier. I also ran the same agent on gpt-oss-120b (Groq) and qwen3:4b (Ollama, on my laptop) to compare.

All three accept the OpenAI chat format, so there is one `openai` client and a small table of base URLs, key names and default models in `citywheels/llm.py`. I picked Flash-Lite over Gemini 3.8 Flash because the free tier of 3.8 Flash allows 20 requests a day, which isn't enough for one evaluation run. The task suggests GitHub Models, but GitHub shut it down on 2026-07-30 (it's in their changelog), so Groq took that slot.

Gemini had the best results and answers in about 1.7 s (median per case). Groq is a bit faster but follows the prompt worse. Ollama took about a minute per question on 8 GB of RAM.

## How the agent works

The loop in `citywheels/agent.py` sends the conversation and the tool schemas to the model, runs whatever tools it asks for, adds the results to the conversation and asks again. It stops when the model answers. If that hasn't happened after 6 rounds, the customer gets a fixed answer with the staff contact. In conversation mode the same message list is kept between questions, so "and if I cancel tomorrow?" works.

Tools, in `citywheels/tools/`:

- `search_policies` splits the three policy files into `##` sections and ranks them with a small BM25 written by hand. I compared a few variants on 28 test queries before picking it ([eval/retrieval_results.md](eval/retrieval_results.md)).

- `get_booking` returns one booking or `not_found`. It accepts `CW-1002`, `cw1002` or just `1002`.

- `calculate_refund` gets only the booking number (and optionally when the customer would cancel). It looks up the booking and applies all the cancellation rules: 100 / 50 / 0% of the rental at 48h and 24h before the start, booking fee never refunded, deposit always refunded, only `confirmed` bookings can be cancelled, voucher bookings get a voucher back.

- `quote_price` and `calculate_late_fee` weren't required. I added them because price and late fee questions need arithmetic too.

Every tool returns a dict with a `status` field. Arguments coming from the model are checked with Pydantic first, and a wrong argument goes back to the model as an error instead of crashing the program.

The system prompt is about fifteen short lines. Two examples:

> Never calculate amounts yourself. Give the amounts exactly as the tools return them.
>
> You can't cancel or change bookings. When a customer wants to, give the refund from calculate_refund and tell them to contact the staff to do it.

The prompt also gives today's date, because opening hours depend on the season.

Tests: each tool has unit tests, including every refund rule and both boundaries (exactly 48h and exactly 24h before the start). The agent loop is tested with a fake model in `tests/fakes.py`: it asks for a tool, then the test checks that the tool ran and that its result reached the second model call. GitHub Actions runs ruff and the tests on every push.

## Evaluation

`eval/cases.toml` has 27 questions: policies, prices, bookings, refunds including the 48h / 24h boundaries, a two-question conversation, things only the staff can decide, refusals and a prompt injection. The checks run automatically: which tools were called and what they returned, the amounts in the answer (compared as numbers), words the answer must or must not contain, whether it refused, the language, and whether it claims to have cancelled anything. A case also fails if the answer contains a EUR amount that no tool returned.

Final runs, same prompt and code (commit `0cad7cc`) for all three. "Stable" means the case passed in every run.

| model | runs | stable cases | passed runs | median time per case |
| --- | --- | --- | --- | --- |
| Gemini 3.5 Flash-Lite | 3 | 26/27 | 80/81 | 1.7 s |
| gpt-oss-120b (Groq) | 3 | 24/27 | 74/81 | 0.9 s |
| qwen3:4b (Ollama) | 1 | 23/27 | 23/27 | 62.5 s |

Gemini's one miss: once it gave the right amount for a voucher booking but didn't say the refund comes back as a voucher. Groq still uses winter opening hours and answers the Polish question in English (0/3 for both), and once left out the staff contact. Ollama missed the voucher and the staff contact once each, timed out on one question, and once asked a follow-up question with "!" instead of "?", which my check counted as not asking. Per-case details are in [eval/results.md](eval/results.md).

Because I tuned the prompt on those 27 cases, I also set up a held-out set of 8 questions (`eval/holdout.toml`). I wanted questions from someone who doesn't know how the agent works, so I had them generated by a separate Claude instance that could only read the policies and bookings, not the code, the prompt or any results. I checked the expected amounts by hand against the policies. The set ran on Gemini three times, with nothing changed in between or afterwards ([details](eval/runs/20261102-1615-gemini-holdout.md)).

Result: 5 of 8 stable, 19 of 24 runs, a lot lower than on my own cases. Two failures are real. Once the model added the 2 EUR booking fee to a 54 EUR quote and said "56 EUR", a sum no tool returned. And asked about a student discount, it answered "we do not offer a student discount", while the documents just don't mention one. The third failure is the case's fault: it expected the answer to say 23 EUR, but the question only asked whether the voucher refund can go to a card, and all three answers ("no, it comes back as a voucher") were correct. I left the case as it was.

What failed along the way. The first Gemini run passed 22 of 26 cases. Two answers told the customer to "contact the staff" without giving the email or phone, because the prompt only included the contact in the refusal line. I had noticed the same thing when trying a storm question by hand. The model also worked out late fees itself (18 EUR, correct, but against the "never calculate" rule), and once gave winter opening hours in June. I added the contact to the "staff decide" line, added a line about using today's date, and wrote `calculate_late_fee`, since telling the model not to calculate clearly wasn't enough. After that Gemini passed all 26 cases in three runs. Those were the same cases I had just fixed, so I don't take 26/26 as proof the agent is right, which is why the held-out set exists.

Groq with the same prompt ignored the date, answered a Polish question in English and asked "how many bikes?" when the customer wrote "a city bike". I didn't tune the prompt for Groq on purpose: the point was to compare models on one prompt. The small Ollama model got the date and Polish right but was slow. On the main cases no model ever gave a EUR amount that a tool hadn't returned. The only one I saw was in the held-out set (54 + 2 = 56), so moving amounts into code mostly worked, but the model can still add them up on its own. Other kinds of made-up facts did slip through, see limitations.

The other models also found bugs in my code. Ollama searched for "cancellation" and got nothing back, because my stemmer didn't handle "-ation". Groq and Ollama phrased things in ways my checker didn't recognise. Later two reviewers with no context (a fresh Claude agent and Codex) found that the agent could say a booking "has been canceled" and still pass, and that some checks were too loose (for example "ID" matched "valid"). I fixed those and reran all three models on one commit. What I changed after the review and what I left is in DECISIONS.

## How I used AI coding assistants

I used Claude Code mostly to write code. I planned the project in small steps, decided the design for each one (no framework, one OpenAI-compatible client, CLI only, amounts in code, tool calls visible by default, comparing models on one prompt), had Claude Code write the code and tests, then read and tested the result before committing. Docs and decisions were kept up to date as I went, in `docs/`.

It was wrong more often than I expected because of outdated knowledge. It gave me a GitHub Models setup with a specific endpoint and token permission, and I only found out the service had been shut down when that permission didn't exist on GitHub. From then on I checked the current provider docs before any config, which caught more: the Gemini 2.5 models it would have used are already legacy, and it set temperature to 0, which the Gemini 3 docs advise against. Later it imported `httpx` in a test because older versions of the `openai` library used it. The current version uses a fork called `httpx2`, so the tests failed on import.

It also guessed instead of measuring. When English questions started getting answers in Spanish, German or Dutch, its first fix was to reword the language line, which still gave English in only 2 of 5 tries. I ran a few versions of that line 5 times each instead, and "Reply in English, unless the customer writes in another language" gave 5 of 5.

Smaller things I caught when reviewing its code: a test that checked two scenarios at once, a function that guessed the provider from the URL (Gemini's URL doesn't contain "gemini"), and a stricter Polish check that would have failed a correct short answer.

## Limitations

- The search works on keywords, so it misses questions with no words in common with the policy ("flat tyre" vs "bike breaks") and still returns sections for off-topic questions. Refusing is left to the model.
- The checks don't catch made-up facts that aren't amounts. Once Ollama said a refund takes "2 business days" (the policy says 5) and the case passed.
- The 27 main cases are mine and I tuned the prompt on them. Ollama ran once instead of three times because it was slow, so there's no stability number for it.
- The policies leave three things open: how the deposit comes back for voucher bookings, how to charge the hours after full days (e.g. 26h), and whether the weekly discount covers add-ons. Quotes that depend on the last two tell the customer the staff can confirm.
- Anyone can ask about any booking number. A real help desk would check who is asking first.

## What I'd do next

First, a check for made-up facts that aren't amounts, probably an LLM judge that compares the answer with the policy sections it was given. That's the main gap the evaluation has now. Then customer verification before showing booking details. And with more than a few documents, a better search (embeddings or hybrid), since keyword search already misses some questions.

## More detail

- [docs/DECISIONS.md](docs/DECISIONS.md): choices and rejected options.
- [docs/DEVLOG.md](docs/DEVLOG.md): what happened, in order, including mistakes.
- [eval/results.md](eval/results.md): latest evaluation.
