# Kisna WhatsApp chatbot — handover

**Repo**: `c:\Users\pc\Desktop\clara\chatbot\kisna-chatbot`
**Branch**: `v3-text-flow` — also what is deployed (`prod` is a fast-forward of it)
**HEAD at handover**: `6d2580e` · **Suite: 1324 passing**, 18 skipped

This replaces `OPEN_DEFECTS_HANDOFF.md`, which is now fully closed.

---

## 0. The one idea that explains most of the bugs

> Someone writes a Latin word list to detect something. It covers the languages
> they thought of. It silently breaks for the rest — while **the LLM already
> understood the message and the code discarded it.**

Confirmed instances, all now fixed: kinship gender · budget declines · Odia
budget ceilings · bare negation · store city/state · native-script "yes" ·
opt-out · Devanagari price loanwords · "non-Latin means Indic".

**So for any new defect, ask in this order:**
1. Does the LLM already emit the right answer? (test the extractor directly)
2. If yes — where does our code drop, override, or fail to consult it?
3. Only if the LLM genuinely gets it wrong, change the prompt.
4. A deterministic list is acceptable **only as a fallback behind the model**,
   and only where you have measured the model failing. Two such fallbacks
   exist and both record their measurement in a comment: romanized price
   comparatives, and English price loanwords in native script.

**A fix verified only in English is not a fix.** Languages that matter:
English, Hindi (Devanagari + romanized), Gujarati, Marathi, Tamil, Telugu,
Bengali, Punjabi, Kannada, Malayalam, Odia, Assamese, Urdu.

---

## 1. How to reproduce anything

```bash
cd "c:/Users/pc/Desktop/clara/chatbot/kisna-chatbot"
./.venv_audit/Scripts/python.exe scripts/loadtest_harness.py <in.json> <out.json> --concurrency 6
./.venv_audit/Scripts/python.exe scripts/qa_scan.py <out.json> <in.json>
```

The harness runs whole conversations through the **real** pipeline (real
classifier, real agents, real Clara API, real translation), skipping only the
WhatsApp send and Mongo writes.

```json
[{"id":"case","lang":"ta","note":"why this exists",
  "turns":["show me gold rings under 50k", {"tap":"Yes, show me"}, {"tap":0}]}]
```

`scripts/qa_scan.py` flags empty replies, unbalanced/`**` markdown, literal
`\n`, foreign script, **same-script wrong language** (hi/mr, bn/as),
untranslated English, duplicate lines, oversize replies and prompt leakage.

Full suite: `./.venv_audit/Scripts/python.exe -m pytest -q -p no:cacheprovider`
(~2 min). Individual test files fail in isolation due to a circular import —
that is not a real failure, run the whole suite.

### Traps that have each cost real time
- **`qa_scan.py` needs BOTH files.** `lang` lives in the INPUT; the harness does
  not copy it to the output. An earlier scanner read it from the output, got
  `""` every time, and silently skipped every language check across three
  sweeps while reporting "0 foreign-script characters". The scanner now prints
  how many conversations carried a `lang` — if that says 0, the checks did not
  run.
- **Product fixtures need >2 results.** `gold rings for women under 50000 ready
  to ship` returns exactly 2, so pagination tests hit "You have seen all 2
  results!" and prove nothing. `under 200000` returns 12.
- **The confirmation card needs all five slots** (category, material, gender,
  budget, fulfillment). Fewer enters the wizard — a different code path.
- `{"tap":0}` on a prompt with no buttons does nothing and yields a blank turn.
- `profile.last_search_products` is serialised as a **string**; read the reply.
- `profile` exposes `reply_language`, not `language`. There is no raw
  `bot_response` in the output — only the rendered `reply`.
- **Always** use `./.venv_audit/Scripts/python.exe`, and make
  `from kisna_chatbot.main import app` the first project import in any script.
- Set `PYTHONIOENCODING=utf-8` and wrap stdout, or Indic/Arabic printing crashes.

---

## 2. Open items

Nothing customer-blocking is known open. In rough priority:

### 2.1 Model quality (no code fix available)
- **Odia compose is intermittent.** `gpt-5.6-luna` returns an *empty* rewrite
  for some strings, so the unsupported-material note and the offers table
  sometimes ship in English. A second-opinion retry on the other model was
  added and fixes Hindi deterministically; Odia improved but still fails
  sometimes. `AI_MODEL_COMPOSE_WEAK` changes the model without a deploy.
- **Odia/Kannada phrasing** is weaker than the other languages. Invented
  product *names* are fixed (the answerer is told they are proper nouns);
  general fluency is a model-selection question.

