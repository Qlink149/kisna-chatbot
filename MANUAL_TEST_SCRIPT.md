# KIA Manual Test Script (WhatsApp)

**How to use:**
1. Paste each message ONE BY ONE into WhatsApp, in the order given (order matters — most tests depend on prior state).
2. For each message note: the bot's reply (first line is enough), whether **images / buttons / forms** arrived, and anything weird.
3. Where a step says **RESET**, send `hi` first to clear state before continuing.
4. `[TAP X]` means tap the quick-reply button, do NOT type it.
5. After finishing, send back the "message → response" list and I'll analyze failures.

**Important — the bot is wizard-first.** A vague shopping message does NOT return products; it starts a guided funnel. Products only appear once all 5 slots are known. The 5 slots, in order:

`category → gender → material → budget → fulfillment`

**Reference — what a correct wizard turn looks like:**

| Slot | Bot asks (English source) | Buttons |
|---|---|---|
| category | "What are you looking for today? e.g. rings, earrings, necklaces…" | none (free text) |
| gender | "Who is it for? (or type *anyone*)" | `Female` `Male` `Kids` |
| material | "What type of jewellery are you interested in?" | `Gold` `Diamond` `Gemstone` |
| budget | "What's your budget? … (or say *no specific budget*)" | none (free text) |
| fulfillment | "ready-to-ship … or made-to-order?" | `Ready to ship` `Made to order` `Either is fine` |

Every question except the first (category) accepts "no preference" — `skip`, `koi bhi`, `anyone`, `no specific budget`, `either`. That must move the funnel FORWARD one step, never restart it and never bail out to a generic browse.

