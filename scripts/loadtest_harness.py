#!/usr/bin/env python3
"""Batched live-replay harness for heavy end-to-end chatbot testing.

Runs whole multi-turn CONVERSATIONS through the real production pipeline
(real Classifier LLM call, real agents, real Clara API) exactly the way
main.process_message does, minus the WhatsApp send and the Mongo writes.

Design notes that matter:
  * UserRegistration is deliberately skipped. It would overwrite
    data["user_profile"] from Mongo on every turn. Instead each conversation
    carries its own in-memory profile dict forward, so sessions are isolated
    from each other AND from real users' Mongo state -- no test pollution.
  * localize_bot_responses IS run (it rewrites reply text/language, so
    skipping it would hide real bugs), and ResponseManager's WhatsApp
    markdown sanitizer is applied so `reply` is exactly the bytes a user
    would see on their phone.
  * Conversations run concurrently (bounded), turns within a conversation
    strictly in order -- that is the only ordering the real system promises.

Input JSON (a list, or {"conversations": [...]}) :
    [
      {"id": "budget_range_gujarati",
       "note": "optional free text for the report",
       "turns": [
          "મારે ₹10,000 થી ₹30,000 વચ્ચેનું મંગળસૂત્ર જોઈએ છે",   # plain text turn
          {"tap": "Under ₹25,000"},   # quick-reply tap, matched by title
          {"tap": 0},                       # or by option index
          {"text": "under 20k"}
       ]}
    ]

Usage:
    python scripts/loadtest_harness.py <in.json> <out.json> [--concurrency N]
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import os
import sys
import time
import traceback
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_WEBHOOK_SECRET", "test-secret")
# The pipeline logs a full JSON blob per processor; at DEBUG a 60-conversation
# run buries the summary line under megabytes of noise. Everything worth
# inspecting lands in the output JSON instead.
os.environ["LOG_LEVEL"] = os.getenv("HARNESS_LOG_LEVEL", "ERROR")

from kisna_chatbot.main import app  # noqa: F401,E402  (must be first — breaks a circular import)
from kisna_chatbot.integrations import clara_filters  # noqa: E402
from kisna_chatbot.pipelines.inference_pipeline import (  # noqa: E402
    CallbackAgent,
    Classifier,
    ComplaintAgent,
    ServiceList,
)
from kisna_chatbot.pipelines.pipeline import Pipeline  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    _prepend_flow_switch_ack,
    _restore_wizard_after_safe_detour,
)
from kisna_chatbot.processors.secondary_intent import (  # noqa: E402
    append_secondary_answer,
)
from kisna_chatbot.processors.response_manager import _sanitize_response_text  # noqa: E402
from kisna_chatbot.config.clients import get_client_config  # noqa: E402
from kisna_chatbot.database.db_utils import MAX_CHAT_HISTORY  # noqa: E402
from kisna_chatbot.utils.format_chathistory import (  # noqa: E402
    format_chat_history,
    trim_chat_history,
)
from kisna_chatbot.utils.logger_config import logger  # noqa: E402
from kisna_chatbot.utils.reply_composer import localize_bot_responses  # noqa: E402
import kisna_chatbot.main as main_mod  # noqa: E402


class HarnessInitialPipeline(Pipeline):
    """InitialPipeline minus UserRegistration (see module docstring)."""

    def __init__(self) -> None:
        super().__init__([CallbackAgent(), ComplaintAgent(), Classifier(), ServiceList()])


def _render(bot_response: list) -> list[dict]:
    """Flatten bot_response into what the user actually perceives."""
    out = []
    for r in bot_response or []:
        t = r.get("type")
        if t == "text":
            out.append({"kind": "text", "text": r.get("text") or ""})
        elif t == "quickreply":
            out.append(
                {
                    "kind": "quickreply",
                    "text": r.get("text") or "",
                    "msgid": r.get("msgid"),
                    "options": [o.get("title") for o in (r.get("options") or [])],
                }
            )
        elif t == "image_with_cta":
            out.append(
                {
                    "kind": "product_card",
                    "title": r.get("title") or "",
                    "caption": (r.get("caption") or "")[:300],
                    "url": r.get("cta_url") or r.get("url") or "",
                }
            )
        elif t == "list":
            out.append(
                {
                    "kind": "list",
                    "text": r.get("text") or r.get("body") or "",
                    "options": [
                        i.get("title")
                        for sec in (r.get("sections") or [])
                        for i in (sec.get("rows") or sec.get("items") or [])
                    ],
                }
            )
        elif t == "flow":
            out.append({"kind": "flow", "text": r.get("text") or r.get("body") or ""})
        elif t == "cta_url":
            out.append(
                {
                    "kind": "cta_url",
                    "text": r.get("text") or "",
                    "cta": r.get("display_text") or "",
                    "url": r.get("url") or "",
                }
            )
        elif t == "media":
            out.append({"kind": "media", "text": r.get("caption") or "", "url": r.get("url") or ""})
        elif t == "skip":
            continue
        else:
            out.append({"kind": t or "unknown", "raw": {k: v for k, v in r.items() if k != "options"}})
    return out


def _user_text(rendered: list[dict]) -> str:
    """The concatenated text a human would read, for assertion purposes."""
    parts = []
    for r in rendered:
        if r["kind"] in ("text", "quickreply", "flow", "cta_url", "media", "list"):
            parts.append(r.get("text") or "")
        elif r["kind"] == "product_card":
            parts.append(f"[{r['title']}] {r.get('caption','')}")
    return "\n".join(p for p in parts if p)


def _pick_tap(prev_rendered: list[dict], want) -> dict | None:
    """Build the interactive payload for tapping a quick reply / list row."""
    for r in prev_rendered:
        if r["kind"] not in ("quickreply", "list"):
            continue
        options = r.get("options") or []
        if not options:
            continue
        title = None
        if isinstance(want, int):
            if 0 <= want < len(options):
                title = options[want]
        else:
            for o in options:
                if o and str(want).strip().lower() == str(o).strip().lower():
                    title = o
                    break
            if title is None:
                for o in options:
                    if o and str(want).strip().lower() in str(o).strip().lower():
                        title = o
                        break
        if title is None:
            continue
        if r["kind"] == "quickreply":
            return {"type": "button_reply", "button_reply": {"id": r.get("msgid"), "title": title}}
        return {"type": "list_reply", "list_reply": {"id": r.get("msgid") or title, "title": title}}
    return None


async def _one_turn(phone: str, profile: dict, *, text=None, interactive=None) -> dict:
    """Mirror of main.process_message's core, without send/persist."""
    messages: dict = {"id": f"harness-{uuid.uuid4().hex[:12]}"}
    if text is not None:
        messages["type"] = "text"
        messages["text"] = {"body": text}
    if interactive is not None:
        messages["type"] = "interactive"
        messages["interactive"] = interactive

    data = {
        "phone_number": phone,
        "messages": messages,
        "whatsapp_username": "Tester",
        "client_id": "kisna",
        "client_config": get_client_config("kisna"),
        "app_state": None,
        "request_id": messages["id"],
        "user_profile": profile,
    }

    data = await HarnessInitialPipeline().run(data=data)

    if "bot_response" not in data:
        service_selected = (data.get("user_profile") or {}).get("service_selected", "")
        pipeline = main_mod._pipeline_for_service(service_selected)
        if pipeline:
            data = await pipeline.run(data=data)
        if "bot_response" not in data:
            from kisna_chatbot.models.service_list import ServiceList as SL
            from kisna_chatbot.processors.general_agent import GeneralAgent

            data["user_profile"]["service_selected"] = SL.GENERAL.value
            data = await GeneralAgent().process(data)

    if "bot_response" in data:
        _prepend_flow_switch_ack(data)
        _restore_wizard_after_safe_detour(data)
        # Mirrors main.py: a second request made in the same message is
        # answered (or acknowledged) BEFORE localisation, so the appended
        # line is translated with the rest. Omitting it here made the
        # harness report multi-intent as still broken after it was fixed.
        await append_secondary_answer(data)
        await localize_bot_responses(data)
        data["bot_response"] = [_sanitize_response_text(r) for r in data["bot_response"]]

    _append_chat_history(data)
    return data


