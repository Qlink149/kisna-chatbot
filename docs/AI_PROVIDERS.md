# AI Providers (OpenAI)

Production uses **OpenAI** (`gpt-4o-mini`) for the classifier, entity extractor,
GeneralAgent, and reply composer.

| Variable | Default | Notes |
|----------|---------|-------|
| `AI_PROVIDER` | `openai` | Only `openai` is supported |
| `AI_PROVIDER_CLASSIFIER` | (inherit) | Optional per-agent override |
| `AI_PROVIDER_GENERAL` | (inherit) | Optional per-agent override |
| `OPENAI_API_KEY` | — | **Required** |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | Chat model |

Setting `AI_PROVIDER=groq` (or any other value) raises at settings load.

Brand/policy answers use prompt-injected KB text in GeneralAgent — there is no
Chroma/vector retrieval path in this deployment.

Keep the classifier prompt under ~12k estimated tokens (`tests/test_prompt_budget.py`)
so provider request-size limits never become a silent outage.
