# Alignment investigation — reply/message lag

**Date:** 2026-08-20  
**Branch tip when investigated:** `v3-text-flow` @ `5eb34a5`  
**Method:** raw Mongo `chat_messages` / `message_traces` / `ai_usage_logs` only for Task 1 verdict. Derived transcripts used only after join fix (Task 2).

Supporting dumps: [`alignment_raw_cases.json`](alignment_raw_cases.json), [`alignment_task4_raw.json`](alignment_task4_raw.json).

---

## TASK 1 — VERDICT: **(a) ANALYSIS ARTIFACT**

Not (b). Production pairs each `request_id` with the correct user message and assistant reply. The lag in `tests/replay/real_conversations.json` / derived `prod_reply` was a **builder join bug**.

### What settles it

For every cited turn, `message_traces.user_message` matches `chat_messages` user content on the same `request_id`, and `reply_preview` / assistant `content` match each other — **not** the “wrong” reply claimed in the finding.

| Case | Finding claimed `prod_reply` | Raw same-`request_id` assistant / trace |
|------|------------------------------|----------------------------------------|
| 10+1 @ 08:56:00 | old-gold exchange copy | Meri Roshni / 10+1 plan copy |
| exchange old gold @ 08:58:39 | empty | old-gold exchange copy |
| fake diamonds | Hari Krishna history | certified diamonds copy |
| Hari Krishna exports | empty | Hari Krishna Group history |
| hi @ 07:01:27 | “No active offers…” | welcome / greeting |
| hi @ 07:12:43 | live-support connect | welcome / greeting |

### Mechanism of the artifact (reproduced)

Deleted builder (`scripts/build_replay_conversations.py` @ `b333e36`) did:

1. Look **forward** only for an assistant with the same `request_id`.
2. If not found, **fall back to `session[i+1]` assistant even when `request_id` differs**.

When equal-`ts` rows are ordered **assistant before user**, step 1 misses the already-passed assistant and step 2 attaches the **next** turn’s reply → systematic one-turn lag. Reproduced locally: assistant-first within equal `ts` yields exactly  
`What is the Kisna 10+1 monthly plan` → `Yes, you can exchange old gold…`.

---

## The 5 raw side-by-side comparisons

### CASE 1 — `What is the Kisna 10+1 monthly plan` (2nd ask, 08:56:00)

- **phone:** `916376925843`  
- **request_id:** `80aa15dd-0b9f-4173-bf3e-5f0ab7e7a4e2`  
- **Finding claimed reply:** `Yes, you can exchange old gold at any Kisna store!`

**chat_messages** (`sort _id ASC`):

| _id | role | ts_iso | content |
|-----|------|--------|---------|
| `6a7d86a0f54b49f12812fe34` | user | 2026-08-13T08:56:00Z | `What is the Kisna 10+1 monthly plan` |
| `6a7d86a0f54b49f12812fe35` | assistant | 2026-08-13T08:56:00Z | `Kisna's *10+1 Monthly Plan* is a savings scheme called **Meri Roshni**. Here's how it works: … You make fixed monthly contributions for 10 months. …` |

**message_traces** (`client_id=kisna`):

| field | value |
|-------|--------|
| user_message | `What is the Kisna 10+1 monthly plan` |
| intent / outcome | `general` / `info_sent` |
| reply_preview | `Kisna's *10+1 Monthly Plan* is a savings scheme called **Meri Roshni**…` |
| steps | Message received → Understood as FAQ/general → Reply sent (same Meri Roshni text) |

**ai_usage_logs:** none for this `request_id`.

**alignment_check:** `user_matches_trace=true`; assistant is **not** the claimed old-gold text.

---

### CASE 2 — `Can I exchange old gold at Kisna?` (08:58:39)

- **request_id:** `31cdb927-4c0d-442e-a7c4-a210d69f5ecb`  
- **Finding claimed reply:** empty

**chat_messages:**

| role | ts_iso | content |
|------|--------|---------|
| user | 2026-08-13T08:58:39Z | `Can I exchange old gold at Kisna?` |
| assistant | 2026-08-13T08:58:39Z | `Yes, you can exchange old gold at any Kisna store! 🌟 You will receive **100% value** for your old gold…` |

**message_traces:** `user_message` = exchange question; `reply_preview` = same old-gold answer; `outcome=info_sent`.

**ai_usage_logs:** none.

**Note:** This assistant text is exactly what the finding wrongly attached to CASE 1.

---

### CASE 3 — `Do you sell fake diamonds?`

- **request_id:** `ef83a8f7-f362-4205-9555-a8a98415b7be`  
- **Finding claimed reply:** Hari Krishna Group history

**chat_messages:**

| role | ts_iso | content |
|------|--------|---------|
| user | 2026-08-19T10:17:44Z | `Do you sell fake diamonds?` |
| assistant | 2026-08-19T10:17:44Z | `Kisna exclusively sells certified diamonds, ensuring quality and authenticity…` |

**message_traces:** `user_message` = fake diamonds; `reply_preview` = certified diamonds answer.

---

