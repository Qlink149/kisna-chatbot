# Dynamic filters — Phase 7 final report

Branch: `v3-text-flow` (from `prod` @ `10b0eef`)

## Commits

| Phase | Commit | Summary |
|-------|--------|---------|
| 0 | `8df7921` | `/filters` in-process cache + snapshot + warm |
| 1 | `4991ac3` | 22KT / collections / souvenir / slug alignment |
| 2 | `a4ff144` | `shopping_wizard_explicit` preserve/merge/clear |
| 3 | `50b5f1d` | `categoryId` / `collectionId` / one-meta + `drop_meta` |
| 4 | `46d1dd5` | Dynamic gender skip / auto-set / live QRs |
| 5 | `5f0c4d7` | Impossible-value validation + optional cross-cat |
| 6 | `9dff00b` | Chroma/KB routes cleanup; OpenAI-only docs; keep Vercel |
| 7 | (this) | Guardrail tests + drift script + report |

## Test counts (pytest)

| Gate | Passed | Skipped | Notes |
|------|--------|---------|-------|
| Baseline (plan) | 1037 | 18 | pre-work |
| After Phase 0 | 1049 | 18 | |
| After Phase 1 | 1050 | 18 | |
| After Phase 2 | 1055 | 18 | |
| After Phase 3 | 1064 | 18 | |
| After Phase 4 | 1068 | 18 | |
| After Phase 5 | 1072 | 18 | |
| After Phase 6 | 1072 | 18 | |
| After Phase 7 | **1083** | 18 | +11 guardrail tests |

Failures: **0** at every committed gate.

## Classifier regression (intent)

All phase labels: **intent 100%** every bucket (with production guards 100%).  
Pre-existing **gu-03** (Gujarati વીંટી ring→earring) **unchanged**.  
e2e / entities ≈ 97.8% (unchanged band).

Artifacts (untracked locally): `audit/regression_phase*.json`.

## Server / client split (Phase 3)

| Entity | Server param | Client filter |
|--------|--------------|---------------|
| category | `categoryId` (warm) else slug | — |
| collection | `collectionId` (fuzzy ≥0.82) else title | leftover title |
| gender | `tagManagerId` | — |
| karat XOR colour | one `metaSubAttributeValue` | the other meta |
| price / material / fulfillment | as before | size/style/occasion etc. |

**One-meta rule:** fewer cached facet options for the category wins; **tie → colour** (live measured).

**Ladder:** `full → drop_fulfillment → drop_meta → drop_price → …`

**searchUrl:** only when slug `category` or `title` present (ObjectId-only + `searchUrl` → Clara 400 `$or`).

**filter_ratio:** `client_survivors / server_page_size` (documented on `_compute_show_more_retries`).

## Live smoke (10 queries, slug vs ID)

| Query | before (slug/title) | after (IDs) |
|-------|---------------------|-------------|
| gold rings under 50000 | 266 | 138 |
| 18kt rose gold rings | 273 | 59 (colour meta) |
| women diamond earrings | 1447 | 1447 |
| evil eye bracelet | 236 | 11 (`collectionId`) |
| 18kt gold chain | 35 | 35 |
| rose gold necklace under 30000 | 1 | 1 |
| mens gold rings | 273 | 138 |
| tanishta bangles | 272 | 0 (`collectionId` AND — ladder recovers) |
| yellow gold pendants | 67 | 57 |
| diamond mangalsutra under 1 lakh | 205 | 186 |

## Cache

- TTL default **21600s** (`CLARA_FILTERS_TTL_SECONDS`)
- Warm: global + 16 categories, semaphore 4, fire-and-forget
- Snapshot drift script: `scripts/report_filters_drift.py` → `audit/filters_drift_report.json` (last run: **+0/−0** global label drift)

## Guardrails added

- `tests/test_filters_guardrails.py` — snapshot ⊆ taught enums; cold degradation; gender skip; 22KT block; explicit survive wizard; categoryId path
- Degradation: filters off ⇒ slug/title behaviour (no IDs / no validation / legacy gender ask)

## UNVERIFIED / open

- Production EasyPanel env may still contain unused `GROQ_*` / `CHROMA_*` keys (not probed remote).
- WhatsApp QR tap on `filter$fix$*` is not yet a dedicated advance handler (user can retype); follow-up if needed.
- Vercel kept per Q7; Docker remains documented production path.

## Q1–Q9 (locked) — status

All shipped as decided: one-meta option-count+tie→colour; ladder drop_meta; filter_ratio redefine; silent gender auto-set; no karat/colour wizard steps; single cross-cat only; keep Vercel; TTL 6h+snapshot; hard-stop on Clara contradiction (searchUrl+$or caught and fixed in Phase 3).
