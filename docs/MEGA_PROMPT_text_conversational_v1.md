# KISNA WhatsApp Chatbot — Fully Text-Conversational, Multilingual (v1)
# END-TO-END IMPLEMENTATION MEGA PROMPT

> Paste this entire file as the task prompt for the implementing AI agent/IDE.
> It is self-contained: mission, architecture context, keep-list, five workstreams
> (A–E), context-hygiene rules, acceptance map, tests, and ground rules.

---

## 1. Mission

Convert the Kisna WhatsApp chatbot from a menu/button-driven state machine into a
**fully AI-driven, multilingual, human-feeling conversational assistant** — like
chatting with a knowledgeable Kisna jewellery salesperson on WhatsApp.

Client requirements (verbatim intent):

- Greet customers **by their name** (where available) for a personalized experience.
- **Remove the main menu/dropdown** and all predefined menu options — fully
  conversational, natural-language interface.
- Understand and act on natural language queries such as:
  - "Show me some lightweight rings."
  - "Show me rings under ₹30,000." / "products under ₹XX" / "necklaces under ₹XX"
  - Any product/category search by budget, style, or preference.
- "Track my order" / "My order status" → keep the CURRENT behavior (send the
  tracking URL). Phone-number-based order lookup will come later — do NOT build it.
- "Kisna store near me" / "store near me" → ask for PIN code in text, then show
  nearest stores.
- "I want to raise a complaint" → send the complaint **form** (the reason dropdown
  lives inside the WhatsApp Flow form — that stays).
- "I want to talk to an agent" → send the **callback form** (date/time slot).
- "Can you schedule a video call?" → send the **video-call form** (date/time slot).
- "Today's gold rate" → show the latest gold rate chart.
- "Today's offers" / "Current offers" → show all active offers/promotions.
- **Multilingual**: understand and reply in the user's language (English, Hindi,
  Hinglish; best effort otherwise).

The ONLY interactive elements that may remain in outbound messages:

1. **WhatsApp Flow forms** (data collection): damage/complaint form,
   callback-request form, video-call form, store-visit datetime form, site-visit
   form.
2. **CTA URL link buttons**: "Buy on KISNA" on product images, "See Collection",
   order-tracking URL button. These are links, not navigation.

Everything else the user does by typing naturally, in their own language.

**Branch**: work on `v0-text-flow-only` (do NOT touch `main`). Phase 1 is already
done on this branch: the main WhatsApp menu list was removed from greetings and
fallbacks and replaced by a short text help prompt. This prompt covers everything
remaining.

---

## 2. Architecture context (read before coding)

- FastAPI app, entry `kisna_chatbot/main.py`. Webhook → `UserRegistration` →
  `InitialPipeline` (`UserRegistration, Classifier, ServiceList`) → per-service
  pipeline selected from `user_profile["service_selected"]` (see
  `kisna_chatbot/pipelines/inference_pipeline.py`) → `ResponseManager`
  (`kisna_chatbot/processors/response_manager.py`) sends via Gupshup.
- `Classifier` (`kisna_chatbot/processors/classifier.py`): regex shortcuts + LLM
  intent classifier (`kisna_chatbot/prompts/classifier_kisna.py`) returning JSON
  `{intent, confidence, entities}`. Entities sanitized by
  `_sanitize_llm_entities`. Regex "sticky session" gates in `Classifier.should_run`
  skip the LLM for in-session refinements (cost control).
- Product search: `kisna_chatbot/processors/product_search_agent_v3.py`. The GOOD
  path already exists: `_build_search_success_response()` sends intro text + up to
  3 product images with caption + "Buy on KISNA" CTA + a "See Collection" CTA.
  **Keep this presentation exactly as is.**
- `GeneralAgent` (`kisna_chatbot/processors/general_agent.py`): LLM with KB
  grounding (KISNA_KNOWLEDGE_BASE prompt injection) for FAQ/brand questions.
- Entity extraction: `kisna_chatbot/processors/entity_extractor.py` — already
  parses budgets ("under 25k", "15-35k", "1 lakh"), categories, materials, karat,
  Hinglish forms, pincodes, cities.
- User profile persisted in Mongo; `user_profile["username"]` /
  `user_profile["whatsapp_username"]` hold the customer's name.
- Session state keys that matter: `service_selected`, `last_search_filters`,
  `last_search_products`, `last_viewed_product`, `pending_clarification`,
  `pending_flow_switch`, `awaiting_store_pincode`, `callback_capture_step`,
  `last_search_at`.
- Chat history for LLM context: `format_recent_history_str(user_profile, 8)`.

---

## 3. Explicit KEEP list (do not change behavior)

- Product results presentation (`_build_search_success_response`,
  `build_product_image_with_cta_message`) — images + captions + CTA links.