### CASE 4 — `How is Kisna related to Hari Krishna exports ?`

- **request_id:** `3fdf875e-3d1c-44a7-917c-560ff13fb714`  
- **Finding claimed reply:** empty

**chat_messages:**

| role | ts_iso | content |
|------|--------|---------|
| user | 2026-08-19T10:18:02Z | `How is Kisna related to Hari Krishna exports ?` |
| assistant | 2026-08-19T10:18:02Z | `Kisna is a brand by Hari Krishna Group, which was established in 1992…` |

**message_traces:** matching `user_message` + Hari Krishna `reply_preview`.

**Note:** This is the text the finding wrongly attached to CASE 3.

---

### CASE 5a — `hi` (07:01:27)

- **phone:** `918696979791`  
- **request_id:** `8a84899d-84f6-4ba8-96bc-a52f8ece51cd`  
- **Finding claimed reply:** `No active offers right now…`

**chat_messages:**

| role | ts_iso | content |
|------|--------|---------|
| user | 2026-08-17T07:01:27Z | `hi` |
| assistant | 2026-08-17T07:01:27Z | `Welcome back, Yogansh Banthia! 👋 Main KIA hoon, aapka trusted jewellery assistant. Kya aaj aapko kuch khaas dhundhna hai?` |

**message_traces:** `user_message=hi`, `intent=greeting`, `reply_preview` = welcome text.

**Neighbor (next turn):** `Do you have any ongoing offers?` / `e196983a-…` → `No active offers right now…` — that is the claimed “lag” reply, on a **different** `request_id`.

---

### CASE 5b — `hi` (07:12:43)

- **request_id:** `245a1d96-33ba-404a-a5ce-16f9977aac61`  
- **Finding claimed reply:** `You are now connected to a live support agent…`

**chat_messages:**

| role | ts_iso | content |
|------|--------|---------|
| user | 2026-08-17T07:12:43Z | `hi` |
| assistant | 2026-08-17T07:12:43Z | `Welcome back, Yogansh Banthia! 👋 I'm KIA, your friendly jewellery assistant. What can I help you find today?` |

**message_traces:** greeting welcome (same).

**Neighbor:** at 07:13:04 an assistant row with **`request_id: null`** — `You are now connected to a live support agent. Please hold on.` — live-agent inject, not the bot reply for this `hi`.

---

## TASK 2 — Join fix + regenerated Part A

### Fix

- [`scripts/pull_verification_transcripts.py`](../scripts/pull_verification_transcripts.py): sort `(ts, _id)`; join traces by `request_id`+`client_id`; expose `paired_assistant_by_request_id`.
- [`scripts/build_replay_conversations.py`](../scripts/build_replay_conversations.py): **`prod_reply` only via `request_id` map**; removed next-assistant fallback.

### Regenerated artifacts

- `audit/transcripts_*_recent150.md`
- `audit/verification_raw/transcript_*_recent150.json`
- `tests/replay/real_conversations.json` (`join_method=request_id_only_no_positional_fallback`, 8 sessions / 147 turns)
- `audit/verification_raw/failure_flags_recent150.json` (rebuilt A2)

### Spot-check after fix

| message | corrected `prod_reply` head |
|---------|------------------------------|
| `Do you sell fake diamonds?` | certified diamonds… |
| `How is Kisna related to Hari Krishna exports ?` | Hari Krishna Group… |
| `hi` 07:01:27 | Welcome back… KIA… |

### Rebuilt A2 — which of the **9 report-table failures** survive?

(From prior verification report A2 narrative table; re-checked on corrected `request_id` pairs / raw Mongo.)

| # | Failure | Survives? | Evidence |
|---|---------|-----------|----------|
| 1–2 | QR “Yes, show me” → `fallback_used` / ladder | **YES** | 4× `fallback_used` on corrected data |
| 3 | Ongoing offers → empty / `no_products` | **YES** | 2× offers → no active offers + `outcome=no_products` |
| 4 | Evil eye collection → category menu | **YES** | e.g. evil eye → `What are you looking for today…` |
| 5 | “under 10 carats” → wizard/menu | **YES** | carat asks → category/gender prompts |
| 6 | Gujarati `વીંટી` → earrings | **YES** (raw) | `category=earring` on Yes-show-me after વીંટી (`59c45535-…`) |
| 7 | Punjabi in → Gujarati out | **YES** (raw) | PA user @ 09:04:39 → GU assistant (same `request_id`) |
| 8 | “above 15,000” after rakhi → menu reset | **YES** | `do you have anything above 15,000?` → category greeting |
| 9 | `filter$fix$*` dead-end | **YES** (code) | synthetic; still no handler on this branch tip |

**All 9 survive** once alignment is corrected. The lag did **not** invent these failures; it only corrupted reply attribution for FAQ/greeting turns.

Auto-flag dump grew noisier on wizard QR rows (`clarification_or_menu_on_productish` on Gold/Diamond taps) — treat the table above as the authoritative Part A narrative, not every auto-flag.

---

## TASK 3 — skipped

Verdict is (a), not (b). No production stale-`bot_response` / lock investigation in this pass.

