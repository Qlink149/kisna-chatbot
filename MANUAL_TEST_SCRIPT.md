# KIA Manual Test Script (WhatsApp)

**How to use:**
1. Paste each message ONE BY ONE into WhatsApp, in the order given (order matters — some tests depend on prior state).
2. For each message note: the bot's reply (full text), whether images/buttons/forms arrived, and anything weird.
3. Where a section says **RESET**, first send `hi` (or `menu`) to clear state before continuing.
4. After finishing, send me the full "message → response" list and I'll analyze failures.

**PASS criteria are written under each message.** If reply is the Hindi "Mujhe samajh nahi aaya..." clarification when it shouldn't be — that's a FAIL, note it.

---

## SECTION A — Greeting & Menu (state reset behaviour)

| # | Paste this | Expected |
|---|---|---|
| A1 | `hi` | Greeting + welcome/menu. Fresh session. |
| A2 | `menu` | Main menu options. |
| A3 | `kya kya kar sakte ho` | Menu/help — capabilities list. |
| A4 | `namaste` | Greeting (not product search). |

---

## SECTION B — Human handoff (the recent fix — CRITICAL)

**RESET: send `hi` first.**

| # | Paste this | Expected |
|---|---|---|
| B1 | `Connect me with agent` | Live agent handoff (open hours) OR offline message + callback form. NEVER "samajh nahi aaya". |
| B2 | `hi` then `Connect me with a human` | Same handoff behaviour. |
| B3 | `hi` then `talk to a human` | Handoff. |
| B4 | `hi` then `I need a real person` | Handoff. |
| B5 | `hi` then `transfer me to support` | Handoff. |
| B6 | `hi` then `customer care` | Handoff. |
| B7 | `hi` then `agent se baat karni hai` | Handoff (Hinglish). |
| B8 | `hi` then `human se baat karo` | Handoff. |
| B9 | `hi` then `मुझे किसी इंसान से बात करनी है` | Handoff (Devanagari). |

## SECTION B2 — Callback vs handoff (must NOT mix)

| # | Paste this | Expected |
|---|---|---|
| B10 | `hi` then `call me back` | Callback form (NOT live agent handoff). |
| B11 | `hi` then `please call me` | Callback form. |
| B12 | `hi` then `mujhe call karo` | Callback form. |
| B13 | `hi` then `video call schedule karna hai` | Video call flow (NOT callback, NOT handoff). |

---

## SECTION C — Product search (English)

**RESET: send `hi`.**

| # | Paste this | Expected |
|---|---|---|
| C1 | `show me diamond rings` | Product cards WITH images on WhatsApp (not just text). Diamond rings. |
| C2 | `under 50k` | SAME search refined — diamond rings under ₹50,000 (keeps category+material). |
| C3 | `show more` | Next page of same results, no repeats. |
| C4 | `necklace above 10k` | Category switches to NECKLACE (not rings), price above 10k, old material NOT carried unless restated. |
| C5 | `for men` | Same search but gender=men. |
| C6 | `gold bracelet for gifting around 30000` | Bracelet, gold, ~30k, occasion gift. |

## SECTION C2 — Product search (Hinglish)

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| C7 | `mujhe sone ki anguthi dikhao` | Gold rings with images. |
| C8 | `20k se 50k tak` | Same rings, ₹20k–50k range. |
| C9 | `thoda sasta dikhao` | Cheaper options (relative price, no invented numbers). |
| C10 | `aur dikhao` | More results (NOT treated as "wrong answer"). |
| C11 | `heere ki bali 50k tak` | Diamond earrings under 50k. |

## SECTION C3 — Product search (native scripts) — MULTILINGUAL CRITICAL

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| C12 | `मुझे सोने की अंगूठी दिखाओ` | Gold rings. Reply in Hindi. |
| C13 | `५० हज़ार से ज़्यादा कीमत वाला नेकलेस चाहिए` | Necklace above ₹50,000. NOT a "can't give prices" answer. |
| C14 | `१० हज़ार से कम की इयररिंग` | Earrings under ₹10,000. |
| C15 | `મારે ૪૦ હજારથી વધુ કિંમતની બુટ્ટી જોઈએ છે` | Gujarati: earrings above ₹40,000. Reply in Gujarati. |
| C16 | `મારે ૧૦,૦૦૦ થી ૩૦,૦૦૦ ની વચ્ચેની કિંમતની કાનની બુટ્ટી જોઈએ છે` | Earrings ₹10k–30k (BOTH bounds extracted). |
| C17 | `તમારી પાસે રિંગ છે?` | Rings shown, Gujarati reply. |
| C18 | `Mala ek ring pahije` | Marathi "I want a ring" → RINGS (NOT necklace/mala!). |
| C19 | `Tamara kem che` | Gujarati greeting → greeting reply, not search. |

---

## SECTION D — Product follow-ups (needs results on screen)

**Setup: send `hi` then `show me diamond rings` first, wait for results.**

