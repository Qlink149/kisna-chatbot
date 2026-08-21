# Clara UAT `/filters` — Chain category karat/colour facets are empty

**Not a kisna-chatbot bug.** This is an escalation to whoever owns the Clara UAT catalogue/backend. No code change is proposed or needed here — see "Why the chatbot needs no change" below.

## What was observed, with timestamps

| When | `GET /filters?categoryId=<Chain>` karat | colour | Global karat | Session |
|---|---|---|---|---|
| Earlier verification pass, same day | `[14KT, 18KT]` | `[Rose, Yellow]` | `[9,14,18,24KT]` | prior pass, live-verified via `scripts/verify_bug4_live.py` — validation correctly fired and offered real Chain alternatives |
| Later, same day, same session | `[]` (empty) | `[]` (empty) | `[9,14,18KT]` (24KT gone) | re-running the identical script — validation stopped firing entirely |
| **Just now** (this pass) | `[]` (empty) | `[]` (empty) | `[9,14,18KT]` (24KT still gone) | direct `curl` re-check |

**This is sustained, not transient.** Chain's karat/colour facets have been empty across two independent checks separated by a meaningful gap (a full prior audit pass ran in between). Global karat has also not recovered its 24KT entry. Escalation urgency should be treated accordingly — this is not "flaky, check back later," it's "still broken as of right now."

## Is this Chain-specific, or could it be elsewhere too?

Checked just now, for comparison:

| Category | karat | colour |
|---|---|---|
| **Chain** | **`[]` — empty** | **`[]` — empty** |
| Rings | `[9KT, 14KT, 18KT]` | `[Rose, White, Yellow]` |
| Bangles | `[9KT, 14KT, 18KT]` | `[Rose, White, Yellow]` |
| Earrings | `[14KT, 18KT]` | `[Rose, White, Yellow]` |
| Global (all categories) | `[9KT, 14KT, 18KT]` | `[Rose, White, Yellow]` |

Chain is the only category checked with genuinely empty facets — Rings/Bangles/Earrings all return healthy, populated lists (Earrings legitimately has only 2 karat options, which is a normal per-category difference, not emptiness). **Recommend checking the remaining categories** (Necklace, Pendant, Bracelet, Mangalsutra, and the rest of the 16-category list) for the same volatility before concluding this is Chain-only — only 4 of 16 categories were spot-checked here, due to time.

## Practical impact on the chatbot

Karat/colour validation (the "we don't offer 22KT for chain, here's what we do have" message, and its `filter$fix$*` quick-reply follow-through) is a **silent no-op for chain** right now. A user asking for "22kt chain" or "white gold chain" gets no correction message and no guided alternative — the search just runs with whatever material/category/price it can extract, silently dropping the karat/colour filter. This is not a crash and not visibly broken to the user (they just don't get told why their exact request wasn't matched), which is precisely why it's easy to miss without direct testing.

## Why the chatbot needs no change

`build_impossible_value_prompt` (`kisna_chatbot/processors/filter_validation.py`) already has a designed degradation path for exactly this situation: when a category-scoped facet's option list comes back empty, it does not block the search or throw an error — it treats the facet as unvalidatable and lets the search proceed (`test_cold_skips_impossible_validation` in `tests/test_filters_guardrails.py` pins this down and is currently green). The code is behaving correctly given the input it's receiving; the input itself is the problem.

## Ask

Someone with access to Clara's catalogue/backend needs to confirm:
1. Was Chain's karat/colour attribute data deliberately removed or restructured?
2. If not deliberate — is this a known/ongoing UAT instability, and is there an ETA for it to be restored?
3. Should the other ~12 unchecked categories be swept for the same issue before assuming it's Chain-only?

No action needed on the kisna-chatbot codebase.
