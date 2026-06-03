# Vercel deploy (testing only)

## Prerequisites

- MongoDB Atlas `MONGO_URI`
- Vercel account + CLI: `npx vercel login`

## Deploy

From `kisna-chatbot/`:

```bash
npx vercel link    # once
npx vercel deploy -y
```

Set **Root Directory** to `kisna-chatbot` if deploying from Git in the Vercel UI.

## Required environment variables (Vercel dashboard)

| Variable | Example / notes |
|----------|-----------------|
| `VERCEL` | Auto-set by Vercel (`1`); enables sync webhook + stderr logging |
| `ENV_MODE` | `dev` |
| `MONGO_URI` | Atlas connection string |
| `GROQ_API_KEY` or `GROQ_API_KEYS` | Chat LLM (Groq-first). Use comma-separated `GROQ_API_KEYS` for rate-limit rotation |
| `OPENAI_API_KEY` | Required for **KB embeddings** (Chroma), not for chat when using Groq |
| `AI_PROVIDER` | `groq` (default) |
| `AI_PROVIDER_GENERAL` | `groq` |
| `AI_FALLBACK_ENABLED` | `false` recommended on Groq-only |
| `GUPSHUP_*` | App ID, token, app name, API key, phone/source |
| `GUPSHUP_SOURCE` | E.164 without `+` (or `GUPSHUP_PHONE_NUMBER`) |
| `MONGO_DB_NAME` | e.g. `Kisna_Chatbot` |
| `WEBHOOK_URL` | `https://<host>/gupshup/message/kisna` — for setup script |

### Logging (Vercel Runtime Logs)

| Variable | Example / notes |
|----------|-----------------|
| `LOG_LEVEL` | `DEBUG` for troubleshooting; `INFO` in steady state |
| `LOG_HTTP_BODIES` | `true` to log sanitized webhook/API bodies; defaults on when `ENV_MODE=dev` |
| `LOG_PRETTY` | Ignored on Vercel (always single-line JSON) |
| `LOG_GUPSHUP_WEBHOOK_PAYLOAD` | Deprecated alias for `LOG_HTTP_BODIES` |

Recommended for Vercel testing: `LOG_LEVEL=DEBUG`, `LOG_HTTP_BODIES=true`, `ENV_MODE=dev`.

Filter logs by `request_id`, `event` (e.g. `http_request`, `http_response`, `inbound_message`, `pipeline_start`), or `phone_number`.

`KISNA_PHONE_NUMBER_ID` is **optional** for a single Kisna number (defaults to client `kisna`).

## Register Gupshup webhook

After deploy, set `WEBHOOK_URL` in `.env` and run:

```bash
python scripts/setup_gupshup_webhook.py
```

See [GO_LIVE.md](./GO_LIVE.md) for the full checklist.

## Verify

- Health: `GET https://<your-preview-host>/ping` → `{"status":"ok"}`
- Gupshup webhook: `https://<your-preview-host>/gupshup/message/kisna`

## Test webhook locally against deployed URL

```bash
set WEBHOOK_URL=https://<your-preview-host>/gupshup/message/kisna
python tests/test_gupshup_webhook.py integration
```

## Notes

- Webhook always returns 200 immediately and processes messages via FastAPI background tasks (avoids Gupshup retries on timeout).
- `vercel.json` uses `functions` + `rewrites` only (do not add legacy `builds` — Vercel rejects `builds` + `functions` together).
- Hobby plan: default timeout may be 10s; this project sets `maxDuration: 60` on `api/index.py` (Pro may be required for 60s on some plans).
- Production should use Docker/long-running hosting, not Vercel serverless.
