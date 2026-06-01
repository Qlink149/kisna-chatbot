# AI Providers (OpenAI + Groq)

The Kisna chatbot supports multiple LLM providers for **chat** workloads. Vector embeddings (Chroma knowledge base) remain OpenAI-only.

## Architecture

- `kisna_chatbot/ai/` — provider factory, chat completions, usage logging
- **Classifier** — chat completions (OpenAI or Groq)
- **GeneralAgent** — OpenAI Responses API (web search) by default; Groq chat mode without web search

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `AI_PROVIDER` | `openai` | Default provider: `openai` or `groq` |
| `AI_PROVIDER_CLASSIFIER` | (empty) | Override for Classifier |
| `AI_PROVIDER_GENERAL` | `openai` | Override for GeneralAgent |
| `AI_FALLBACK_ENABLED` | `true` | Retry with fallback on transient errors |
| `AI_FALLBACK_PROVIDER` | `openai` | Fallback provider name |
| `OPENAI_API_KEY` | — | Required when OpenAI is selected |
| `OPENAI_CHAT_MODEL` | `gpt-4o-mini` | OpenAI chat model |
| `GROQ_API_KEY` | — | Required when Groq is selected |
| `GROQ_CHAT_MODEL` | `llama-3.3-70b-versatile` | Groq model |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Groq OpenAI-compatible base URL |

## Switching providers

**Classifier only (recommended first step):**

```env
AI_PROVIDER=openai
AI_PROVIDER_CLASSIFIER=groq
GROQ_API_KEY=your_key
```

**GeneralAgent on Groq (degraded — no hosted web search):**

```env
AI_PROVIDER_GENERAL=groq
```

## Admin API (JWT)

- `GET /system/ai/config` — effective providers and models
- `POST /system/ai/test` — ping completion
- `GET /system/ai/usage?days=7` — usage aggregates from `ai_usage_logs`

## Capability matrix

| Feature | Classifier + OpenAI | Classifier + Groq | General + OpenAI | General + Groq |
|---------|---------------------|-------------------|------------------|----------------|
| Chat completions | Yes | Yes | — | Yes |
| Responses API | — | — | Yes | No |
| Hosted web search | No | No | Yes | No |

## Deprecated modules

- `kisna_chatbot.utils.get_openai_responses` → `kisna_chatbot.ai.complete_chat`
- Direct `openai_client` in processors → `kisna_chatbot.ai.run_general_agent`

## Testing

```bash
python -m unittest discover -s tests -v
```
