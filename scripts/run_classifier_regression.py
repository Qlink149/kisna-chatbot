"""Multilingual classifier regression gate (LIVE model — not part of pytest).

Runs tests/multilingual_regression.json against the classifier prompt under
test and the entity-extractor prompt, using batched screening + individual
re-verification so a 40-case x 3-run suite costs ~6 batched calls plus a
handful of single calls instead of 240 single calls.

Method (applied identically at every remediation stage so numbers compare):

  1. SCREEN — one classifier call and one entity-extractor call per run,
     3 runs, temperature=0. Every item is presented as an isolated
     conversation carrying only its own context.
  2. RE-VERIFY — every case that FAILED or VARIED across the 3 screening
     runs is re-run individually, one API call per case, through the exact
     production message shape (`_build_classifier_system_content` +
     "User Query: ..."). Individual results are authoritative.
  3. SCORE — individual result where re-verified, batched result where all
     3 runs agreed and passed.

Three scores are reported at every stage:
  intent_pct    — classifier prompt alone (comparable across all stages)
  entity_pct    — entity extractor prompt alone (production entity source)
  overall_pct   — intent AND entities, i.e. what the pipeline concludes

Usage:
    python scripts/run_classifier_regression.py --label baseline
    python scripts/run_classifier_regression.py --label stage1 \
        --classifier-prompt kisna_classifier_intent
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

# PINNED, not inherited: results must be comparable across stages and across
# machines regardless of what the local .env says. Production runs OpenAI
# gpt-4o-mini for the classifier; Groq is fallback only (and 413s on the
# current prompt, so it could not produce a comparable run anyway).
REGRESSION_PROVIDER = "openai"
REGRESSION_MODEL = "gpt-4o-mini"
os.environ["AI_PROVIDER"] = REGRESSION_PROVIDER
os.environ["AI_PROVIDER_CLASSIFIER"] = REGRESSION_PROVIDER
os.environ["AI_PROVIDER_GENERAL"] = REGRESSION_PROVIDER
os.environ["OPENAI_CHAT_MODEL"] = REGRESSION_MODEL
os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("KISNA_PHONE_NUMBER_ID", "850788844795304")

from kisna_chatbot.main import app  # noqa: F401,E402  (import order: env first)
from openai import AsyncOpenAI  # noqa: E402

from kisna_chatbot.processors import classifier as clf  # noqa: E402
from kisna_chatbot.prompts import classifier_kisna as prompts  # noqa: E402

CASES_PATH = ROOT / "tests" / "multilingual_regression.json"
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(exist_ok=True)

BUCKET_ORDER = [
    "gu-native",
    "hi-native",
    "romanized",
    "store",
    "contrast",
    "context",
]

# Canonical conversation state for each context flag. Kept here (not in the
# JSON) so the case file stays a pure statement of expectations.
ACTIVE_SEARCH_HISTORY = [
    {"role": "user", "content": "gold rings for women"},
    {"role": "assistant", "content": "Here are some lovely gold rings for her."},
]
ACTIVE_SEARCH_FILTERS = {
    "category": "ring",
    "material_type": "gold",
    "gender": "women",
}
STORE_WAIT_HISTORY = [
    {"role": "user", "content": "store in udaipur"},
    {"role": "assistant", "content": "Sure — please share your 6-digit pincode."},
]

BATCH_INSTRUCTION = """You will receive a JSON array of independent test messages.
Classify EACH one using the rules above, exactly as if it were the only message
you had ever received.

CRITICAL — treat every item as a separate, isolated conversation. Do NOT let one
item influence another. Do NOT carry entities, intent, language, or context
between items. Item 7 knows nothing about item 6.

Each item may carry its own context — use ONLY that item's context, and only for
that item:
  "active_search": true   -> treat as an active jewellery search
  "shown_products": [...] -> treat as the products currently shown
  "store_wait": true      -> treat as awaiting a store pincode
  absent                  -> no context at all

INPUT:
{payload}

