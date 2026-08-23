# Final end-to-end QA — Kisna WhatsApp chatbot

**Branch** `v3-text-flow` (= `prod`) · **HEAD `bbbdd30`** · **Suite 1343 passing**, 18 skipped
**Sweep**: 251 conversations / 410 turns, 8 batches, 0 exceptions, all 13 languages
**Verdict**: the two ship-blockers found are fixed, verified live and deployed. Nothing customer-blocking is known open.

The question this pass had to answer was not "do the new fixes work" but
**"did the eleven commits break anything that used to work"**. Both answers are
below, and the regression answer was *yes, two things* — both mine.

---

## 1. What was verified working

All measured live through the real pipeline, not read off a transcript.

| Area | Result |
|---|---|
| Budget ceilings | **14/14 languages.** "under ₹20,000" → `max_price=20000`, `min_price=null`. Never inverted, never `min==max` |
| Price ranges | 5/5 — `15–35k` (en dash), `15-35k`, "between 20k and 40k", Hindi and Tamil equivalents |
| Order tracking | 7/7 generic CTA, **no junk-id echo**; 5/5 with an id — prose translated, `KIS-2024-778812` byte-identical |
| Off-step funnel survival | 9/9 — refinements keep every collected slot; all five genuine escapes fire; a category switch keeps gender and material |
| Pagination | 6 languages, up to 4 pages, **zero repeats**, product names verbatim English throughout |
| Markdown + script purity | **410/410 turns clean** — 0 empty replies, 0 `**`, 0 unbalanced asterisks, 0 literal `\n`, 0 foreign script |
| Prompt injection | 4/4 refused; no system prompt, model name, tool name or `_compose` tag leaked in 410 turns |
| Unsupported materials | 6/6 — refused honestly at entry and at the wizard material step, with the buttons reduced |
| Store lookups | Mumbai (4), Bombay, Calcutta, bare pincode, Delhi, Chennai, Lucknow, Pune, Guwahati, state lookup — correct. **Goa, Kerala and Surat correctly report none** |
| Store follow-up | 3/3 reuse the remembered city, including per-branch timings in Tamil |
| Offers and gold rate | 12/12 languages, fully translated, every ₹ and % intact |
| Reply-language stability | English chats stay English through 6 turns; native script is never demoted to romanized; Marathi holds through a refinement |
| Kinship gender | 10/11 terms across 8 languages; parents / cousin / friend correctly ask instead of guessing |

Thirteen of the fourteen changed behaviours also landed as intended — native-script
"yes" in all 13 languages, opt-out in 8 (with "stop showing me gold ones"
correctly *not* unsubscribing), six-figure budgets as ceilings, `excluded_material`
with its contrast case, multi-intent, Urdu end-to-end, size-question vs
new-search, प्रीमियम vs pagination, વીંટી, and the returns/complaint flow
keeping its order number.

---

## 2. Regressions found — both fixed in `bbbdd30`

### R1 · City aliases stopped resolving · `4c8a5e6` · 12/13 reproduction · **ship-blocker**

> `any store in bengaluru?` → *"No KISNA stores found near you."*
> KISNA has **four** Bangalore stores.

Madras, Mysuru and Gurgaon failed identically. Canonical spellings and native
script were unaffected, which is what made it invisible.

`_location_entities` merged the extractor LLM's `city` over the regex layer's.
The regex canonicalises through `_CITY_NAME_MAP` (`bengaluru → Bangalore`) and
had already got it right; the model answers with the customer's own spelling,
and this merge overwrote the canonical name with it. Matching then compared
`"bengaluru"` against the catalogue's `address.city.name` `"Bangalore"` and
found nothing. Bombay and Calcutta survived only because the model happens to
canonicalise those two itself.

**Fixed** by canonicalising the model's answer through the same map before
merging, and keeping what the regex resolved when the map does not know the
name. The model still wins where the regex is blind — native script, the
reason it was put in front — and that is covered by a test.

### R2 · Product names renamed in Hindi answers · `4c8a5e6` · 3/3 Hindi, 0/3 elsewhere

> `साइज़ 14 है क्या?` → *"जी हाँ, **Waida अंगूठी** का साइज 14 है…"*
> and on a price question, *"झानवी अंगूठी की कीमत ₹70,240 है"*.

A customer told "झानवी अंगूठी" cannot find that piece on the card, on
kisna.com, or in their order. Tamil, Urdu and Marathi got the same question
right, which is what isolated it to the composer rather than the answerer.