def _append_chat_history(data: dict) -> None:
    """Grow user_profile["chat_history"] the way production does.

    In production this happens ONLY inside db_utils.save_to_mongo, which this
    harness deliberately skips (no test writes to Mongo). Without it every turn
    saw an empty history, which silently changed real behaviour rather than just
    omitting a field: the classifier reads history in a dozen places, and
    product_search_agent_v3's `if len(history) == 0` re-emitted the KIA welcome
    on EVERY product turn -- a phantom "greeting spam" bug that does not exist
    in production. Reuses the real formatter/trimmer so the shape cannot drift.
    """
    profile = data.get("user_profile")
    if not isinstance(profile, dict):
        return
    try:
        new_chat = format_chat_history(
            user=data.get("messages"),
            assistant=data.get("bot_response"),
            phone_number=data.get("phone_number"),
            request_id=data.get("request_id"),
        )
    except Exception:
        logger.warning("harness: chat_history append failed", exc_info=True)
        return
    profile["chat_history"] = trim_chat_history(
        (profile.get("chat_history") or []) + (new_chat or []), MAX_CHAT_HISTORY
    )


def _profile_snapshot(profile: dict) -> dict:
    """Point-in-time copy of the state worth reviewing.

    Must deep-copy: the pipeline mutates shopping_wizard_data / last_search_filters
    IN PLACE across turns, so storing references made every earlier turn display
    the run's FINAL state -- per-turn state was unreadable and any conclusion
    drawn about when a slot was lost was wrong.
    """
    keys = (
        "service_selected",
        "reply_language",
        "last_search_filters",
        "shopping_wizard_active",
        "shopping_wizard_data",
        "shopping_wizard_explicit",
        "pending_confirmation",
        "awaiting_clarification",
        "last_shown_products",
        "last_viewed_product",
        "last_search_products",
    )
    snap = {}
    for k in keys:
        if k in profile:
            v = profile[k]
            if k in ("last_search_products",) and isinstance(v, list):
                v = f"<{len(v)} products>"
            elif k == "last_viewed_product" and isinstance(v, dict):
                v = v.get("title") or "<product>"
            elif k == "last_shown_products" and isinstance(v, list):
                v = [str(p.get("title") if isinstance(p, dict) else p)[:60] for p in v][:5]
            snap[k] = copy.deepcopy(v)
    return snap


