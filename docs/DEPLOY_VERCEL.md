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
| `OPENAI_API_KEY` | |
| `GUPSHUP_*` | App ID, token, app name, API key, phone/source |
| `GUPSHUP_SOURCE` | E.164 without `+` (or `GUPSHUP_PHONE_NUMBER`) |
| `MONGO_DB_NAME` | e.g. `Kisna_Chatbot` |
| `WEBHOOK_URL` | `https://<host>/gupshup/message/kisna` — for setup script |

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

- On Vercel, messages are processed **synchronously** (`VERCEL=1`); Docker still uses background tasks.
- Hobby plan: 10s function timeout; full bot replies may need Vercel Pro (`maxDuration: 60` in `vercel.json`).
- Production should use Docker/long-running hosting, not Vercel serverless.