---

## TASK 4 — verified against raw data

### a) Hallucinated scheme — **P0**

**Raw:** `request_id=3a31554f-419f-4549-9ba8-4b22f3367aee`  
- user: `Tell me about your schemes`  
- assistant: invents `*2. Kisna 1 Scheme*` with “Designed for convenient savings…” / “periodic contributions” while also listing Meri Roshni.

**Live reproduce (this session, GeneralAgent):** `Tell me about your schemes` returned Meri Roshni **and** framed **Digital Gold** as a co-equal “scheme” — still over-generating beyond KB-only Meri Roshni. Prod invent of “Kisna 1 Scheme” is confirmed in Mongo.

### b) Return → damage flow — **P0**

**Raw:** `How do I return the chain that I ordered?`  
- `message_traces.intent=returns_refund` (90%)  
- assistant content: `Sent flow - [damage_complaint]`  
Return intent correctly classified; **wrong flow** dispatched.

### c) Order id extraction — **P1**

**Raw:** `I had ordered a chain 3 years ago…` → `Order *ed* — click below…`

**Code:** [`order_tracking_agent.py:49-55`](../kisna_chatbot/processors/order_tracking_agent.py)  
Pattern `(?:order|track)\s*(?:id|#|:)?\s*([A-Za-z0-9-]+)` on that sentence matches **`ed`** (span inside `ordered`).

### d) Reply language thrashing — **P0** (most visible)

**Raw same-`request_id` pairs:**

| user script | assistant script | example |
|-------------|------------------|---------|
| Punjabi (Gurmukhi) | Gujarati | 2026-08-13T09:04:39Z |
| Punjabi | Gujarati | 2026-08-13T09:07:43Z |
| Gujarati | Hindi | 2026-08-13T09:14:15Z વીંટી → Hindi RTS prompt |
| Gujarati | English | 2026-08-13T09:21:39Z |

[`classifier.py:1182-1206`](../kisna_chatbot/processors/classifier.py) `_store_language`: with `language_override` set, **current message does not win**; docstring claims last-message wins but override short-circuits. Without override, LLM language label + script heuristic still mis-assigns PA↔GU. Empirically replies often follow a **stale / wrong stored language**, not the current message’s script.

### e) Budget parsing — **P1**

**Raw:**

- `35` (791, Aug19) → confirm `₹30,000 and ₹40,000` (band for 35k). Bare `35` does not parse via regex (`len(digits)<3` in wizard; `extract_entities("35")` empty) — value almost certainly from **LLM entity path** then `_snap_single_price_to_band(35000)→(30000,40000)` ([`entity_extractor.py:1123-1137`](../kisna_chatbot/processors/entity_extractor.py)). **Not ±10%**; website bucket snap.
- `50000` → Understood line `₹50,000–₹60,000` (correct bucket). Later recap once showed `₹50,000–₹50,000` (display/min=max bug) while search band was 50–60k. **±10% not applied**; bucket snap is.

### f) Store dead-end — **P1** (Mumbai), Udaipur different

**Raw corrected pairs:**

- `Do you have a store in Udaipur?` → pincode ask (whole reply). Not Bilkul.
- `Do you have a Store in Mumbai` / `…Mumbai?` (`23f7e160-…`, `197580d1-…`) → **entire** reply `Bilkul! Main ismein madad kar sakta hoon.` with `intent=store_info`. No second message lost on that `request_id`. Later Mumbai ask (`04d8d33e-…`) returned real store cards.

So the dead-end is a **store_info handler failure on some Mumbai utterances**, not a missing follow-up for Udaipur. Misattribution to Udaipur was likely the same off-by-one artifact.

---

## Revised severity list

### P0 (fix before merge)

1. **Hallucinated schemes** (Kisna 1 / non-KB schemes) — Task 4a  
2. **Return intent → `damage_complaint` flow** — Task 4b  
3. **Reply language thrashing** (PA/GU/HI/EN within session) — Task 4d  
4. **Chain → Necklace `categoryId`** (still on this branch tip)  
5. **`filter$fix$*` no handler** (still on this branch tip)  
6. **Gender omitted → missing `tagManagerId`** (still on this branch tip)

### P1

7. Order-id regex → `ed` from `ordered` — Task 4c  
8. Budget bare/`35`→35k silent; `50000–50000` recap display — Task 4e  
9. Store Mumbai → Bilkul dead-end — Task 4f  
10. Evil-eye / collection-only → category menu — A2 #4  
11. `વીંટી` → `category=earring` (gu-03) — A2 #6  
12. Sticky refine “above 15k” after rakhi resets menu — A2 #8  
13. Offers empty → `no_products` — A2 #3  
14. Carat/weight treated as wizard restart — A2 #5  

### P2 / behavioural (recover products)

15. RTS ladder `fallback_used` on band searches — A2 #1–2 (products often still shown)

---

## What was fixed in-repo this pass (analysis only + join)

- Transcript / replay **join** corrected (Task 2).  
- **No product-code fixes** for Tasks 1–4 bugs (report-first rule).  
- Task 3 not applicable.
