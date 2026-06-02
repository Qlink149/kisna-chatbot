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
KISNA_PHONE_NUMBER_ID=451074671429987

# Product catalog (required for "show me sofas" / product search)
KISNA_PRODUCT_API=https://your-api-host
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

### If you get `403` on `/partner/app/.../token`

`GUPSHUP_TOKEN` must be a **Partner Portal** token, not the WhatsApp `apikey`.

1. Log in at [partner.gupshup.io](https://partner.gupshup.io)
2. **Settings → API client details** → create/copy **Client Secret**
3. Add to `.env` (Partner Portal → Settings → API client details):

```env
GUPSHUP_PARTNER_EMAIL=your-partner-login-email
GUPSHUP_PARTNER_CLIENT_SECRET=your-client-secret
```

(Older accounts may use `GUPSHUP_PARTNER_PASSWORD` instead of client secret.)

4. Run the script again:

```bash
python scripts/setup_gupshup_webhook.py
```

**Or set webhook in the UI:** Partner Portal → app **Qliink** (your `GUPSHUP_APP_NAME`) → Webhook / Subscription → URL:

`https://kisna-chatbot.vercel.app/gupshup/message/kisna`

| Variable | Used for |
|----------|----------|
| `GUPSHUP_API_KEY` | Sending WhatsApp messages (`apikey` header) |
| `GUPSHUP_TOKEN` / partner login | Partner API (token, subscriptions, flows) |

List existing subscriptions:

```bash
python scripts/setup_gupshup_webhook.py --list
```

## 3b. Create complaint WhatsApp Flow (script)

The menu **Raise a Complaint** sends a Gupshup Flow. You need a flow **published on your Kisna WABA** (not Nilkamal’s legacy id).

1. Ensure partner auth in `.env` (same as webhook script — `GUPSHUP_TOKEN` or partner email + secret).
2. Optional in `.env`:

```env
GUPSHUP_FLOW_NAME=kisna_damage_complaint
GUPSHUP_FLOW_CATEGORIES=OTHER
GUPSHUP_FLOW_JSON_PATH=json/damage_complaint.json
```

3. Run from `kisna-chatbot/`:

```bash
python scripts/setup_gupshup_flow.py --dry-run
python scripts/setup_gupshup_flow.py
```

4. Copy the printed `flowId` into `.env` and Vercel:

```env
KISNA_DAMAGE_COMPLAINT_FLOW_ID=<flowId from script>
```

5. Redeploy Vercel and test **Raise a Complaint** on WhatsApp.

List flows: `python scripts/setup_gupshup_flow.py --list`

If create succeeded but upload failed (network error on Windows), resume without creating a duplicate:

```bash
python scripts/setup_gupshup_flow.py --resume
```

Or: `python scripts/setup_gupshup_flow.py --flow-id YOUR_FLOW_ID --upload-only` then `--publish-only`.

API docs: [Create Flow](https://partner-docs.gupshup.io/reference/createflow), [Publish flow](https://partner-docs.gupshup.io/reference/publishflow).

## 4. About `KISNA_PHONE_NUMBER_ID` (you can skip it)

This is **not** your phone number. It is Meta’s internal `phone_number_id` inside webhook JSON (`metadata.phone_number_id`).

- If **unset**: every inbound message is handled as client **`kisna`** (fine for one WhatsApp number).
- If you later run **multiple brands** on one server, set `KISNA_PHONE_NUMBER_ID` after you see it in Vercel logs (first WhatsApp message logs: `Webhook phone_number_id not in env map`).

You do **not** need this for testing with only Kisna on `GUPSHUP_SOURCE`.

## 5. Vercel env (required or the site shows 500)

In Vercel → **Settings → Environment Variables**, add at least:

- `ENV_MODE=dev` (do not use `prod` until all prod keys are set)
- `MONGO_URI`, `MONGO_DB_NAME`
- `GROQ_API_KEY`, `AI_PROVIDER=groq`, `AI_PROVIDER_GENERAL=groq`, `AI_FALLBACK_ENABLED=false`
- `GUPSHUP_APP_ID`, `GUPSHUP_TOKEN`, `GUPSHUP_APP_NAME`, `GUPSHUP_API_KEY`, `GUPSHUP_SOURCE`
- `KISNA_DAMAGE_COMPLAINT_FLOW_ID` (from `setup_gupshup_flow.py` after publish)
- `KISNA_PHONE_NUMBER_ID` (from webhook logs, e.g. `451074671429987`)
- `KISNA_PRODUCT_API` (catalog base URL for product search)

`OPENAI_API_KEY` is **not** required when using Groq only.

After deploy, open `https://YOUR-APP.vercel.app/ping` — must return `{"status":"ok"}`. If you see **FUNCTION_INVOCATION_FAILED**, check **Logs** for missing env or import errors.

## 6. Test on WhatsApp

1. Send **Hi** (first message) — welcome text + main menu list.
2. Send **What do you have?** — product list if `KISNA_PRODUCT_API` is set.
3. Send **I have a complaint** — complaint WhatsApp Flow opens.
4. Check **Vercel → Logs** and Atlas → `users` collection.

## 7. No webhook secret

Leave `GUPSHUP_WEBHOOK_SECRET` empty. The app skips signature verification in dev (warning only).

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No reply on WhatsApp | Vercel logs; confirm `GUPSHUP_API_KEY` + `GUPSHUP_SOURCE`; webhook script ran |
| 401 on webhook | If you set `GUPSHUP_WEBHOOK_SECRET`, Gupshup must sign requests — remove secret for now |
| Mongo timeout | Atlas Network Access → allow `0.0.0.0/0` for testing |
| Groq errors | `AI_FALLBACK_ENABLED=false` and valid `GROQ_API_KEY` on Vercel |
