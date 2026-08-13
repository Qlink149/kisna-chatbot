# KISNA / KIA — WhatsApp jewellery assistant

FastAPI service behind Gupshup WhatsApp, with an LLM classifier, a Clara
catalogue search, and a knowledge base for brand/policy questions.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in the required keys
```

`OPENAI_API_KEY` is required: OpenAI is the default chat provider for every
agent and is also used for KB embeddings. Groq is fallback-only — see the
ceiling note in `.env.example` before switching any agent to it.

## Tests

```bash
pytest                    # full suite; no network, no LLM calls
pytest -m live            # only tests that need a real provider
```

The suite is hermetic by design. `tests/conftest.py` blocks every route to a
provider at the client boundary and replaces provider credentials with
sentinels, because `utils/env_load.py` calls `load_dotenv()` at import — so
without the guard, importing the package pulls a real `.env` into every test
process and results depend on the machine.

Two markers:

| marker | meaning |
|---|---|
| `live` | makes real LLM calls; deselected by default |
| `no_search_recap` | targets search mechanics behind the confirmation gate, so it runs with `KISNA_SEARCH_CONFIRM_ENABLED=false` |

Everything else runs with the **production** search-confirmation default.

## Release gate — classifier regression

**Run this before every deploy that touches a prompt, the classifier, or the
entity extractor.** It calls the live model, so it is deliberately NOT part of
`pytest` and is unaffected by the test isolation fixture.

```bash
python scripts/run_classifier_regression.py --label pre-release
# or
make regression
```

It runs `tests/multilingual_regression.json` (Gujarati and Devanagari native
script, romanized regional, store true-positives, store/product contrast pairs,
and context-dependent follow-ups) against the live classifier and entity
extractor: three batched screening runs, then individual re-verification of any
case that failed or varied. Provider and model are pinned to OpenAI
`gpt-4o-mini` inside the script, so results are comparable across runs and
machines regardless of local `.env`.

Output goes to `audit/regression_<label>.json` plus a per-bucket table.

**Ship only if every bucket holds at 100%.** A drop in `gu-native`,
`hi-native` or `romanized` means a prompt change hurt multilingual routing —
the failure mode this suite exists to catch.

Cost: ~18-24 API calls, roughly 150k prompt tokens, ~4 minutes.

Historical baselines live in `audit/` (`regression_baseline_v2.json` is the
reference; `regression_stage1..4.json` track the prompt remediation).

## Prompt budgets

`tests/test_prompt_budget.py` and `tests/test_prompt_balance.py` run in the
normal suite and exist because the classifier prompt once grew to 12,819
estimated tokens — past Groq's 12,000 TPM ceiling — one small addition at a
time, with nothing measuring the total.

- The classifier prompt owns **routing**; the entity extractor owns
  **extraction**. Do not duplicate a rule into both: two copies drift, and the
  drift is what caused the original regression.
- Fix a misclassification by fixing the **rule**, not by adding a fifth
  example. The balance test fails a secondary intent that accumulates examples.