**Reference — what a correct RESULTS turn looks like (all 4, in this order):**
1. one intro/summary line (e.g. "Perfect! Let me show you the best diamond rings under ₹30,000.")
2. **exactly 3 product cards**, each ONE bubble = photo + `*Title*` + price + material line + shipping line + inline **`Buy on KISNA`** button
3. no separate "Tap below to buy on kisna.com" text bubble (that's the old broken split — FAIL it)
4. last message = **`See Collection`** CTA

---

## SECTION A — Greeting, menu, session reset

| # | Paste this | Expected |
|---|---|---|
| A1 | `hi` | KIA welcome/intro + menu. Fresh session (no leftover filters). |
| A2 | `menu` | Main menu options. |
| A3 | `kya kya kar sakte ho` | Capabilities list **in Hinglish** (language must mirror). |
| A4 | `namaste` | Greeting only — NOT a product search. |
| A5 | `Tamara kem che` | Gujarati greeting → greeting reply, not search. |

---

## SECTION B — Wizard happy path (the core flow — CRITICAL)

**RESET: `hi`**

| # | Paste this | Expected |
|---|---|---|
| B1 | `rings` | Asks **gender** with buttons `Female` `Male` `Kids`. Must NOT dump products yet. |
| B2 | `[TAP Female]` | Asks **material** with buttons `Gold` `Diamond` `Gemstone`. |
| B3 | `[TAP Diamond]` | Asks **budget** as free text ("under 25k, 15–35k, around 1 lakh"). |
| B4 | `under 30k` | Asks **fulfillment** with buttons `Ready to ship` `Made to order`. |
| B5 | `[TAP Ready to ship]` | Summary line + **3 cards with images** + `See Collection` last. Filters must match: diamond rings, women, ≤30k, ready-to-ship. |

**Check on B5:** open one card's price and the `Buy on KISNA` link — title/price on WhatsApp must match the website page. Any invented gram/carat text = FAIL.

---

## SECTION B2 — Wizard, typed answers instead of buttons

**RESET: `hi`**

| # | Paste this | Expected |
|---|---|---|
| B6 | `earrings dikhao` | Gender question. |
| B7 | `for my wife` | Accepted as gender=women → material question (NOT re-asking gender). |
| B8 | `sona` | Accepted as gold → budget question. |
| B9 | `20000` | Accepted (bare number) → fulfillment question. |
| B10 | `ready to ship` | Results: gold earrings for women ~20k, ready-to-ship. |

---

## SECTION B3 — Wizard multi-slot fill (one message answers several slots)

**RESET: `hi`**

| # | Paste this | Expected |
|---|---|---|
| B11 | `necklace` | Gender question. |
| B12 | `for men gold` | Fills gender AND material in one go → jumps straight to **budget** (skipping material question). |
| B13 | `50k to 1 lakh` | Fulfillment question. Range parsed as 50,000–1,00,000. |
| B14 | `[TAP Made to order]` | Results + line like "Any of these can be made to order for you ✨". |

---

## SECTION C — Smart-skip (complete query must NOT start the wizard)

**RESET: `hi` before each.**

| # | Paste this | Expected |
|---|---|---|
| C1 | `ready to ship diamond rings under 20k for her` | **Straight to results.** Zero wizard questions. All 5 filters applied. |
| C2 | `hi` then `gold necklace for women above 50000 made to order` | Straight to results, MTO. |
| C3 | `hi` then `sab dikhao` | Browse-all → results directly, no wizard. |
| C4 | `hi` then `show me everything` | Same as C3. |
| C5 | `hi` then `show me diamond rings` | Wizard (gender question) — gender/budget/fulfillment are missing. EXPECTED, not a bug. |
| C6 | `hi` then `diamond rings for her under 30k` | Asks **only fulfillment** (one question), then results. Any other question = smart-skip broken. |

---

## SECTION D — Wizard escape & sticky-state hygiene (recent fix — CRITICAL)

Each row: start fresh with `hi`, send `rings`, tap `Female` (wizard now sits on **material**), THEN send the test message.

| # | Mid-wizard message | Expected |
|---|---|---|
| D1 | `Connect me with agent` | Live agent handoff (or offline + callback form). Wizard cleared. NEVER "Mujhe samajh nahi aaya". |
| D2 | `call me back` | Callback form (NOT handoff). |
| D3 | `aaj ka gold rate kya hai` | Live gold rates. |
| D4 | `store near me` | Store/pincode ask. |
| D5 | `track my order` | Order tracking flow. |
| D6 | `koi offer hai?` | Offers. |
| D7 | `मुझे किसी इंसान से बात करनी है` | Handoff (Devanagari). |
| D8 | `koi bhi` | Read as "no material preference" → moves to the BUDGET question. Must not bail out or re-ask. |
| D9 | `browse all` | This one really does bail out — but it must KEEP Female + the category, never restart at "What are you looking for today?". |
| D10 | Fresh: `hi`, `rings`, tap `Female`, tap `Gold`, then `show me rings under 30k` | Carryover: must NOT re-ask gender/material; goes to results with women + gold + ≤30k. |

**FAIL signatures here:** the clarification line, or the wizard continuing to ask its next slot as if the escape was a slot answer.

## SECTION D2 — Wizard slot integrity (adversarial)

| # | Setup → then send | Expected |
|---|---|---|
| D11 | `hi`, `rings`, tap `Female` → `recommend something nice` | Gender must STAY women (the word "recommend" contains "men" — must not flip to male). Re-asks material or moves on. |
| D12 | `hi`, `rings`, tap `Female`, tap `Gold` → `hmm` | Budget question re-asked (reask), not a crash or a wrong search. |
| D13 | `hi`, `rings`, tap `Female`, tap `Gold`, `under 30k` → `in stock please` | Read as ready-to-ship → results. |
| D14 | `hi`, `necklace`, tap `Male` → `for my wife gold` | Gender flips to women only because this message restates it; material=gold → budget question. |
| D15 | `hi`, `rings` → `anyone` | "No preference" → material question. Results at the end must not be gender-filtered. |
| D16 | `hi`, `rings` → `koi bhi` | Same as D15 — on a filter question this is an answer, not an escape. |
| D17 | `hi`, `rings`, tap `Female`, tap `Gold` → `No specific budget` | Moves to the fulfillment question. Must NOT re-ask the budget (this was the reported bug). |
| D18 | Continue D17 → tap `Either is fine` | Results appear with no availability filter — 3 cards + `See Collection`. |
| D19 | `hi`, `rings` → `anyone` → `skip` → `no specific budget` → `either` | Full funnel answered entirely with "no preference": results still arrive, and the summary line must not say "any rings". |

---

## SECTION E — Wizard in native scripts (MULTILINGUAL CRITICAL)

**RESET: `hi`** — buttons stay English even when questions are localized; that's expected.

| # | Paste this | Expected |
|---|---|---|
| E1 | `मुझे अंगूठी चाहिए` | Gender question **in Hindi**. |
| E2 | `[TAP Female]` | Material question in Hindi. |
| E3 | `डायमंड` | Accepted as diamond → budget question. NOT re-asked, NOT sent to a text-only answer. |
| E4 | `५० हज़ार से कम` | Fulfillment question. Budget parsed as ≤50,000. |
| E5 | `[TAP Ready to ship]` | Results, Hindi intro, real product cards (no invented names/weights). |
| E6 | `hi` then `મારે બુટ્ટી જોઈએ છે` | Gujarati earrings → gender question in Gujarati. |
| E7 | `[TAP Female]` then `સોનું` | Gold accepted → budget question. |
| E8 | `૧૦,૦૦૦ થી ૩૦,૦૦૦` | Range 10k–30k parsed (BOTH bounds) → fulfillment question. |
| E9 | `hi` then `Mala ek ring pahije` | Marathi "I want a ring" → RING wizard (NOT necklace/mala). |

---

## SECTION F — After results: pagination & refinement

**Setup: `hi` → `ready to ship diamond rings under 50k for her` (smart-skip → results).**

| # | Paste this | Expected |
|---|---|---|
| F1 | `show more` | 3 NEW products, no repeats, **no intro line** repeated. |
| F2 | `aur dikhao` | 3 more. When exhausted: "You have seen all N results" + website link (not an error). |
| F3 | `under 20k` | Same diamond rings for her, now ≤20k. Category/material must NOT reset. |
| F4 | `thoda sasta dikhao` | Cheaper band, with a line like "Showing options under ₹X". No invented numbers. |
| F5 | `aur mehnga dikhao` | Higher band. |
| F6 | `for men` | Same search, gender flips to men. |
| F7 | `necklace above 10k` | Category switches to NECKLACE, >10k. Old material must not silently leak. |
| F8 | `इसका price बहुत ज्यादा है` | Cheaper options, reply in HINDI (language switch mid-flow). |
| F9 | `ok in English please` | Switches back to English. |

---

## SECTION G — After results: picking a product

**Setup: `hi` → `ready to ship gold rings under 50k for her` → wait for 3 cards.**

| # | Paste this | Expected |
|---|---|---|
| G1 | `the second one` | Card/details of item **#2** from the 3 shown. |
| G2 | Copy-paste the exact title of card #3 (e.g. `Twist Ring`) | Opens THAT product's card. Must NOT restart the wizard with "Who is it for?". |
| G3 | `बीच वाला कितने का है` | Price of the middle shown item, Hindi reply. |
| G4 | `which is cheaper?` | Compares the shown items by real prices. |
| G5 | `sabse sasta dikhao` | Cheapest of the shown items. |
| G6 | `isi jaisa aur dikhao` | Similar pieces to the last viewed product. |
| G7 | `does it come with a chain?` | Answer grounded in that product (chain-not-included note if applicable) — no generic essay. |
| G8 | `no that's not what I meant` | Apology + asks what they want. Fresh start, NOT the same results again. |

**FAIL signature:** any gram weight, carat, SKU or variant the card/website doesn't show = hallucination.

---

## SECTION H — Zero results & relaxation quality

**RESET: `hi` before each.** Each query below is deliberately *complete* (category + gender + material + budget + fulfillment) so it smart-skips the wizard and actually hits the API — that's the only way to see fallback behaviour.

| # | Paste this | Expected |
|---|---|---|
| H1 | `ready to ship gold rings for her between 40k and 50k` | Exact match, OR fallback that KEEPS GOLD (ready-to-ship is dropped FIRST, then price). Diamond rings appearing = FAIL. |
| H2 | `hi` then `ready to ship diamond ring for her under 2000` | "No pieces found under ₹2,000 … closest picks ✨" + real products. Never an empty reply. |
| H3 | `hi` then `ready to ship platinum ring for her under 50k` | "We specialise in gold, diamond, and gemstone…" pivot + real alternatives. |
| H4 | `hi` then `ready to ship gold anklets for her under 30k` | Graceful "no specific filter for that" + collection, no crash. |
| H5 | `hi` then `made to order gold ring for her under 50k` | MTO results + "Any of these can be made to order for you ✨". |
| H6 | `hi` then `custom ring banwana hai` | Design-expert handoff (NOT a catalog search, NOT the wizard). |
| H7 | `hi` then `ready to ship gold rings for her under 300` | Nothing exists that cheap → closest picks with a budget note, or the zero-result message with kisna.com link. No blank/error reply. |

---

## SECTION I — Human handoff / callback / video call (no wizard involved)

**RESET: `hi` before each row.**

| # | Paste this | Expected |
|---|---|---|
| I1 | `Connect me with agent` | Handoff (open hours) or offline msg + callback form. |
| I2 | `Connect me with a human` | Handoff. |
| I3 | `I need a real person` | Handoff. |
| I4 | `transfer me to support` | Handoff. |
| I5 | `customer care` | Handoff. |
| I6 | `agent se baat karni hai` | Handoff (Hinglish). |
| I7 | `call me back` | Callback form (NOT handoff). |
| I8 | `please call me` | Callback form. |
| I9 | `mujhe call karo` | Callback form. |
| I10 | `video call schedule karna hai` | Video call flow (not callback, not handoff). |

---

## SECTION J — Store locator

**RESET: `hi`**

| # | Paste this | Expected |
|---|---|---|
| J1 | `store near me` then `400001` | Store list for Mumbai 400001. |
| J2 | `hi` then `store near me` then `show me gold rings` | Escapes store wait → ring wizard/results. NOT "invalid pincode". |
| J3 | `hi` then `560001` (bare pincode) | Store lookup for that pincode. |

---

## SECTION K — Orders, returns, complaints

**RESET: `hi` before each.**

| # | Paste this | Expected |
|---|---|---|
| K1 | `track my order` | Order tracking flow. |
| K2 | `mera order kahan hai` | Order tracking. |
| K3 | `return karna hai` | Returns ACTION flow. |
| K4 | `return policy kya hai` | Policy ANSWER (KB) — not the flow. |
| K5 | `mera order damage aa gaya` | Complaint flow. |
| K6 | `order cancel karna hai` | Human handoff (bot can't cancel). |
| K7 | `मुझे रिटर्न करना है` | Returns flow, Hindi reply. |

---

## SECTION L — Offers, rates, schemes, FAQ

**RESET: `hi`**

| # | Paste this | Expected |
|---|---|---|
| L1 | `koi offer hai?` | Current offers. |
| L2 | `what are current offers?` | Offers (not product search). |
| L3 | `aaj ka gold rate kya hai?` | Live gold rates (22KT/24KT). |
| L4 | `sone ka bhav batao` | Gold rates. |
| L5 | `koi scheme hai kya? KMR vagera` | KMR/savings plan info (not offers). |
| L6 | `EMI available hai?` | EMI policy answer. |
| L7 | `What is KISNA?` | Brand answer, not search. |
| L8 | `kya hallmark jewellery hai?` | Hallmark/BIS answer. |
| L9 | `making charges kitna hai` | Policy answer (not returns flow). |
| L10 | `buyback kitna milega` | Buyback policy answer. |

---

## SECTION M — Edge cases / adversarial

| # | Paste this | Expected |
|---|---|---|
| M1 | `asdfghjkl` | Polite clarification — the ONE place "samajh nahi aaya" is acceptable. |
| M2 | `gold` (bare word) | Clarifying question or wizard start, NOT a wrong guess. |
| M3 | `book me a flight to Delhi` | Polite redirect to jewellery. |
| M4 | `😍😍` right after results | Friendly continuation, does NOT restart the wizard. |
| M5 | `thank you` | Warm ack, no menu spam. |
| M6 | `return gift ke liye kuch dikhao` | Product search (gift), NOT returns flow. |
| M7 | `hi show me rings` | Ring flow starts (greeting prefix must not swallow the query). |
| M8 | Mid-wizard, send the same answer twice (`[TAP Female]` twice) | No duplicate/stuck state; moves on. |
| M9 | Wait 2+ hours after results, then `show more` | "Your search session has expired…" + asks what they're looking for (not a crash). |
| M10 | At the **budget** step, send `400001` (a pincode) | Budget question re-asked — must NOT become a ₹4 lakh search. But `100000` at the same step IS a valid budget. |
| M13 | `hi` then `gold rings for her 50k se 1 lakh` | Range read as ₹50,000–₹1,00,000 (the Hinglish range works without "tak"). |
| M11 | At the **budget** step, send `gold` | Should re-ask the budget question, not silently search. |
| M14 | At the **budget** step, send `not sure` | Accepted as "no preference" → fulfillment question. |
| M12 | Start wizard, then `custom design chahiye` | Design-expert handoff — must NOT be swallowed as a "made to order" fulfillment answer. |

---

## Reporting format (send this back)

One line per test:

```
B5: [PASS/FAIL] — bot said: "<first line>" (buttons: yes/no, images: 3/0, See Collection last: yes/no)
```

**Always flag these:**
- "Mujhe samajh nahi aaya" outside M1/M2
- Reply language ≠ user's message language
- Product cards missing images, or split into image + separate "Tap below to buy" bubble
- `See Collection` appearing before the 3 products, or missing
- Wizard re-asking a slot the user already answered
- Wizard continuing after an escape (agent/callback/store/offers/gold rate)
- Any product name, price, gram weight or carat that doesn't exist on the linked kisna.com page
- Old filters leaking (wrong category/material/gender/price) after a refinement
- Any turn where only SOME of the messages arrive (e.g. 2 cards instead of 3, or no `See Collection`) — note how many landed