- Order tracking: current behavior (sends the tracking URL). No phone-based lookup.
- Store locator conversational shape: "store near me" → bot asks for PIN code in
  text → shows nearest stores (`awaiting_store_pincode` + `ad_flow_agent.py`).
- Gold rate (`gold_rate_handler.py`) and Offers (`offers_agent.py`) responses.
- All WhatsApp Flow forms listed in §1 and `flow_data_exchange.py`.
- Human-takeover, inbound dedupe, rate limiting, typing indicator, and the
  24h-window welcome template logic in `response_manager.py`.
- `ResponseManager` keeps its `list`/`quickreply` handlers REGISTERED (legacy
  interactive messages already in users' chats can still be tapped and their
  postbacks must still parse) — but after this change NOTHING new may emit
  `{"type": "list"}` or `{"type": "quickreply"}`.
- Inbound `button_reply` / `list_reply` PARSING everywhere (transition period).

---

## 4. Workstream A — Remove every remaining menu / button sender

Replace each with conversational text (composed via Workstream C's reply layer).

### A1. `processors/product_search_agent_v3.py`
- Remove sends of:
  - `build_explore_products_list_with_prompt()` (~lines 1655, 1671)
  - `build_other_jewellery_list()` (~1693)
  - `build_main_category_list()` (~1696, 1832, 1898)
  - `build_pref_step1_material_list()` (~1719)
  - `build_pref_step2_type_list()` (~1734)
- Remove the `budget_custom_input` flow sends (~1729, 1743, 1751) and the
  `awaiting_custom_budget` path → ask for budget in plain text instead:
  "What budget do you have in mind? e.g. under 25k, 15–35k, around 1 lakh" and
  parse the reply with the existing entity extractor.
- Vague queries ("show me jewellery", "I want something nice") → conversational
  **slot-filling**: ONE natural combined question ("Lovely! Are you thinking
  rings, earrings, necklaces…? And any budget in mind?"). The next user message
  goes through the normal classifier/entity-extractor path. Never ask more than
  one clarifying question in a row — if still vague after one clarification, run
  the existing default/bestsellers search with a soft note.

### A2. `processors/service_list.py`
- `_build_help_center_list` → delete the send. Route help/support messages
  directly: complaint intent → complaint form; callback → callback form; video
  call → video-call form; generic "talk to an agent" → **callback form** (per
  client: agent assistance = pick a callback slot). Update
  `support_handler.py` (quickreply ~line 64) accordingly.
- `build_clarification_bot_response` → plain-text clarifying question, no
  buttons. Keep `pending_clarification` (classifier already re-feeds the answer
  with context on the next turn).
- `build_flow_switch_bot_response` + `_maybe_prompt_flow_switch` (in
  `classifier.py`) → REMOVE the confirmation entirely. When intent changes with
  confidence ≥ 0.5, switch silently and act, with a one-line natural
  acknowledgement ("Sure — let's look at your order."). Delete
  `pending_flow_switch` handling after migrating.
- `build_acknowledgement_bot_response` → short warm text ("Happy to help! Ask me
  anything else — jewellery, offers, your order… 😊"), no buttons.
- Rating quickreply (~line 1130) → "How was your experience? Reply with a rating
  from 1 to 5." Set `awaiting_rating` flag; parse a digit 1–5 (or words like
  "five"/"paanch") from the next message; clear the flag after one turn or on any
  non-rating message (treat that message normally).
- Complaint-entry quickreply (~line 179 area) → send the damage/complaint FORM
  directly when complaint intent is detected.
- `is_menu_request` ("menu", "options", "help") → return the text capability
  summary (no list).

### A3. `processors/product_details_agent.py` (~lines 206–230)
- Delete the three quickreply messages (See Similar / Find a Store / Browse
  More). Append ONE text line to the detail response: "You can ask me for
  *similar designs*, a *store near you*, or keep browsing 💎".
- Ensure these phrases route correctly as text: "similar" / "is jaisa aur" →
  similar-products search seeded from `last_viewed_product`; store phrases
  already route via classifier regexes.

### A4. `processors/non_text_handler.py` (~line 42)
- Quickreply → plain text: "I can't read images or audio yet — just tell me in
  words what you're looking for 🙂".

### A5. Sweep check
After all edits, run:

```
grep -rn '"type": "quickreply"\|"type": "list"' kisna_chatbot/processors kisna_chatbot/utils
```

There must be ZERO senders reachable from live code paths. The legacy
interactive-list builder in `utils/product_formatter.py` may remain only if fully
unreachable — otherwise delete it. Paste the grep output in your final summary.

---

## 5. Workstream B — Personalized, human greeting

- `build_greeting_welcome_bot_responses` in `service_list.py`: greet by name —
  `user_profile.get("username") or user_profile.get("whatsapp_username")`; omit
  the name cleanly if missing (never "Hi None"). Guard against garbage names
  (purely numeric, > 30 chars, contains "@") — fall back to no-name greeting.
- First-time greeting: warm welcome + one-line capability hint written as
  conversation, not a list dump.
- Returning user (existing `is_new_session` logic): shorter "Welcome back,
  {name}!" and, if `last_search_filters` is fresh (< 2h), optionally offer to
  continue ("Want to keep looking at gold rings under ₹50k?").
- Greeting text goes through the reply composer (Workstream C) so it mirrors the
  user's language.

---

## 6. Workstream C — Multilingual + LLM reply layer (the "feels human" core)

### C1. Language detection — zero extra LLM calls
- Extend the classifier prompt (`prompts/classifier_kisna.py`) to also return
  `"language"` in its JSON — one of `"en"`, `"hi"` (Devanagari), `"hi-Latn"`
  (Hinglish), or another short code for anything else.
- Parse it in `_parse_classifier_json`, sanitize against an allowlist, store
  rolling state in `user_profile["language"]` (update on every LLM-classified
  message; for messages that skip the LLM classifier — regex shortcuts, sticky
  sessions — reuse the stored value; default `"en"`).

### C2. Reply composer — new module `kisna_chatbot/utils/reply_composer.py`
```python
async def compose(template_key: str, text: str, *, language: str, name: str | None = None) -> str
```
- `language == "en"` → return `text` unchanged (zero cost for the majority).
- Otherwise → one small LLM call: "Rewrite this WhatsApp message in <language>,
  warm and natural, keep emojis, keep prices/URLs/product names/numbers EXACTLY
  unchanged."
- Cache results in-process keyed by `(template_key, language)` for static
  templates; skip caching for dynamic product/gold-rate/offer text.
- On any composer failure, fall back to the English text — never block a reply.
- Route through it: greetings, clarifications, acknowledgements, slot-fill
  questions, error/fallback texts, store-pincode prompt, rating prompt, product
  search intros, detail hint lines.
- Do NOT translate: form flows (stay English), CTA button titles, product
  names/prices, URLs.

### C3. Agent prompts
- `GeneralAgent` and product prompts: add "Reply in the user's language (match
  their last message — English, Hindi, or Hinglish). Keep product names and
  prices as-is."

### C4. Tone pass
- Rewrite every remaining hardcoded user-facing string in processors to be warm,
  concise, salesperson-like. No "Please select from the menu", no robotic
  phrasing. WhatsApp-appropriate length: 2–4 lines typical.

---

## 7. Workstream D — Context hygiene (anti-context-bleeding)

Implement as explicit, tested rules:

1. **Universal session TTL**: generalize the existing 2h product-search expiry
   (`_maybe_expire_product_search_session`) into a helper that clears
   `service_selected`, `pending_clarification`, `awaiting_store_pincode`,
   `awaiting_rating`, `callback_capture_step` when the last inbound message is
   > 2h old (store/refresh `last_message_at` in the profile). A user returning
   after a day starts clean (greeting flow), never resumes a stale wizard state.
2. **Intent-change cleanup**: when the classifier routes to a service DIFFERENT
   from the current one, clear the other service's transient flags (moving to
   complaint clears `awaiting_store_pincode`; moving to store lookup clears
   `pending_clarification`; etc.). Centralize in one
   `reset_transient_state(user_profile, keep=...)` helper called from
   `_apply_intent_routing`.
