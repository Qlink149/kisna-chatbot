# Go live on Vercel (testing)

Step-by-step for Mongo + Groq + Gupshup with `GUPSHUP_SOURCE` (no `GUPSHUP_PHONE_NUMBER` required).

## 1. `.env` essentials

```env
ENV_MODE=dev

# MongoDB Atlas
MONGO_URI=mongodb+srv://...
MONGO_DB_NAME=Kisna_Chatbot

# Groq only (no OpenAI)
AI_PROVIDER=groq
AI_PROVIDER_CLASSIFIER=groq
AI_PROVIDER_GENERAL=groq
AI_FALLBACK_ENABLED=false
GROQ_API_KEY=gsk_...

# Gupshup outbound + partner API
GUPSHUP_APP_ID=
GUPSHUP_TOKEN=
GUPSHUP_APP_NAME=
GUPSHUP_API_KEY=
GUPSHUP_SOURCE=919549549339

# Webhook registration (run script after deploy)
WEBHOOK_URL=https://YOUR-APP.vercel.app/gupshup/message/kisna
GUPSHUP_WEBHOOK_TAG=kisna-chatbot
GUPSHUP_WEBHOOK_VERSION=3
GUPSHUP_WEBHOOK_MODES=MESSAGE

# Leave empty for now (optional)
GUPSHUP_WEBHOOK_SECRET=
KISNA_PHONE_NUMBER_ID=
```

`GUPSHUP_SOURCE` is the WhatsApp business number **without** `+` — same as your value `919549549339`.

## 2. Deploy to Vercel

```bash
cd kisna-chatbot
npx vercel login
npx vercel link
npx vercel deploy -y
```

Copy the deployment URL, then set the same variables in **Vercel → Settings → Environment Variables** (not only local `.env`).

Check: `https://YOUR-APP.vercel.app/ping` → `{"status":"ok"}`

## 3. Register Gupshup webhook (script)

Update `WEBHOOK_URL` in `.env` to your real Vercel URL, then:

```bash
cd kisna-chatbot
python scripts/setup_gupshup_webhook.py
```

List existing subscriptions:

```bash
python scripts/setup_gupshup_webhook.py --list
```

## 4. About `KISNA_PHONE_NUMBER_ID` (you can skip it)

This is **not** your phone number. It is Meta’s internal `phone_number_id` inside webhook JSON (`metadata.phone_number_id`).

- If **unset**: every inbound message is handled as client **`kisna`** (fine for one WhatsApp number).
- If you later run **multiple brands** on one server, set `KISNA_PHONE_NUMBER_ID` after you see it in Vercel logs (first WhatsApp message logs: `Webhook phone_number_id not in env map`).

You do **not** need this for testing with only Kisna on `GUPSHUP_SOURCE`.

## 5. Test on WhatsApp

1. Send **Hi** to your Gupshup WhatsApp number.
2. Check **Vercel → Logs** for errors (Mongo, Groq, Gupshup send).
3. Check Atlas → database `MONGO_DB_NAME` → collection `users` for a new document.

## 6. No webhook secret

Leave `GUPSHUP_WEBHOOK_SECRET` empty. The app skips signature verification in dev (warning only).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No reply on WhatsApp | Vercel logs; confirm `GUPSHUP_API_KEY` + `GUPSHUP_SOURCE`; webhook script ran |
| 401 on webhook | If you set `GUPSHUP_WEBHOOK_SECRET`, Gupshup must sign requests — remove secret for now |
| Mongo timeout | Atlas Network Access → allow `0.0.0.0/0` for testing |
| Groq errors | `AI_FALLBACK_ENABLED=false` and valid `GROQ_API_KEY` on Vercel |