OUTPUT — a json object {{"results": [...]}} whose array has the same order and
the same ids as the input, and nothing else:
{{"results": [{{"id": "gu-01", "intent": "...", "confidence": 0.0,
  "language": "...", "entities": {{...}}}}, ...]}}
Return that object only. No prose, no markdown fences."""

EXTRACTOR_BATCH_INSTRUCTION = """You will receive a JSON array of independent
messages. Extract jewellery attributes for EACH one using the rules above,
exactly as if it were the only message you had ever received.

CRITICAL — treat every item as a separate, isolated conversation. Do NOT let one
item influence another. Do NOT carry any value between items. Item 7 knows
nothing about item 6.

INPUT:
{payload}

OUTPUT — a json object {{"results": [...]}} whose array has the same order and
the same ids as the input. Each element is {{"id": "<id>", "entities": {{...}}}}
where entities is the full attribute object for that message.
Return that object only. No prose, no markdown fences."""

ENTITY_KEYS_CHECKED = (
    "category",
    "material_type",
    "min_price",
    "max_price",
    "gender",
    "fulfillment",
    "occasion",
    "action",
    "product_reference",
    "collection",
    "karat",
    "metal_colour",
    "size",
    "style",
    "price_direction",
)


# ──────────────────────────────────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────────────────────────────────
def est_tokens(text: str) -> int:
    return round(len(text or "") / 3.6)


def strip_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def load_cases() -> list[dict]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


def profile_for(case: dict) -> dict:
    """Reconstruct the user_profile the classifier would see in production."""
    ctx = case.get("context") or {}
    profile: dict[str, Any] = {"chat_history": [], "service_selected": ""}
    if ctx.get("active_search"):
        profile["chat_history"] = list(ACTIVE_SEARCH_HISTORY)
        profile["last_search_filters"] = dict(ACTIVE_SEARCH_FILTERS)
    if ctx.get("store_wait"):
        profile["chat_history"] = list(STORE_WAIT_HISTORY)
        profile["awaiting_store_pincode"] = True
        profile["service_selected"] = "ad_flow"
    shown = ctx.get("shown_products")
    if shown:
        products = []
        for entry in shown:
            match = re.search(r"₹\s*([\d,]+)", entry)
            price = int(match.group(1).replace(",", "")) if match else 0
            title = re.sub(r"\s*₹\s*[\d,]+\s*$", "", entry).strip()
            products.append({"title": title, "price": {"finalPrice": price}})
        profile["last_search_products"] = products
    return profile


def batch_item(case: dict) -> dict:
    item: dict[str, Any] = {"id": case["id"], "message": case["message"]}
    ctx = case.get("context") or {}
    if ctx.get("active_search"):
        item["active_search"] = True
    if ctx.get("store_wait"):
        item["store_wait"] = True
    if ctx.get("shown_products"):
        item["shown_products"] = ctx["shown_products"]
    return item


def entities_match(expected: dict, actual: dict) -> tuple[bool, list[str]]:
    """Every asserted field must match; null means 'must be null/absent'."""
    actual = actual or {}
    bad: list[str] = []
    for key, want in (expected or {}).items():
        got = actual.get(key)
        if want is None:
            if got is not None:
                bad.append(f"{key}: expected null, got {got!r}")
        elif got != want:
            bad.append(f"{key}: expected {want!r}, got {got!r}")
    return (not bad), bad


def apply_production_guards(query: str, intent: str, entities: dict) -> str:
    """Post-LLM intent corrections that run in production (classifier.py)."""
    override = clf._programmatic_intent_override(query)
    if override:
        return override[0]
    if entities.get("category") and intent in (
        "general",
        "product_info",
        "menu_help",
        "greeting",
    ):
        return "product_search"
    if (
        clf._STORE_LOOKUP_RE.search(query)
        and not entities.get("category")
        and not (
            clf._CATEGORY_WORD_RE.search(query)
            and clf._BROWSE_ACTION_RE.search(query)
        )
        and intent
        in ("product_search", "product_info", "general", "menu_help", "greeting")
    ):
        return "store_info"
    return intent


# ──────────────────────────────────────────────────────────────────────────
# LLM plumbing (direct SDK so temperature / response_format are available)
# ──────────────────────────────────────────────────────────────────────────
class Caller:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=os.environ["OPENAI_API_KEY"], timeout=180.0
        )
        self.model = REGRESSION_MODEL
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    async def chat(
        self, messages: list[dict], *, max_tokens: int, json_mode: bool = True
    ) -> str:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self.client.chat.completions.create(**kwargs)
                self.calls += 1
                usage = resp.usage
                if usage:
                    self.prompt_tokens += usage.prompt_tokens or 0
                    self.completion_tokens += usage.completion_tokens or 0
                return (resp.choices[0].message.content or "").strip()
            except Exception as exc:  # transient API errors
                last = exc
                await asyncio.sleep(2 * (attempt + 1))
        raise last or RuntimeError("chat failed")


def parse_results(raw: str, expected_ids: list[str]) -> dict[str, dict] | None:
    try:
        data = json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        return None
    items = data if isinstance(data, list) else (data.get("results") or [])
    by_id = {
        str(i.get("id")): i for i in items if isinstance(i, dict) and i.get("id")
    }
    if set(by_id) != set(expected_ids):
        return None
    return by_id


# ──────────────────────────────────────────────────────────────────────────
# batched screening
# ──────────────────────────────────────────────────────────────────────────
async def classifier_batch(
    caller: Caller, cases: list[dict], prompt: str
) -> tuple[dict[str, dict], dict]:
    payload = json.dumps([batch_item(c) for c in cases], ensure_ascii=False, indent=1)
    user = BATCH_INSTRUCTION.format(payload=payload)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user},
    ]
    raw = await caller.chat(messages, max_tokens=8000)
    ids = [c["id"] for c in cases]
    parsed = parse_results(raw, ids)
    if parsed is None:
        raw = await caller.chat(messages, max_tokens=8000)
        parsed = parse_results(raw, ids)
    meta = {
        "system_tokens": est_tokens(prompt),
        "batch_tokens": est_tokens(user),
        "total_tokens": est_tokens(prompt) + est_tokens(user),
        "unbatched_estimate": len(cases) * (est_tokens(prompt) + 50),
    }
    return (parsed or {}), meta


async def extractor_batch(
    caller: Caller, cases: list[dict]
) -> tuple[dict[str, dict], dict]:
    payload = json.dumps(
        [{"id": c["id"], "message": c["message"]} for c in cases],
        ensure_ascii=False,
        indent=1,
    )
    user = EXTRACTOR_BATCH_INSTRUCTION.format(payload=payload)
    prompt = prompts.kisna_entity_extractor
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user},
    ]
    raw = await caller.chat(messages, max_tokens=8000)
    ids = [c["id"] for c in cases]
    parsed = parse_results(raw, ids)
    if parsed is None:
        raw = await caller.chat(messages, max_tokens=8000)
        parsed = parse_results(raw, ids)
    meta = {
        "system_tokens": est_tokens(prompt),
        "batch_tokens": est_tokens(user),
        "total_tokens": est_tokens(prompt) + est_tokens(user),
        "unbatched_estimate": len(cases) * (est_tokens(prompt) + 50),
    }
    return (parsed or {}), meta


# ──────────────────────────────────────────────────────────────────────────
# individual re-verification (exact production message shape)
# ──────────────────────────────────────────────────────────────────────────
async def classifier_single(caller: Caller, case: dict, prompt: str) -> dict:
    profile = profile_for(case)
    from kisna_chatbot.utils.format_chathistory import format_recent_history_str

    history = format_recent_history_str(profile, 8)
    system_content = clf._build_classifier_system_content(
        profile, history, hint=clf._programmatic_intent_hint(case["message"])
    )
    raw = await caller.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"User Query: {case['message']}"},
        ],
        max_tokens=512,
    )
    try:
        return json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        return {"intent": "PARSE_FAILED", "entities": {}}


async def extractor_single(caller: Caller, case: dict) -> dict:
    raw = await caller.chat(
        [
            {"role": "system", "content": prompts.kisna_entity_extractor},
            {"role": "user", "content": case["message"]},
        ],
        max_tokens=400,
    )
    try:
        return json.loads(strip_fences(raw))
    except json.JSONDecodeError:
        return {}


# ──────────────────────────────────────────────────────────────────────────
# scoring
# ──────────────────────────────────────────────────────────────────────────
def production_entities(extractor: dict, classifier: dict | None) -> dict:
    """Merge exactly as product_search_agent_v3.py does.

    The context-free extractor is the single source of truth for every search
    filter; ``product_reference`` is the one field taken from the classifier,
    because resolving it legitimately needs the shown-products context
    (product_search_agent_v3.py:2052-2065).
    """
    merged = dict(extractor or {})
    ref = (classifier or {}).get("product_reference")
    if ref is not None and merged.get("product_reference") is None:
        merged["product_reference"] = ref
    return merged


def score_case(
    case: dict, intent: str, entities: dict, clf_entities: dict | None = None
) -> dict:
    entities = production_entities(entities, clf_entities)
    guarded = apply_production_guards(case["message"], intent, entities or {})
    ent_ok, ent_bad = entities_match(case.get("expect_entities") or {}, entities)
    # The classifier's OWN entity output — measured only so Stage 1 (which
    # removes it) can be judged against what it actually gave up.
    clf_ok, _ = entities_match(case.get("expect_entities") or {}, clf_entities or {})
    return {
        "intent": intent,
        "guarded_intent": guarded,
        "intent_ok": intent == case["expect_intent"],
        "guarded_ok": guarded == case["expect_intent"],
        "entities": {
            k: (entities or {}).get(k)
            for k in ENTITY_KEYS_CHECKED
            if (entities or {}).get(k) is not None
        },
        "entity_ok": ent_ok,
        "entity_mismatches": ent_bad,
        "classifier_entities": {
            k: (clf_entities or {}).get(k)
            for k in ENTITY_KEYS_CHECKED
            if (clf_entities or {}).get(k) is not None
        },
        "classifier_entity_ok": clf_ok,
        "classifier_emitted_entities": bool(clf_entities),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True, help="stage label, e.g. baseline")
    ap.add_argument(
        "--classifier-prompt",
        default=None,
        help="constant name in prompts.classifier_kisna (default: live CONTEXT)",
    )
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    prompt = (
        getattr(prompts, args.classifier_prompt)
        if args.classifier_prompt
        else clf.CONTEXT
    )
    prompt_name = args.classifier_prompt or "classifier.CONTEXT"

    cases = load_cases()
    caller = Caller()
    started = time.perf_counter()

    print(f"Regression: {args.label}")
    print(f"  classifier prompt : {prompt_name} ({est_tokens(prompt):,} est tokens)")
    print(
        f"  extractor prompt  : kisna_entity_extractor "
        f"({est_tokens(prompts.kisna_entity_extractor):,} est tokens)"
    )
    print(f"  cases             : {len(cases)}  runs: {args.runs}\n")

    runs: list[dict] = []
    for run_no in range(1, args.runs + 1):
        c_res, c_meta = await classifier_batch(caller, cases, prompt)
        e_res, e_meta = await extractor_batch(caller, cases)
        runs.append({"classifier": c_res, "extractor": e_res})
        print(
            f"  run {run_no}: classifier batch — system {c_meta['system_tokens']:,} + "
            f"batch {c_meta['batch_tokens']:,} = {c_meta['total_tokens']:,} tokens, "
            f"1 call (unbatched would be ~{c_meta['unbatched_estimate']:,} "
            f"tokens over {len(cases)} calls)"
        )
        print(
            f"          extractor  batch — system {e_meta['system_tokens']:,} + "
            f"batch {e_meta['batch_tokens']:,} = {e_meta['total_tokens']:,} tokens, "
            f"1 call (unbatched would be ~{e_meta['unbatched_estimate']:,} "
            f"tokens over {len(cases)} calls)"
        )
        if not c_res or not e_res:
            print("          WARNING: a batch failed id round-trip after retry")

    # per-case screening verdicts
    screened: dict[str, dict] = {}
    for case in cases:
        cid = case["id"]
        per_run = []
        for run in runs:
            c = run["classifier"].get(cid) or {}
            e = run["extractor"].get(cid) or {}
            intent = (c.get("intent") or "MISSING").strip().lower()
            ents = clf._sanitize_llm_entities(e.get("entities") or {})
            raw_clf_ents = c.get("entities")
            clf_ents = (
                clf._sanitize_llm_entities(raw_clf_ents) if raw_clf_ents else None
            )
            per_run.append(score_case(case, intent, ents, clf_ents))
        intents = {r["intent"] for r in per_run}
        ent_sigs = {json.dumps(r["entities"], sort_keys=True) for r in per_run}
        varied = len(intents) > 1 or len(ent_sigs) > 1
        all_pass = all(r["intent_ok"] and r["entity_ok"] for r in per_run)
        screened[cid] = {
            "runs": per_run,
            "varied": varied,
            "all_pass": all_pass,
            "needs_verify": varied or not all_pass,
        }

    to_verify = [c for c in cases if screened[c["id"]]["needs_verify"]]
    print(
        f"\n  screening done — {len(to_verify)} case(s) need individual "
        f"re-verification ({len(cases) - len(to_verify)} passed identically "
        f"{args.runs}x)\n"
    )

    verified: dict[str, dict] = {}
    for case in to_verify:
        cid = case["id"]
        c_raw = await classifier_single(caller, case, prompt)
        e_raw = await extractor_single(caller, case)
        intent = (c_raw.get("intent") or "MISSING").strip().lower()
        ents = clf._sanitize_llm_entities(e_raw or {})
        raw_clf_ents = c_raw.get("entities")
        clf_ents = clf._sanitize_llm_entities(raw_clf_ents) if raw_clf_ents else None
        verified[cid] = score_case(case, intent, ents, clf_ents)

    # final rows: individual where re-verified, batched (run 1) otherwise
    rows: list[dict] = []
    disagreements: list[dict] = []
    for case in cases:
        cid = case["id"]
        scr = screened[cid]
        if cid in verified:
            final = verified[cid]
            source = "individual"
            batched_intent = scr["runs"][0]["intent"]
            if batched_intent != final["intent"]:
                disagreements.append(
                    {
                        "id": cid,
                        "batched_intent": batched_intent,
                        "individual_intent": final["intent"],
                    }
                )
        else:
            final = scr["runs"][0]
            source = "batched"
        rows.append(
            {
                "id": cid,
                "bucket": case["bucket"],
                "message": case["message"],
                "expect_intent": case["expect_intent"],
                "expect_entities": case.get("expect_entities") or {},
                "source": source,
                "varied_across_runs": scr["varied"],
                **final,
            }
        )

    def pct(sel, key) -> float:
        rs = [r for r in rows if sel(r)]
        return round(100 * sum(bool(r[key]) for r in rs) / len(rs), 1) if rs else 0.0

    overall = {
        "intent_pct": pct(lambda r: True, "intent_ok"),
        "guarded_intent_pct": pct(lambda r: True, "guarded_ok"),
        "entity_pct": pct(lambda r: True, "entity_ok"),
        "classifier_entity_pct": pct(lambda r: True, "classifier_entity_ok"),
        "classifier_emitted_entities_n": sum(
            bool(r["classifier_emitted_entities"]) for r in rows
        ),
        "overall_pct": round(
            100
            * sum(bool(r["intent_ok"] and r["entity_ok"]) for r in rows)
            / len(rows),
            1,
        ),
    }
    buckets = {}
    for b in BUCKET_ORDER:
        sel = lambda r, b=b: r["bucket"] == b  # noqa: E731
        brows = [r for r in rows if sel(r)]
        buckets[b] = {
            "n": len(brows),
            "intent_pct": pct(sel, "intent_ok"),
            "guarded_intent_pct": pct(sel, "guarded_ok"),
            "entity_pct": pct(sel, "entity_ok"),
            "classifier_entity_pct": pct(sel, "classifier_entity_ok"),
            "overall_pct": round(
                100
                * sum(bool(r["intent_ok"] and r["entity_ok"]) for r in brows)
                / len(brows),
                1,
            )
            if brows
            else 0.0,
        }

    report = {
        "label": args.label,
        "classifier_prompt": prompt_name,
        "classifier_prompt_tokens": est_tokens(prompt),
        "entity_extractor_tokens": est_tokens(prompts.kisna_entity_extractor),
        "model": caller.model,
        "runs": args.runs,
        "cases": len(cases),
        "api_calls": caller.calls,
        "api_prompt_tokens": caller.prompt_tokens,
        "api_completion_tokens": caller.completion_tokens,
        "elapsed_s": round(time.perf_counter() - started, 1),
        "overall": overall,
        "buckets": buckets,
        "nondeterministic": [r["id"] for r in rows if r["varied_across_runs"]],
        "batch_vs_individual_disagreements": disagreements,
        "results": rows,
    }

    out = AUDIT_DIR / f"regression_{args.label}.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 78)
    print(
        f"OVERALL  intent {overall['intent_pct']}%  "
        f"(with production guards {overall['guarded_intent_pct']}%)  |  "
        f"entities {overall['entity_pct']}%  |  end-to-end {overall['overall_pct']}%"
    )
    print("-" * 78)
    print(
        f"classifier-emitted entities: {overall['classifier_entity_pct']}% correct "
        f"({overall['classifier_emitted_entities_n']}/{len(rows)} cases got any)"
    )
    print("-" * 78)
    print(
        f"{'bucket':<12} {'n':>3}  {'intent':>7} {'guarded':>8} {'entity':>7} "
        f"{'e2e':>7} {'clf-ent':>8}"
    )
    for b, v in buckets.items():
        print(
            f"{b:<12} {v['n']:>3}  {v['intent_pct']:>6}% {v['guarded_intent_pct']:>7}% "
            f"{v['entity_pct']:>6}% {v['overall_pct']:>6}% "
            f"{v['classifier_entity_pct']:>7}%"
        )
    print("-" * 78)
    fails = [r for r in rows if not (r["intent_ok"] and r["entity_ok"])]
    if fails:
        print(f"\nFAILURES ({len(fails)}):")
        for r in fails:
            why = []
            if not r["intent_ok"]:
                why.append(f"intent {r['intent']} != {r['expect_intent']}")
            why.extend(r["entity_mismatches"])
            print(f"  [{r['id']}] {r['message'][:44]!r} ({r['source']})")
            for w in why:
                print(f"        - {w}")
    bleed = [
        r
        for r in rows
        if r["classifier_emitted_entities"] and not r["classifier_entity_ok"]
    ]
    if bleed:
        print(
            f"\nCLASSIFIER ENTITY ERRORS ({len(bleed)}) — these are the entities "
            f"production already discards:"
        )
        for r in bleed:
            print(
                f"  [{r['id']}] {r['message'][:40]!r} -> {r['classifier_entities']} "
                f"(expected {r['expect_entities']})"
            )
    if report["nondeterministic"]:
        print(f"\nNONDETERMINISTIC across {args.runs} runs: "
              f"{', '.join(report['nondeterministic'])}")
    if disagreements:
        print(f"\nBATCH vs INDIVIDUAL disagreements ({len(disagreements)}):")
        for d in disagreements:
            print(
                f"  {d['id']}: batched={d['batched_intent']} "
                f"individual={d['individual_intent']} (individual is authoritative)"
            )
    print(
        f"\nAPI: {caller.calls} calls, {caller.prompt_tokens:,} prompt + "
        f"{caller.completion_tokens:,} completion tokens, {report['elapsed_s']}s"
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