| # | Paste this | Expected |
|---|---|---|
| D1 | `the second one` | Details/price of item #2 from shown list. |
| D2 | `which is cheaper?` | Compare of the shown items. |
| D3 | `does it come with a chain?` | Info about the viewed product (from API, not generic). |
| D4 | `बीच वाला कितने का है` | Price of middle shown item, Hindi reply. |
| D5 | `no that's not what I meant` | Apology + asks what they want (REPAIR — fresh start, NOT same results again). |

---

## SECTION E — Shopping wizard + sticky state (regression of recent fixes)

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| E1 | Start wizard (tap browse / or send `kuch dikhao`) | Wizard or clarify prompt. |
| E2 | Follow wizard: pick `Ring` → `Male` → `Gold`, then type `50k` | Budget accepted → SEARCH RESULTS. NOT a store/pincode reply (old bug). |
| E3 | `hi` then `store near me` then instead of pincode type `show me gold rings` | Escapes store wait → shows rings (doesn't say "invalid pincode"). |
| E4 | `hi` then `store near me` then `400001` | Store list for Mumbai 400001. |
| E5 | `hi` then `560001` (bare pincode, no context) | Store lookup for that pincode. |

---

## SECTION F — Ready-to-ship / fallback quality (regression)

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| F1 | `ready to ship gold rings between 40k and 50k` | If exact match exists → gold rings RTS. If 0 results → fallback must KEEP GOLD (drop ready-to-ship first). Diamond rings appearing = FAIL. |
| F2 | `made to order ring chahiye` | MTO rings OR custom-design handoff — note which one you get. |

---

## SECTION G — Offers / gold rate / schemes

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| G1 | `koi offer hai?` | Current offers. |
| G2 | `what are current offers?` | Offers (NOT product search). |
| G3 | `aaj ka gold rate kya hai?` | Live gold rates (22KT/24KT etc.). |
| G4 | `sone ka bhav batao` | Gold rates. |
| G5 | `koi scheme hai kya? KMR vagera` | KMR / savings plan info from KB (NOT offers). |
| G6 | `EMI available hai?` | EMI policy answer (general/KB). |

---

## SECTION H — Orders / returns / complaints

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| H1 | `track my order` | Order tracking flow. |
| H2 | `mera order kahan hai` | Order tracking. |
| H3 | `return karna hai` | Returns/refund ACTION flow. |
| H4 | `return policy kya hai` | Policy ANSWER (KB), not the return flow. |
| H5 | `mera order damage aa gaya` | Complaint flow. |
| H6 | `order cancel karna hai` | Human handoff (bot can't cancel). |
| H7 | `मुझे रिटर्न करना है` | Returns flow, Hindi reply. |

---

## SECTION I — Brand FAQ / general knowledge

| # | Paste this | Expected |
|---|---|---|
| I1 | `What is KISNA?` | Brand answer (NOT product search). |
| I2 | `kya hallmark jewellery hai?` | Hallmark/BIS answer. |
| I3 | `gold kaise maintain kare` | Care tips. |
| I4 | `making charges kitna hai` | Policy answer (not returns flow). |
| I5 | `buyback kitna milega` | Buyback policy answer. |

---

## SECTION J — Edge cases / adversarial

| # | Paste this | Expected |
|---|---|---|
| J1 | `asdfghjkl` | Polite clarification (this is the ONE place "samajh nahi aaya" is OK). |
| J2 | `gold` (bare word) | Clarifying question, not a wrong guess. |
| J3 | `book me a flight to Delhi` | Polite redirect to jewellery topics. |
| J4 | `😍😍` (right after search results) | Friendly continuation, does NOT restart flow. |
| J5 | `thank you` | Warm acknowledgement, no menu spam. |
| J6 | `return gift ke liye kuch dikhao` | PRODUCT SEARCH (gift), NOT returns flow. |
| J7 | `custom ring banwana hai` | Design-expert handoff message. |
| J8 | `hi show me rings` | Rings shown (greeting prefix must not swallow the search). |

---

## SECTION K — Language switching mid-conversation

**RESET: `hi`.**

| # | Paste this | Expected |
|---|---|---|
| K1 | `show me gold rings` | English results. |
| K2 | `इसका price बहुत ज्यादा है` | Cheaper options, HINDI reply (language switched). |
| K3 | `mane sastu joie che` | Even cheaper, Gujarati-romanized understood. |
| K4 | `ok in English please` | Bot switches back to English. |

---

## Reporting format (send me this back)

For each test, one line like:

```
B1: [PASS/FAIL] — bot said: "<first line of reply>" (buttons: yes/no, images: yes/no)
```

Flag anything where:
- Reply language ≠ user's message language
- "Mujhe samajh nahi aaya" appeared outside J1/J2
- Images/cards missing on WhatsApp for product results
- Old filters leaked (wrong category/material/price)
- Store/pincode reply appeared where it shouldn't