3. **Entity carry-over rules** (product search):
   - Price-only refinement ("under 40k") inherits category/material from
     `last_search_filters` (already works — keep).
   - NEW category ("show me necklaces") drops previous price/material filters
     UNLESS the message restates them. Verify the current merge logic in
     `product_search_agent_v3.py` and fix if it leaks old budget into a fresh
     category search.
   - `last_viewed_product` is cleared on any NEW search (not just detail views),
     so "what's the price?" after a new search never answers about a stale
     product.
4. **One-shot flags**: `pending_clarification` and `awaiting_rating` are consumed
   or discarded after exactly one turn; they must never cause the bot to
   misinterpret an unrelated next message.
5. **Chat history**: keep the 8-message window for classifier/general agent (do
   not grow it). History passed to LLMs contains only user/bot text — never
   internal trace/system strings.
6. **Classifier gating**: keep the cheap sticky-session regex gates in
   `Classifier.should_run` (cost control) but verify every sticky state has a
   working text escape (offers / order / complaint / human / store / FAQ regexes
   exist — add tests proving each escape works).

---

## 8. Workstream E — Fallbacks (never dead-end, never menu)

- `main.py` "pipeline completed without bot_response" fallback (~line 579):
  route to `GeneralAgent` (one LLM attempt) instead of the help text; if that
  also fails, send a short localized apology.
