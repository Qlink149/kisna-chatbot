# Kisna WhatsApp chatbot — open defects handoff

**Repo**: `c:\Users\pc\Desktop\clara\chatbot\kisna-chatbot`
**Branch**: `v3-text-flow` — this is also what is deployed (`prod` is a
fast-forward of it). Current HEAD when this was written: `03a0c57`.
**Suite**: 1215 passing. Do not regress it.

You are being handed a list of defects that are **still live in production**.
Every one below was found by replaying real conversations through the real
pipeline, not by reading code. Your job: verify each one live, pinpoint the
actual mechanism, then plan fixes. Do not trust this document's suspected
causes — several earlier diagnoses in this project turned out to be wrong, and
the wrong ones are flagged so you don't repeat them.


---

## STATUS — resolved 2026-08-22

Every defect below was reproduced live before being touched, and the fixes are
verified live, multilingually. **Suite: 1247 passing** (was 1215).

| | Defect | Outcome |
|---|---|---|
| D1 | Refinement during the confirmation card destroys the search | **Fixed.** The recap now survives by default; only a message naming a different product replaces it. |
| D2 | "aur premium wale dikhao" returns cheaper items | **Fixed.** Plus a second bug this doc missed: "show me the second one" paginated instead of opening item #2. |
| D3 | A product question after a LIST re-prints the card | **Fixed** via a new `product_question` routing field. |
| D4 | Bare negation selects the refused metal | **Fixed** via a new `excluded_material` field. 6/6 Indic languages. |
| D5a | Unsupported metal at the material step is ignored | **Fixed.** Also: `pearl` was being *accepted* and advanced the funnel. |
| D5b | Pearl never flagged | **Fixed.** `pearl` was missing from the material enum. |
| D6 | Store lookup: a STATE gets a pincode prompt | **Fixed** — and it was wider than documented: native-script *cities* failed too. |
| D7 | Punjabi `ਮੁੰਦਰੀ` read as earring | **Fixed** (Gurmukhi category words added). Telugu half **did not reproduce**, 5/5 correct — dropped. |
| D8 | Hours questions get a pincode prompt | **Fixed.** `storeHours` was in every record and read by nothing. |
| D9 | Zero-result message quotes an unused filter | **Reframed.** The prefix was truthful; the real defect was three stacked preambles. Fixed. |
| D10 | Translation quality on long text | Open — model-bound, not code. Cost is settled (~$3/month). |
| D11 | Multi-intent silently halved | Open — deferred. |
| D12 | KB email / offers percentages | **Fixed** (offers now defer to the offers flow; `ecom@` for returns, `support@` for general). Cold start still open. |

**Four things this document got wrong**, corrected by live testing:

1. **D2**: it claims the entity extractor returns `price_direction="higher"`.
   It does not — `aur premium wale dikhao`, `aur mehnga dikhao` and
   `show me more premium ones` all returned `action="more"` with no direction.
   Native script *did* work. So it was an extractor failure on romanized text,
   not a classifier-contract wiring gap.
2. **D6**: "the city path is solid" is true only in Latin script. `मुंबई`,
   `સુરત` and `சென்னை` all got the pincode prompt.
3. **D7**: Telugu `పిన్ని` returned `gender: women` 5/5. Does not reproduce.
4. **D5b**: English `pearl ring dikhao` *was* flagged — by the regex, not the
   LLM. Only native script failed.

**Two scaffolding traps** that cost a cycle each, for whoever tests next:

- Build product fixtures with **more than 2 results**. `gold rings for women
  under 50000 ready to ship` returns exactly 2, so every pagination test hits
  "You have seen all 2 results!" and proves nothing. `under 200000` returns 12.
- Reaching the confirmation card needs **all five slots named** (category,
  material, gender, budget, fulfillment). Fewer slots enter the wizard instead,
  which is a different code path — that is why this document's Hindi and Tamil
  D1 claims are wrong.

The sections below are the ORIGINAL report, kept for the reproduction steps and
the transcripts. Read the table above first.

---

## 0. READ THIS FIRST — the principle that decides most of these fixes

This codebase keeps rediscovering one failure mode:

> Someone writes a Latin (or Latin + Devanagari) word list to detect something.
> It covers the languages they thought of. It silently breaks for the rest.
> Meanwhile **the LLM already understood the message and the code discarded it.**

Confirmed instances already fixed this way:
- kinship gender (`chachi` → the prompt enumerated allowed terms, and a regex
  validator threw away anything unlisted)
- budget declines (`null` meant BOTH "said any price" and "never mentioned
  money", so the concept was unrepresentable → phrase matching was the only
  tool left)
- an Odia budget ceiling inverted into a floor by a Latin-only heuristic

**So for every defect below, ask in this order:**
1. Does the LLM already emit the right answer? (test the extractor directly)
2. If yes — where does our code drop, override or fail to consult it?
3. Only if the LLM genuinely gets it wrong, change the prompt.
4. A deterministic list is acceptable **only** as a fallback behind the model,
   never as the primary reader. One exception is defensible: a **closed class**
   (negation particles are ~2 words per language and finite). Kinship terms,
   budget phrasings and range separators are **open classes** — lists cannot
   work there.

**This is a multilingual product.** A fix verified only in English is not a
fix. The nine languages that matter: English, Hindi (Devanagari + romanized
"Hinglish"), Gujarati, Marathi, Tamil, Telugu, Bengali, Punjabi, Kannada.
Malayalam and Odia also appear.

---

## 1. How to reproduce anything here

Use the live replay harness. It runs whole multi-turn conversations through the
**real** production pipeline (real classifier LLM, real agents, real Clara API,
real translation layer), skipping only the WhatsApp send and Mongo writes.

```bash
cd "c:/Users/pc/Desktop/clara/chatbot/kisna-chatbot"
./.venv_audit/Scripts/python.exe scripts/loadtest_harness.py <in.json> <out.json> --concurrency 6
./.venv_audit/Scripts/python.exe scripts/loadtest_view.py <out.json>          # compact, use this
./.venv_audit/Scripts/python.exe scripts/loadtest_view.py <out.json> --full   # untruncated
```

Input format:
```json
[{"id": "case_name",
  "note": "why this case exists",
  "turns": ["show me diamond rings for women under 50k",
            {"tap": "Either is fine"},
            {"tap": "Yes"},
            "aur premium wale dikhao"]}]
```
- bare string = typed text; `{"tap": "<button title>"}` or `{"tap": 0}` = a tap
- each conversation carries its own in-memory profile, so sessions are isolated
  and no real user's Mongo state is touched
- ~2–13s per turn, 6-wide. Use a generous Bash timeout (600000).

**Always run with `./.venv_audit/Scripts/python.exe`.** Importing the package
standalone hits a circular-import trap — `from kisna_chatbot.main import app`
must be the first project import in any ad-hoc script.

Full suite: `./.venv_audit/Scripts/python.exe -m pytest -q -p no:cacheprovider`
(~2.5 min). Individual test files fail in isolation because of that same
circular import — that is not a real failure, run the whole suite.

Prior context worth reading: `audit/heavy_loadtest_report.md` (the original
251-conversation QA report) and `git log --oneline -12` — the commit bodies
explain WHY each change was made and several record known residuals.

---

## 2. OPEN DEFECTS

### D1 — P0 — A refinement typed while the confirmation card is on screen destroys the whole search

**Symptom.** With the "Does this sound correct to you?" card showing, any
refinement the deterministic extractor cannot read as a slot value throws the
entire search away and restarts with a greeting.

```
1  show me gold rings for women under 50k ready to ship
   BOT "Understood 👍 I'll look in our catalogue for *gold rings for women
        under ₹50,000 ready to ship*. Does this sound correct to you?"
        [Yes, show me] [No, change it]
2  show me cheaper ones
   BOT "Hi! 👋 What are you looking for today? e.g. rings, earrings, necklaces…"
```
Category, material, gender, budget and fulfillment all gone.

**Reproduces 14/14**, deterministic, in English, Hinglish, Hindi
(`थोड़ा सस्ता दिखाओ`), Gujarati (`બીજું કંઈક બતાવો`), Bengali (`আরও দেখান`),
Tamil (`இன்னும் காட்டுங்கள்`). Also with "more", "aur premium wale dikhao",
"doosra wala dikhao".