### 2.2 Operational
- **Cold start**: the first ~6 turns of a fresh process take 58–63 s each;
  every other turn is median 4.7 s. The first customer after a deploy waits a
  minute. A warm-up call at startup is the obvious fix, untried.
- **Latency tail**: one Telugu compose call once took 43 s. If it recurs on real
  traffic it needs a timeout-and-fall-back-to-mini guard. Do not add one
  speculatively — drive it from production data.

### 2.3 Known-imperfect, judged acceptable
- A Hindi **"समय क्या है?"** after store cards routes to the FAQ and answers
  with *support* hours rather than that branch's timings. Genuinely ambiguous
  ("what time is it?"); the English "what are the timings?" works and reuses
  the remembered city.
- **"Where is your head office?"** answers with the policy and offers the store
  locator. Excluded from scope by the product owner.
- A **carat question with 2+ pieces shown and none opened** answers across all
  of them rather than picking one. Intentional.

### 2.4 Deferred features
- **Multi-intent is partial.** `offers` and `gold_rate` asked as a second
  request are answered inline; `store_info` and `general` get an
  acknowledgement line. `order_tracking`, `returns_refund` and `complaint` are
  deliberately NOT supported as secondaries — each needs its own conversation.
- **~45 untagged responses remain** and are listed with reasons in
  `tests/test_untagged_responses.py`. Three groups genuinely cannot be fixed by
  tagging: `ResponseManager` builds its fallbacks *after* localisation runs, the
  admin takeover route calls `send_text_message` directly, and WhatsApp Flow
  payloads never become a `bot_response`. Fixing those means moving the work,
  not adding a tag.

### 2.5 Decisions the product owner still owns
- **`KISNA_SUPPORT_EMAIL` in the prod environment** drives the runtime support
  address. The KB is now internally consistent (`ecom@` for returns/exchange,
  `support@` for general) but a code change alone will not move the env value.
- **Offers percentages**: the KB no longer quotes numbers and defers to the
  offers flow, which is the single source of truth. If marketing wants a
  headline figure in the KB, it must be kept in step with that table.

---

## 3. Guardrails — do not remove these without reading why

| Guard | Protects against |
|---|---|
| `tests/test_untagged_responses.py` | A new customer-facing reply shipping in English. Does not ban untagged responses — bans adding one without recording a reason. |
| `tests/test_prompt_budget.py` | Prompt drift. **Headroom is thin**: ~3045 tokens under the request ceiling against a 3000 floor. The next addition WILL fail `test_entity_extractor_fits_under_request_ceiling`. **Trim; do not raise it.** |
| `scripts/qa_scan.py` | Language and script regressions no test covers. |
| `kisna_chatbot/utils/script_detect.py` | "Non-Latin means Indic". Seven sites once encoded that assumption; adding Urdu broke all seven at once. Ask what a character IS, never which block it sits in. |
| `_PINNED_PHRASES` / `pin=` in `reply_composer` | Product names, button labels and typed-back trigger phrases being translated. A renamed product is unfindable on the card, the site and the customer's order. |

---

## 4. Architecture notes worth knowing

- **Entity contract is split.** `kisna_classifier_intent` owns routing plus
  `product_reference`, `product_question`, `action`, `secondary_intent`.
  `kisna_entity_extractor` owns every search filter and runs context-free.
- **Localisation is opt-in.** `localize_bot_responses` only rewrites items
  carrying `_compose`. It handles `text`, `cta_url`, `flow`, `quickreply` and
  media `caption`. `display_text` is deliberately never translated — WhatsApp
  caps button labels at 20 characters.
- **Two composer paths**: `compose()` mirrors canned copy faithfully (cached by
  language + exact text); `narrate()` regenerates personality lines. Functional
  copy must never use a personality tag — figures and terms have to survive.
- **Model routing**: `resolve_compose_model()` sends ten native-script
  low-resource languages plus Urdu to `AI_MODEL_COMPOSE_WEAK`
  (`gpt-5.6-luna`). English and Hindi measured *better* on the default and stay
  there; every member of that set is measured, not assumed — the numbers are in
  `ai/config.py`. The general agent uses the same resolver.
- **Clara API constraints** (escalated, not our bugs): `?city=X` returns 400
  (city is smuggled through the broad `name=` text search), and `pageSize` is
  ignored unless `pageNo` is passed too. Store city/state matching is done
  client-side against `address.city.name` / `address.state.name`.

---

## 5. Repo hygiene at handover

Three tracked files have been modified since before this work and are **still
uncommitted** — they are not mine to commit:

```
scripts/build_replay_conversations.py
scripts/pull_verification_transcripts.py
tests/replay/real_conversations.json     (~2,850 lines)
```

Plus ~54 untracked files under `audit/` and `scripts/`. Decide what is worth
keeping before the next person clones this.