- Classifier JSON-error/exception fallbacks (`classifier.py` ~lines 1400–1417):
  localized "Sorry, I didn't catch that — could you say it another way?" instead
  of the help prompt; never crash the turn.
- Unknown/unsupported requests → `GeneralAgent` answers from KB or politely
  redirects to what Kisna can do.
- Off-topic chit-chat ("how are you") → `GeneralAgent` replies warmly in 1–2
  lines and steers back gently to jewellery/service topics.

---

## 9. Acceptance map (must all pass — manual + automated where mockable)

| # | User says (any language) | Expected behavior |
|---|---|---|
| 1 | "Hi" (known user) | "Hi {name}! 👋 …" text only, no list |
| 2 | "Hi" (name unavailable) | Clean greeting without a name, never "Hi None" |
| 3 | "Show me some lightweight rings" | Ring search (style hint), images + CTA |
| 4 | "Show me rings under ₹30,000" | Filtered search, images + CTA |
| 5 | "necklaces under 50k" after a ring conversation | Necklace search; ring budget NOT silently carried — budget comes from this message |
| 6 | "Track my order" / "order status" | Current tracking-URL response |
| 7 | "Kisna store near me" | Text asking for PIN code → stores on PIN reply |
| 8 | "I want to raise a complaint" | Complaint FORM (reason dropdown inside form) |
| 9 | "I want to talk to an agent" | Callback FORM (date/time slot) |
| 10 | "Can you schedule a video call?" | Video-call FORM |
| 11 | "Aaj ka gold rate?" | Gold-rate chart; intro line in Hindi/Hinglish |
| 12 | "Today's offers" | Offers response |
| 13 | "thanks" | Short warm text, no buttons |
| 14 | Gibberish "asdfgh" | ONE gentle text clarification, then bestsellers/general if still unclear |
| 15 | "sone ki anguthi 20 hazar tak" | Hindi understood → ring search under ₹20,000, Hindi reply |
| 16 | "show me jewellery" (vague) | ONE combined slot-fill question (category + budget), free-text answer works |
| 17 | "similar" after viewing a product | Similar-products search seeded from `last_viewed_product` |
| 18 | Returns after 3 days, says "yes" | Treated as fresh session — no stale wizard resume |

---

## 10. Tests

- Update/rewrite: `tests/test_vague_browse_menu.py`,
  `tests/test_classifier_clarification.py`, `tests/test_help_center.py`,
  `tests/test_menu_greeting.py`, `tests/test_non_text_inbound.py`, plus any test
  asserting `"type": "quickreply"` / `"type": "list"` in outputs.
- Add new tests for:
  - Greeting by name: present / missing / garbage name.
  - Slot-fill question for vague query; free-text answer completes the search.
  - Budget text parsing replacing the budget flow ("under 25k", "15-35k",
    "1 lakh", "₹20000 tak").
  - Silent flow-switch (no confirmation buttons, state switches, transient flags
    cleared).
  - Universal session TTL reset.
  - Entity carry-over rules — all three cases in §7.3.
  - `language` field parsing, allowlist sanitization, composer cache hit,
    composer failure → English fallback.
  - Every sticky-session text escape in §7.6.
  - Acceptance-map rows that can run offline (mock the LLM with canned
    classifier JSON — follow existing test patterns).
- The ENTIRE suite must pass. Do not weaken assertions to make tests pass —
  change tests only to reflect the new intended behavior.

---

## 11. Ground rules

- Branch `v0-text-flow-only`; do not touch `main`.
- Small, reviewable commits per workstream (A, B, C, D, E) with descriptive
  messages.
- No new heavyweight dependencies. Language detection must NOT add an extra LLM
  call.
- Never let an exception surface to the user; every error path sends a friendly
  localized text.
- Keep the deterministic pipeline routing (classifier → service pipelines). This
  is a hybrid design on purpose: deterministic routing + LLM-composed replies.
- English replies must bypass the composer LLM call entirely (cost control).
- After Workstream A, run the grep sweep (§4 A5) and include its output in the
  final summary.
- Final summary must list: every file changed, every removed menu/button, every
  new profile key (`language`, `awaiting_rating`, `last_message_at`, …), and any
  behavior you were unsure about.

---

## 12. Known cost/latency notes (for the record)

- Multilingual mirroring adds one small LLM call per canned reply for
  non-English users only (cached for static templates). English users: zero
  added cost.
- Classifier sticky-session gates are retained so per-message LLM volume stays
  roughly the same as today.
- The riskiest area is §7.3 entity carry-over — write the tests FIRST for those
  three rules, then fix the merge logic against them.