async def run_conversation(convo: dict, sem: asyncio.Semaphore) -> dict:
    conv_id = convo.get("id") or uuid.uuid4().hex[:8]
    phone = convo.get("phone") or f"9199{abs(hash(conv_id)) % 100000000:08d}"
    profile: dict = dict(convo.get("initial_profile") or {})
    profile.setdefault("phone_number", phone)
    profile.setdefault("client_id", "kisna")
    profile.setdefault("service_selected", "")
    profile.setdefault("chat_history", [])
    profile.setdefault("shown_product_ids", [])

    turns_out = []
    prev_rendered: list[dict] = []
    async with sem:
        for idx, raw in enumerate(convo.get("turns") or []):
            spec = {"text": raw} if isinstance(raw, str) else dict(raw)
            text = spec.get("text")
            tap = spec.get("tap")
            interactive = None
            skipped = None
            if tap is not None:
                interactive = _pick_tap(prev_rendered, tap)
                if interactive is None:
                    skipped = f"no matching option for tap={tap!r}; options were {[r.get('options') for r in prev_rendered if r.get('options')]}"
                    text = spec.get("fallback_text") or (tap if isinstance(tap, str) else None)
                    if text is None:
                        turns_out.append({"i": idx, "input": spec, "error": skipped})
                        continue

            t0 = time.perf_counter()
            try:
                data = await _one_turn(phone, profile, text=text, interactive=interactive)
                rendered = _render(data.get("bot_response") or [])
                profile = data.get("user_profile") or profile
                turns_out.append(
                    {
                        "i": idx,
                        "input": {"text": text, "tap": tap},
                        "tap_note": skipped,
                        "ms": int((time.perf_counter() - t0) * 1000),
                        "intent": data.get("classified_category"),
                        "confidence": data.get("classifier_confidence"),
                        "service_selected": (data.get("user_profile") or {}).get("service_selected"),
                        "entities": data.get("llm_extracted_entities") or data.get("entities"),
                        "search_params": data.get("clara_params") or data.get("search_params"),
                        "total_count": data.get("total_count"),
                        "reply": _user_text(rendered),
                        "rendered": rendered,
                        "profile": _profile_snapshot(profile),
                    }
                )
                prev_rendered = rendered
            except Exception as e:
                turns_out.append(
                    {
                        "i": idx,
                        "input": {"text": text, "tap": tap},
                        "ms": int((time.perf_counter() - t0) * 1000),
                        "EXCEPTION": f"{type(e).__name__}: {e}",
                        "traceback": traceback.format_exc()[-1500:],
                    }
                )
                prev_rendered = []

    return {"id": conv_id, "phone": phone, "note": convo.get("note"), "turns": turns_out}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()

    payload = json.loads(Path(args.infile).read_text(encoding="utf-8"))
    conversations = payload["conversations"] if isinstance(payload, dict) else payload

    await clara_filters.warm_filters_cache()

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.perf_counter()
    results = await asyncio.gather(*(run_conversation(c, sem) for c in conversations))
    elapsed = time.perf_counter() - t0

    turn_count = sum(len(r["turns"]) for r in results)
    errors = sum(1 for r in results for t in r["turns"] if t.get("EXCEPTION"))
    out = {
        "conversations": len(results),
        "turns": turn_count,
        "exceptions": errors,
        "elapsed_s": round(elapsed, 1),
        "results": results,
    }
    Path(args.outfile).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(
        f"ran {len(results)} conversations / {turn_count} turns in {elapsed:.0f}s "
        f"({errors} exceptions) -> {args.outfile}"
    )


if __name__ == "__main__":
    asyncio.run(main())
