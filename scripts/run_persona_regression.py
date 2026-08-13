"""Persona regression — drive the REAL pipeline, one message at a time.

Unlike run_classifier_regression.py (which batches prompts to score routing
cheaply), this runs each case through the actual Classifier processor exactly
as production does: pre-LLM shortcuts, universal escape gate, the classifier
call, the canonical entity extraction, and every post-LLM guard. One API path,
one message, one verdict — no batching, so nothing is masked.

Cases come from tests/persona_regression.json, built from the production
transcripts of three real users.

Usage:
    python scripts/run_persona_regression.py
    python scripts/run_persona_regression.py --runs 2 --only marathi,gujarati
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

# Pinned, not inherited — production runs OpenAI gpt-4o-mini.
os.environ["AI_PROVIDER"] = "openai"
os.environ["AI_PROVIDER_CLASSIFIER"] = "openai"
os.environ["AI_PROVIDER_GENERAL"] = "openai"
os.environ["OPENAI_CHAT_MODEL"] = "gpt-4o-mini"
for _k, _v in {
    "ENV_MODE": "dev",
    "MONGO_URI": "mongodb://localhost:27017",
    "JWT_SECRET_KEY": "test-jwt",
    "SYSTEM_API_KEY": "test-api",
    "KISNA_CLARA_BASE_URL": "https://clara.example.com",
    "CLARA_API_KEY": "test-clara-key",
    "GUPSHUP_APP_ID": "t",
    "GUPSHUP_TOKEN": "t",
    "GUPSHUP_APP_NAME": "t",
    "GUPSHUP_API_KEY": "t",
    "KISNA_PRODUCT_API": "https://example.com/p",
    "KISNA_OFFERS_API": "https://example.com/o",
    "KISNA_STORE_API": "https://example.com/s",
    "KISNA_VTIGER_BASE": "https://example.com/c",
    "KISNA_VTIGER_TOKEN": "t",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.main import app  # noqa: F401,E402  (env before imports)

import logging  # noqa: E402

logging.disable(logging.CRITICAL)

from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    read_context_free_entities,
)

CASES_PATH = ROOT / "tests" / "persona_regression.json"
AUDIT_DIR = ROOT / "audit"
AUDIT_DIR.mkdir(exist_ok=True)

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

# Intents the classifier resolves without ever calling the LLM. Recorded so a
# pass can be attributed to a shortcut rather than to routing quality.
SHORTCUT_CATEGORIES = {"greeting", "menu_help", "acknowledgement"}


def build_profile(case: dict) -> dict:
    ctx = case.get("context") or {}
    profile: dict = {
        "chat_history": [],
        "service_selected": "",
        "last_message_at": int(time.time()),
        "username": "Test User",
    }
    if ctx.get("active_search"):
        profile["chat_history"] = list(ACTIVE_SEARCH_HISTORY)
        profile["last_search_filters"] = dict(ACTIVE_SEARCH_FILTERS)
        profile["service_selected"] = "product_search"
    if ctx.get("store_wait"):
        profile["chat_history"] = list(STORE_WAIT_HISTORY)
        profile["awaiting_store_pincode"] = True
        profile["service_selected"] = "ad_flow"
    shown = ctx.get("shown_products")
    if shown:
        products = []
        for entry in shown:
            import re

            match = re.search(r"₹\s*([\d,]+)", entry)
            price = int(match.group(1).replace(",", "")) if match else 0
            title = re.sub(r"\s*₹\s*[\d,]+\s*$", "", entry).strip()
            products.append({"title": title, "price": {"finalPrice": price}})
        profile["last_search_products"] = products
    return profile


def entities_match(expected: dict, actual: dict) -> list[str]:
    actual = actual or {}
    bad = []
    for key, want in (expected or {}).items():
        got = actual.get(key)
        if want is None:
            if got is not None:
                bad.append(f"{key}: expected null, got {got!r}")
        elif got != want:
            bad.append(f"{key}: expected {want!r}, got {got!r}")
    return bad


async def run_case(case: dict) -> dict:
    profile = build_profile(case)
    data = {
        "phone_number": "919999999999",
        "messages": {"text": {"body": case["message"]}},
        "user_profile": profile,
        "client_id": "kisna",
    }
    started = time.perf_counter()
    error = None
    try:
        result = await Classifier().process(data)
    except Exception as exc:  # a crash is a test result, not a runner failure
        result = data
        error = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.perf_counter() - started) * 1000)

    intent = result.get("classified_category")
    entities = dict(result.get("llm_extracted_entities") or {})
    # The search agent reuses the classifier's context-free extraction; read it
    # the same way so entity assertions see what the search would see.
    stashed = read_context_free_entities(result, case["message"])
    if stashed:
        for key, value in stashed.items():
            if value is not None and entities.get(key) is None:
                entities[key] = value

    mismatches = entities_match(case.get("expect_entities") or {}, entities)
    intent_ok = intent == case["expect_intent"]
    return {
        "id": case["id"],
        "bucket": case["bucket"],
        "message": case["message"],
        "expect_intent": case["expect_intent"],
        "intent": intent,
        "intent_ok": intent_ok,
        "entities": {k: v for k, v in entities.items() if v is not None},
        "entity_mismatches": mismatches,
        "entity_ok": not mismatches,
        "passed": intent_ok and not mismatches,
        "shortcut": intent in SHORTCUT_CATEGORIES,
        "bot_replied": bool(result.get("bot_response")),
        "latency_ms": latency_ms,
        "error": error,
        "rationale": case.get("rationale", ""),
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="", help="comma-separated bucket filter")
    ap.add_argument("--label", default="persona")
    args = ap.parse_args()

    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    if args.only:
        wanted = {b.strip() for b in args.only.split(",")}
        cases = [c for c in cases if c["bucket"] in wanted]

    print(f"Persona regression — {len(cases)} cases x {args.runs} run(s)")
    print("Driving the real Classifier pipeline, one message per call.\n")

    all_runs: list[list[dict]] = []
    for run_no in range(1, args.runs + 1):
        rows = []
        for i, case in enumerate(cases, 1):
            rows.append(await run_case(case))
            if i % 10 == 0:
                print(f"  run {run_no}: {i}/{len(cases)}")
        all_runs.append(rows)

    final = all_runs[-1]
    varied = set()
    if len(all_runs) > 1:
        for idx in range(len(cases)):
            if len({r[idx]["intent"] for r in all_runs}) > 1:
                varied.add(cases[idx]["id"])

    by_bucket = defaultdict(list)
    for row in final:
        by_bucket[row["bucket"]].append(row)

    total_pass = sum(r["passed"] for r in final)
    print("\n" + "=" * 84)
    print(f"OVERALL {total_pass}/{len(final)} passed "
          f"({100 * total_pass / len(final):.1f}%)")
    print("-" * 84)
    print(f"{'bucket':<16}{'n':>4}{'intent':>9}{'entity':>9}{'pass':>8}")
    for bucket in sorted(by_bucket):
        rows = by_bucket[bucket]
        n = len(rows)
        print(
            f"{bucket:<16}{n:>4}"
            f"{100 * sum(r['intent_ok'] for r in rows) / n:>8.0f}%"
            f"{100 * sum(r['entity_ok'] for r in rows) / n:>8.0f}%"
            f"{100 * sum(r['passed'] for r in rows) / n:>7.0f}%"
        )
    print("-" * 84)

    fails = [r for r in final if not r["passed"]]
    if fails:
        print(f"\nFAILURES ({len(fails)}):")
        for r in fails:
            print(f"  [{r['id']}] {r['message'][:52]!r}")
            if not r["intent_ok"]:
                print(f"        intent: got {r['intent']}, want {r['expect_intent']}")
            for m in r["entity_mismatches"]:
                print(f"        {m}")
            if r["error"]:
                print(f"        ERROR {r['error']}")
            if r["rationale"]:
                print(f"        (expected because: {r['rationale']})")

    crashed = [r for r in final if r["error"]]
    if crashed:
        print(f"\nCRASHES ({len(crashed)}): "
              + ", ".join(r["id"] for r in crashed))
    if varied:
        print(f"\nNONDETERMINISTIC across {args.runs} runs: {', '.join(sorted(varied))}")

    lat = sorted(r["latency_ms"] for r in final)
    print(f"\nlatency p50 {lat[len(lat)//2]}ms  p90 {lat[int(len(lat)*0.9)]}ms  "
          f"max {lat[-1]}ms")
    print(f"shortcut-resolved (no LLM): {sum(r['shortcut'] for r in final)}/{len(final)}")

    out = AUDIT_DIR / f"regression_{args.label}.json"
    out.write_text(
        json.dumps(
            {
                "cases": len(final),
                "runs": args.runs,
                "passed": total_pass,
                "pass_pct": round(100 * total_pass / len(final), 1),
                "buckets": {
                    b: {
                        "n": len(rows),
                        "pass_pct": round(100 * sum(r["passed"] for r in rows) / len(rows), 1),
                    }
                    for b, rows in by_bucket.items()
                },
                "nondeterministic": sorted(varied),
                "results": final,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {out}")


if __name__ == "__main__":
    asyncio.run(main())