`4c8a5e6` tagged the spoken product answer `_compose` without pinning
anything. Cards were already protected because `_bold_titles` recovers a
card's title — a card always bolds it — and a spoken answer does not.

**Fixed** with a `_pin` key builders can attach to a response; the three
product replies that name a piece now declare their names. Deliberately *not*
pinning every bold segment: the recap bolds the material, the category and the
budget, and all three must translate. That distinction is a test.

---

## 3. Three pre-existing defects, also fixed in `bbbdd30`

None is a regression. All three are the same failure the handover names in §0
— a rule written for the languages someone had in front of them.

- **Assamese was answered in Bengali, 14/14 turns.** Widening the script block
  to `{"bn","as"}` was not enough: it still defaulted to `bn` whenever the
  model did not volunteer `as`, which was every turn. Assamese and Bengali
  share a Unicode block but not an alphabet — ৰ (U+09F0) and ৱ (U+09F1) are
  not Bengali letters. Measured 4/5 Assamese sentences carry one, 0/5 Bengali
  do; short turns are held by the existing bn/as sibling stickiness. Live now:
  নমস্কাৰ / আপোনাৰ, with Bengali unchanged.
- **A carat weight in native script became a rupee budget.** `10 कैरेट से कम की
  अंगूठी है क्या?` → `max_price=10000`; the same sentence ending `दिखाओ` →
  `100000`. Two different invented numbers for near-identical input is what
  tells you it is the model, not a regex. Tamil and Gujarati failed the same
  way; English was already guarded, in Latin only. A *stated* budget beside a
  carat weight still survives, including one written in plain digits.
- **Punjabi ਮੁੰਦਰੀਆਂ (rings) returned earrings**, 3/3 on a full sentence, 0/3
  when short — the identical shape recorded for Gujarati વીંટી in `6fe1dd6`,
  in a language nobody had checked. ਵਾਲੀਆਂ and કાનની બુટ્ટી still read earring.

---

## 4. Still open

Nothing customer-blocking. In rough priority:

- **"story udaipur" routes to `general`** and answers "are you looking for a
  specific piece?" instead of the Udaipur branch (3/3). Every near-miss
  control passes — `stor udaipur`, `strore in udaipur`, `store in udaipur`,
  and `story mumbai`. The extractor reads `city: "Udaipur"` correctly; the
  classifier simply does not route there, and the store heuristics need a
  literal `store|shop|showroom|outlet` token so the model alone decides. Not
  attributable to a commit and stable-wrong only for this one city.
- **Tamil "அத்தை" alone drops gender**, 3/4. Adding any category word rescues
  it (`அத்தைக்கு ஒரு மோதிரம்` → `women`, 2/2). One term, one phrasing shape.
- **Intermittent compose-quality glitches**, all ~1/4 and none systematic:
  Gujarati offers rendered `હીરાનું હવલાત`; Malayalam offers leaked a Spanish
  word (`índice`); a Hindi wizard prompt said `जुड़वां` (twins) for earrings
  once; Bengali/Assamese cards mix Latin and native digits within one message.
  Figures and ₹ prices were correct in every instance.
- Carried forward unchanged: **cold start** (~60 s for the first ~6 turns after
  a deploy), **one 43 s Telugu latency tail**, **Odia compose intermittency**,
  **Odia/Kannada fluency**, Hindi **"समय क्या है?"** answering with support
  hours, **head office** (excluded by the product owner), **multi-intent is
  partial by design**, **~45 untagged responses** with recorded reasons.
- Product-owner decisions still outstanding: the prod `KISNA_SUPPORT_EMAIL`
  value, and whether the KB carries a headline offers percentage.

## 5. Could not reproduce

- Marathi "आणखी दाखवा" repeating the recap — happens only while a confirmation
  is pending, which is correct. Clean across 3 pages, twice.
- The returns/complaint "loop" — the WhatsApp Flow payload being re-offered.
  The harness cannot complete a Flow, so flow completion is *untested*, not
  broken.
- Cold start — never observed in this sweep; the process stayed warm. Median
  turn ~5 s, slowest 20 s.

---

## 6. The pattern worth naming

R1, the carat guard and the Punjabi ring word are all handover §0 again, and
R1 is it running in reverse: **code discarding what a layer had already got
right.** The earlier fixes were correct but were applied one language at a
time instead of at the layer — which is why Gujarati was fixed and Punjabi was
not, and why English carats were guarded and native-script ones were not. When
the next one of these appears, fix the layer.