**Still works (do not break):** "under 20k" after the same recap merges
correctly and re-recaps; tapping "Yes, show me" returns products.

**Suspected mechanism** (verify): `product_search_agent_v3.py:2749` calls
`_confirm_refinement_merge(pending, text)`. That helper (`:504`) runs the
deterministic `extract_entities` and returns `None` unless it finds one of
`_CONFIRM_REFINEMENT_SLOTS` (`:493` — min_price, max_price, gender,
material_type, karat, metal_colour, fulfillment). `action`,
`price_direction` and `product_reference` are not in that tuple and the Latin
extractor cannot produce them, so control falls to `clear_confirm_state();
return None` and the message routes as a brand-new search whose only entity is
`action:"more"`.

**Important correction — this is NOT a regression.** Before the P0-1 fix
(`f5188d8`) that block did `clear_confirm_state(); return None`
*unconditionally* for any non-yes/no reply. Verify with
`git show f5188d8^:kisna_chatbot/processors/product_search_agent_v3.py`. The
fix added a merge in front of it and covers slot-value refinements; it simply
never extended to these phrasings. Pre-existing, still open.

**Design note.** The right fix is probably not "add more slots to the tuple" —
that is the word-list trap again. Consider: a pending recap should survive
*any* message that does not name a different product, and pagination /
price-direction should apply to the recapped search rather than discarding it.

---

### D2 — P1 — "aur premium wale dikhao" (show pricier) returns CHEAPER items

**Symptom.** After a results list, asking for more premium pieces returns the
next page of the same band, which is cheaper.
Live: before ₹48,680 / ₹48,896 / ₹49,249 → after ₹47,777 / ₹48,053 / ₹48,635.
`thoda sasta dikhao` (cheaper) works correctly — only "higher" is broken.

**What is already true and verified:**
- the entity contract has `"price_direction": "lower|higher|null"`
- the extractor prompt maps `"premium wale"` → higher
  (`prompts/classifier_kisna.py`, the RELATIVE-price rule)
- a working consumer exists that shifts the band ~30%
  (`product_search_agent_v3.py`, `_entities_for_price_direction`)
- the **entity extractor** now returns `price_direction="higher"` for
  "show me more premium ones" and "aur premium wale dikhao"
- `_is_show_more_request` (`:1017`) already returns `False` when a price
  direction is set

**Why it still fails.** `_is_show_more_request` reads
`data["llm_extracted_entities"]`, which is the **CLASSIFIER's** output. The
classifier's contract deliberately excludes price_direction ("a separate
extractor owns them") and it keeps emitting `action:"more"` for these
phrasings. So the pagination gate at `:2137` fires and returns into
`_handle_show_more` long before the direction branch is reached.

**Failed approach — do not repeat.** Adding a rule to the classifier prompt
telling it that "more" + a price word is a refinement did **not** change its
output (still `action="more"`, 3 attempts). It was reverted.

**Likely real fix** (needs judgement): move `price_direction` into the
classifier's own output contract so the routing gate can see it, since the gate
is a routing decision. Weigh that against the reason it was split out.

---

### D3 — P1 — A product question after a LIST re-prints a card instead of answering

**Symptom.** After 3 products are shown, "iska price kya hai?" and
"isme kitne carat ka diamond hai" both return the same product card. The carat
question is never answered, and the card shows `14KT` (the GOLD purity), which
reads as if it were the diamond carat weight.

**What already works — build on it, don't rewrite it.**
`product_details_agent._answer_product_question(question, product, ...)` exists
and is good: it enumerates the product's real facts
(`_product_facts`) and answers from those only, in the customer's language,
and says plainly when a fact is missing. Verified in isolation:
- "iska price kya hai?" → "Iska price ₹49,249 hai, lekin yeh live gold rate ke
  saath vary hota hai."
- "isme kitne carat ka diamond hai" → "Mujhe is piece ke liye diamond carat ka
  pata nahi hai. Lekin yeh 14KT yellow gold mein hai…"
- a product record with no price omits price entirely rather than saying ₹0

It is wired into `_handle_product_info_followup` (`:688`) at the
resolved-single-product branch, and that branch works **when a single product
has been viewed**.

**Why it still fails on the common path.** After a LIST, the classifier sets
`product_reference: 1` for a bare "iska" (it treats "this one" as picking item
#1). `_handle_product_reference` (`:544`) → `_open_shown_product` (`:586`)
opens that product's card and returns, before the answerer is reached.

**Failed approach — do not repeat.** Tightening the classifier's
product_reference rule (so a bare "iska/isme" + a question is not a positional
pick) made Hindi `इसकी कीमत क्या है?` fall through to a **fresh search** — a
worse regression. It was reverted.

**Note.** Diamond carat weight genuinely is not in the Clara product record.
Available facts: title, price, karat, metal colour, size, shipping days, SKU,
chain-included, promo label. "I don't have that" is the correct answer, not a
bug to fix.

---

### D4 — P1 — Bare negation still selects the metal the customer refused

**Symptom.** "I don't want gold" style messages return `material_type: "gold"`.

Reproduces in **7 Indic languages**, 8/8:
```
मुझे सोने की नहीं, अंगूठी दिखाओ         → material_type "gold"
મને સોનાની નહીં, વીંટી બતાવો            → "gold"
আমার সোনা চাই না, আংটি দেখান           → "gold"
मला सोन्याची नको, अंगठी दाखवा           → "gold"
ਮੈਨੂੰ ਸੋਨੇ ਦੀ ਨਹੀਂ ਚਾਹੀਦੀ, ਅੰਗੂਠੀ ਦਿਖਾਓ  → "gold"
```
plus Tamil. **English and Hinglish are correct** ("I want something not in
gold", "gold nahi chahiye" → no material), 3/3.

**Scope correction.** Commit `780c383` documents this as residual in Tamil,
Marathi and Bengali only. It is wider — Hindi, Gujarati and Punjabi too, which
that commit claimed were fixed.

**Mechanism.** The LLM itself emits the refused metal (verify directly with
`extract_entities_with_llm`), and `apply_llm_evidence_gate`
(`entity_extractor.py:2026`) returns early for Indic script **by design** — its
docstring states multilingual understanding rides the prompt/LLM, not the Latin
regex. So there is no gate to correct. `_is_bare_material_negation`
(`:1691`) exists and works, but only where the Latin/Devanagari synonym map
found the metal in the first place.

**Constraint on any fix.** A blanket "negation particle present → drop the
material" rule would break `"मुझे सोने की अंगूठी चाहिए, हीरे की नहीं"`
(*I want gold, NOT diamond*), where the model is right and you would be
deleting a correct answer. This is why it was left open rather than patched.

---

### D5 — P1 — Unsupported materials: two separate holes

**D5a. Answering the MATERIAL QUESTION with an unsupported metal is silently
ignored.** The "we don't carry silver/platinum/pearl" note was added to
`start_wizard` only (`shopping_wizard.py:802` calling
`_unsupported_material_note` at `:818`). `advance_wizard` (`:1288`) has no
equivalent:
```
1  Do you have rings
2  [tap Female]  → "What type of rings are you interested in?" [Gold][Diamond][Gemstone]
3  silver        → "What type of rings are you interested in?" [Gold][Diamond][Gemstone]
```
Identical for Hindi `चांदी की`, Tamil `பிளாட்டினம்`, Gujarati `ચાંદીની`,
Telugu `వెండి`, English `platinum`. 8/8.
*The entry path works* — "silver ki ring dikhao" as an opening message does
show the note, with the metal names correctly pinned in English.

**D5b. Pearl is never flagged at all.** The LLM extractor returns
`material_type: "gemstone"` for bare `pearl` and for Gujarati `મોતી` (3/3
each), so `_CLARA_UNSUPPORTED_MATERIALS` (`entity_extractor.py:218`) never
matches and the funnel happily accepts pearl as a gemstone. This is a prompt /
contract issue, not a code one.

---

### D6 — P1 — Store lookup: a STATE name still gets a pincode prompt

```
"Do you have a store in Gujarat?"      → "Please share your 6-digit pincode…"
"…Maharashtra?" / "…Rajasthan?" / "kisna store in Uttar Pradesh"  → same
```
4/4. Kisna has 5 stores in Rajasthan and 2 in Gujarat, so the question is
answerable. This was in the original P1-8 scope and was explicitly deferred.

**Do not break the city path — it is solid and was hard-won.** Verified live:
misspelling ("Do you have a story udaipur") returns the real Udaipur store;
Goa honestly returns "No KISNA stores found near you"; Mumbai returns 4
branches; aliases (Bombay/Calcutta/Bengaluru/Gurgaon) resolve.

**Known API constraint** (already escalated to the Kisna team, not our bug):
`/api/v1/clara/stores` has **no city filter** — `?city=X` returns 400. `name=`
is a broad substring text search with both false positives and false negatives,
so city lookup is done client-side against `address.city.name` with a full-scan
fallback. Also: `pageSize` is silently ignored unless `pageNo` is passed too.

---

### D7 — P2 — Two kinship / vocabulary extraction errors

- **Telugu `పిన్ని` (aunt) → `gender: "kids"`**, 3 of 5 runs (the other 2 give
  "women"). It then sends an adult-woman search into the kids catalogue and
  hits "We don't currently offer *kids* gender in ring". Commit `7f0315d`
  names Telugu "pinni" as a success case; live it is wrong more often than not.
- **Punjabi `ਮੁੰਦਰੀ / ਮੁੰਦਰੀਆਂ` (ring) → `category: "earring"`**, 3/3. The user
  asks for rings and is offered/returned earrings.

All other kinship terms tested are correct (chachi, masi, bua, chacha, mami,
Gujarati ફોઈ, Tamil அத்தை, Bengali কাকিমা, Marathi आत्या, Kannada ಚಿಕ್ಕಮ್ಮ),
and parents/cousin/friend correctly still ask "Who is it for?".

---

### D8 — P2 — Intent routing sends two FAQ questions to the store locator

```
"What time do you open?"      → "Please share your 6-digit pincode…"
"Where is your head office?"  → "Please share your 6-digit pincode…"
```
2/2. Note `"office hours"`, `"What are your office hours?"`,
`"Aap kitne baje tak available ho?"` and `"आपका ऑफिस किस समय खुलता है?"` all
answer correctly with the real support hours — so this is a classifier routing
edge, not a missing fact. The KB explicitly says never to share the head-office
street address and to offer the store locator instead, so the head-office case
may be half-intended; the pincode prompt is still the wrong shape of reply.

---

### D9 — P2 — Zero-result message quotes a filter that was not used

```
"Show me gold rings of price 50000"
  → recap  "between ₹50,000 and ₹60,000"
  → "No pieces found in ₹50,000–₹60,000 right now — here are our closest picks ✨"
  → then shows ₹16,720 / ₹18,215 / ₹22,639 rings
  → last_search_filters shows min_price: null, max_price: null
```
The price filter was dropped before the API call but the prefix still quotes
it. Same for `above ₹100,000,000,000`. Related: a maang-tikka search where the
user taps **Gold** replies "I couldn't find gold maang tikkas…" and then shows
a **Diamond** one, with `last_search_filters.material_type` null.

The fallback template itself is fine — the bug is that the message describes
filters the search did not actually apply.

---

### D10 — P2 — Translation quality residue on long text

- Long FAQ answers are still garbled in **Tamil** and **Gujarati**:
  `"பொருப்பு படிவம், முன்னணி நிலை, மற்றும் அசலான கமர்சியுடன் இருக்க வேண்டும்"`,
  `"વસ્તુ બેઉંછી ન હોવા જોઈએ"` (`બેઉંછી` is not a word). Scripts are pure and
  no foreign script leaks — this is semantic quality on long text only.
- The pinned-phrase safety net leaves a bare English sentence at the end of
  Tamil/Gujarati return-policy answers: *"If you'd like to go ahead, just
  message me "I want to return my order"…"*. `reply_composer` returns the whole
  English source when a pinned phrase does not survive; Hindi translates the
  sentence and keeps only the quoted trigger in English, which is the intended
  shape.

Context: translation for `ta/te/bn/pa/kn/ml/gu/mr` is routed to a stronger
model via `AI_MODEL_COMPOSE_WEAK` (default `gpt-5.6-luna`); Hindi and all
romanized variants stay on the default.

**Cost is settled — do not treat it as an open question.** luna is
$0.20/M input, $1.20/M output, $0.02/M cache reads. Measured against real
token counts that is ~0.03 cents for a short canned line and ~0.08 cents
for a long FAQ answer; 10,000 translated replies a month is under $3, and
compose() caches by (lang, exact text) so most calls never reach the API.
`AI_MODEL_COMPOSE_WEAK` still lets you change the model without a deploy.

---

### D11 — P2 — Multi-intent is silently halved

`"show me gold rings and also tell me your nearest store in Mumbai"` → answers
the product half only; the store request is dropped with no acknowledgement.
The classifier returns exactly one intent and there is no secondary-intent
support anywhere. Explicitly deferred, not attempted.

---

### D12 — Operational, not a code bug

- **Cold start**: the first six concurrent turns of a fresh process each took
  **58–63 s**. Every other turn (of 403 measured) was median 4.7 s, p90 8.7 s,
  max 15.1 s. The first customer after a deploy waits a minute. Worth
  investigating whether a warm-up call at startup is appropriate.
- **KB email inconsistency**: `kisna_knowledge_base.py` line ~37 now says
  returns go to `ecom@kisna.com`, but line ~44 ("Track a return") and the
  general-support lines still say `support@kisna.com`, and the live
  return-policy answer serves `support@kisna.com` in both English and Tamil.
  Also `KISNA_SUPPORT_EMAIL` in the **prod environment** is what actually
  drives `general_agent_kisna.py` at runtime — a code change alone will not
  move it. Decide whether `support@` is retired, then make all of it consistent.
- **Offers percentages disagree**: the GeneralAgent says "up to 75% off diamond
  making charges and up to 50% on gold"; the offers builder says up to **100%**
  diamond / 50% gold. One of them is wrong.
- **Cosmetic**: the wizard material prompt bolds the interpolated category in
  some languages and not others (Hindi `*अंगूठियों*`, Kannada `*ಉಂಗುರಗಳಲ್ಲಿ*`,
  Marathi `*अंगठ्यांमध्ये*`; English/Tamil/Gujarati unbolded).

---

## 3. What is verified working — protect these

Measured live, do not regress:

- **Budget ceilings** hold in all 8 tested scripts (a stated "under ₹20,000"
  stays a ceiling; it used to invert into a floor). Also `under 10 carats` is
  not a ₹10 budget; `15–35k` (en dash), `15-35k`, `between 20k and 40k` parse.
- **Order tracking** never echoes a junk id — 9/9. `"track my order"` gives the
  generic CTA; a real id still surfaces.
- **Off-step funnel survival** (outside the D1 confirmation case) — 9/9 across
  languages. Genuine escapes (store, order, complaint, handoff, gold rate) still
  escape 5/5; genuine category switches still switch 3/3.
- **Kinship gender** 15/16 (D7 is the miss).
- **Pagination**: plain "more"/"aur dikhao" pages correctly with no repeats.
- **Markdown and script purity**: 0 markdown artifacts and 0 foreign-script
  characters across a 500-reply scan.
- **Offers and gold-rate replies are translated**, figures intact.
- **Handoff preamble** appeared 0 times in 500 replies.
- **Reply language does not drift** — an all-English chat stays English through
  slot answers; native-script chats are not demoted to romanized.
- **Prompt injection**: 9+ attempts refused, no system prompt / model name /
  tool names leaked.

---

## 4. What to deliver

For each defect you take on:
1. **Reproduce it live first** through the harness. If it does not reproduce,
   say so and drop it — several items in earlier reports did not survive
   verification, and two "failures" turned out to be bad test scaffolding.
2. **Pinpoint the mechanism** to a file and line you have actually read. State
   whether the LLM got it right and we discarded it, or the LLM got it wrong.
3. **Propose the fix at the right layer** per §0. Say explicitly which layer
   you are changing and why a list is or is not appropriate.
4. **Name the regression risk** and the specific case that would catch it.
5. Verify multilingually. English-only verification does not count.

Suggested order by user impact: **D1 → D4 → D5 → D2 → D3**, with D6–D12 as a
second pass.
