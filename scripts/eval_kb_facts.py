#!/usr/bin/env python3
"""KB fact eval: tests/fixtures/kb_fact_eval.json through the live GeneralAgent
prompt, ONE call per question (no batching), same request shape as
ai/openai_responses (instructions, tool, output schema, temperature). No side
effects: a live-agent tool call is answered locally; nothing is sent or saved.

    python scripts/eval_kb_facts.py [--runs 1] [--out results.json]

Per question: the row's must / any / must_not regexes, its optional
"handoff" (true/false: whether the live-agent tool must be called), plus the generic
checks (banned phrases incl. any pincode ask, unlocked % figures, the bot
naming itself, the VOICE opener; "empathy_ok" allows the empathy line
first; skipped for code-served client texts, which are verbatim by
requirement). A row with "history" ([{role, content}, ...]) is asked with that
chat history in front, as the live agent sees it -- used to check that an
older, different answer in the chat does not override today's. A row with
"intent" is checked at the
classifier instead (one LLM classification per run): order issues must route
there and never reach a KB answer. Prints every failure with the full answer.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / "tests" / "fixtures" / "kb_fact_eval.json"
MODEL = "gpt-4o-mini"

# ---------------------------------------------------------------- checks
PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
ALLOWED_PCT = {"95", "100", "90", "97", "25", "75", "50", "37.5", "91.6", "99.5"}
NEG = re.compile(r"\b(unable|not (?:currently )?(?:able|accept\w*|available|offer\w*|possible)|cannot|can't|don't|do not|no longer)\b", re.I)
VOICE_OPENERS = ("yes", "absolutely", "certainly", "no worries", "please note that", "currently")
HANDOFF = ("let me connect you with a kisna representative", "i'm connecting you", "i've connected you")
EMPATHY = "i'm sorry for the inconvenience"


def c_banned(a: str) -> list[str]:
    hits = []
    for pat, label in ((r"discreet", "discreet"), (r"next[- ]day", "next-day"),
                       (r"\bexpress\b", "express"), (r"My Orders", "My Orders")):
        for m in re.finditer(pat, a, re.I):
            window = a[max(0, m.start() - 80): m.end() + 80]
            if label in ("express", "next-day") and NEG.search(window):
                continue
            hits.append(label)
            break
    for sent in re.split(r"(?<=[.!?])\s+|\n+", a):
        if re.search(r"\bpin\s?-?code\b|\bpin\b", sent, re.I) and re.search(
            r"\b(share|provide|send|give|enter|tell|let me know|your|check|verify|look ?up|confirm|I can help|if you have)\b",
            sent, re.I,
        ):
            hits.append("asks for / offers to check a pincode")
            break
    if re.search(r"invest|store of value", a, re.I):
        hits.append("investment framing")
    return hits


def c_locked(a: str) -> list[str]:
    return [f"unlocked % figure {f}%" for f in PCT.findall(a) if f not in ALLOWED_PCT]


def c_name(a: str) -> list[str]:
    for m in re.finditer(r"\b(?:I am|I'm|my name is|this is)\s+([A-Z][A-Za-z]+)", a):
        if m.group(1) not in ("KIA", "Kisna", "KISNA", "Sorry", "Happy", "Here", "Glad", "Delighted"):
            return [f"self-named '{m.group(1)}'"]
    return []


def c_voice(a: str, tool: bool, empathy_ok: bool = False) -> list[str]:
    # empathy_ok: a row where VOICE's upset-customer rule puts the empathy
    # line first (e.g. a lost certificate).
    lead = re.sub(r"^[\W_]+", "", a, flags=re.U).lower()
    if tool and lead.startswith(HANDOFF):
        return []
    if empathy_ok and lead.startswith(EMPATHY):
        return ["contains 'Unfortunately'"] if re.search(r"\bunfortunately\b", a, re.I) else []
    if re.search(r"\bunfortunately\b", a, re.I):
        return ["contains 'Unfortunately'"]
    if re.match(r"no\b", lead) and not lead.startswith("no worries"):
        return ["opens with bare 'No'"]
    if not lead.startswith(VOICE_OPENERS):
        return [f"opener not a VOICE verdict: {lead[:45]!r}"]
    return []


def c_row(row: dict, a: str, tool: bool = False) -> list[str]:
    probs = []
    for rx in row.get("must", []):
        if not re.search(rx, a, re.I):
            probs.append(f"missing /{rx}/")
    anys = row.get("any", [])
    if anys and not any(re.search(rx, a, re.I) for rx in anys):
        probs.append(f"none of {anys}")
    for rx in row.get("must_not", []):
        if re.search(rx, a, re.I):
            probs.append(f"forbidden /{rx}/")
    if "handoff" in row and row["handoff"] != tool:
        probs.append("expected a live-agent handoff" if row["handoff"] else "handed off to a live agent")
    return probs


def _history_str(history: list | None) -> str:
    from kisna_chatbot.utils.format_chathistory import format_recent_history_str

    return format_recent_history_str({"chat_history": list(history or [])}, 8) if history else ""


async def classify(q: str, sem: asyncio.Semaphore, history: list | None = None) -> dict:
    from kisna_chatbot.processors.classifier import classify_query_for_audit, strip_list_number

    async with sem:
        got = await classify_query_for_audit(
            strip_list_number(q), {"chat_history": list(history or [])}, use_llm=True
        )
    return {"q": q, "a": f"[routed: {got.get('intent')}]", "intent": got.get("intent"), "tool": False}


# ------------------------------------------------------------------ ask
async def ask(q: str, instructions: str, sem: asyncio.Semaphore, history: list | None = None) -> dict:
    from kisna_chatbot.ai.config import GENERAL_AGENT_TEMPERATURE
    from kisna_chatbot.constants import KIA_HANDOFF_MESSAGE
    from kisna_chatbot.processors.code_served_facts import (
        CANCEL_ORDER_TEXT,
        EMI_BANKS_TEXT,
        KARAT_COMPARISON_TEXT,
        RING_FIT_TEXT,
        is_cancel_order_question,
        is_emi_banks_question,
        is_karat_comparison,
        is_ring_fit_question,
    )
    from kisna_chatbot.processors.general_agent import _replace_sentence_unfortunately
    from kisna_chatbot.prompts.general_agent_kisna import output_schema, request_live_agent_tool
    from kisna_chatbot.utils.get_openai_client import get_openai_client

    if is_karat_comparison(q):
        return {"q": q, "a": KARAT_COMPARISON_TEXT, "tool": False, "canned": True}
    if is_emi_banks_question(q):
        return {"q": q, "a": EMI_BANKS_TEXT, "tool": False, "canned": True}
    if is_ring_fit_question(q):
        return {"q": q, "a": RING_FIT_TEXT, "tool": False, "canned": True}
    if is_cancel_order_question(q):
        return {"q": q, "a": CANCEL_ORDER_TEXT, "tool": False, "canned": True}
    async with sem:
        messages = [
            {"role": "system", "content": "Username: Customer"},
            {"role": "system", "content": "Recent chat history:\n" + _history_str(history)},
            {"role": "user", "content": q},
        ]
        tool = False
        response = None
        for _ in range(3):
            response = await get_openai_client().responses.create(
                model=MODEL, instructions=instructions, input=messages,
                tools=[request_live_agent_tool], text=output_schema,
                max_output_tokens=1024, temperature=GENERAL_AGENT_TEMPERATURE,
            )
            calls = [i for i in response.output if i.type == "function_call"]
            if not calls:
                break
            for fc in calls:
                tool = True
                messages.append({"type": "function_call", "call_id": fc.call_id, "name": fc.name, "arguments": fc.arguments})
                messages.append({"type": "function_call_output", "call_id": fc.call_id, "output": json.dumps({"success": True})})
        msg = next((i for i in response.output if i.type == "message"), None)
        text = json.loads(msg.content[0].text).get("message", "") if msg and msg.content else ""
        shown = KIA_HANDOFF_MESSAGE if tool else _replace_sentence_unfortunately(text)
        if not tool:
            shown += "".join(f"\n[button: {u}]" for u in _cta_urls(q, text))
        return {"q": q, "a": shown, "tool": tool}


def _cta_urls(q: str, text: str) -> list[str]:
    """The CTA buttons GeneralAgent attaches after the model's text, with the
    same conditions (processors/general_agent.py). The customer sees these
    links; the model is told not to type them itself."""
    from kisna_chatbot.processors.classifier import _STORE_PICKUP_RE
    from kisna_chatbot.processors.general_agent import (
        DIGITAL_GOLD_URL,
        GRP_URL,
        KMR_URL,
        _DIGITAL_GOLD_RE,
        _GRP_RE,
        _KMR_RE,
    )

    urls = []
    if _DIGITAL_GOLD_RE.search(q) or _DIGITAL_GOLD_RE.search(text):
        urls.append(DIGITAL_GOLD_URL)
    grp = _GRP_RE.search(q) or _GRP_RE.search(text)
    if grp:
        urls.append(GRP_URL)
    if not grp and (_KMR_RE.search(q) or _KMR_RE.search(text)):
        urls.append(KMR_URL)
    if _STORE_PICKUP_RE.search(q):
        urls.append("https://www.kisna.com/store")
    from kisna_chatbot.processors.general_agent import (
        SAMPLE_CERTIFICATE_URL,
        _CERTIFICATE_PROBLEM_RE,
        _CERTIFICATE_RE,
    )

    if _CERTIFICATE_RE.search(q) and not _CERTIFICATE_PROBLEM_RE.search(q):
        urls.append(SAMPLE_CERTIFICATE_URL)
    return urls


async def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    from kisna_chatbot.prompts.general_agent_kisna import build_general_agent_prompt

    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out")
    ap.add_argument("--only", help="comma-separated question numbers (1-based)")
    args = ap.parse_args()

    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    picked = [int(x) for x in args.only.split(",")] if args.only else range(1, len(rows) + 1)
    # A row may carry "date": the prompt is built for that day (live
    # campaigns change by date -- e.g. GRP listed or not).
    prompts: dict[str, str] = {}

    def prompt_for(row: dict) -> str:
        key = row.get("date") or ""
        if key not in prompts:
            prompts[key] = build_general_agent_prompt(date.fromisoformat(key) if key else None)
        return prompts[key]

    sem = asyncio.Semaphore(4)
    results = []
    for run in range(args.runs):
        answers = await asyncio.gather(*(
            classify(rows[i - 1]["q"], sem, rows[i - 1].get("history")) if rows[i - 1].get("intent")
            else ask(rows[i - 1]["q"], prompt_for(rows[i - 1]), sem, rows[i - 1].get("history"))
            for i in picked
        ))
        for i, ans in zip(picked, answers):
            row = rows[i - 1]
            a = ans["a"]
            if row.get("intent"):
                ok = row["intent"] if isinstance(row["intent"], list) else [row["intent"]]
                problems = [] if ans["intent"] in ok else [f"routed to {ans['intent']!r}, expected {row['intent']!r}"]
            else:
                problems = c_row(row, a, ans["tool"]) + c_banned(a) + c_locked(a) + c_name(a) + ([] if ans.get("canned") else c_voice(a, ans["tool"], row.get("empathy_ok", False)))
            results.append({"run": run, "n": i, "topic": row["topic"], "q": row["q"] + (f" [as of {row['date']}]" if row.get("date") else ""), "a": a,
                            "tool": ans["tool"], "problems": problems})

    by_topic: dict[str, list[int]] = {}
    for r in results:
        t = by_topic.setdefault(r["topic"], [0, 0])
        t[0] += not r["problems"]
        t[1] += 1
    for topic, (ok, n) in by_topic.items():
        print(f"{topic:18} {ok}/{n}")
    fails = [r for r in results if r["problems"]]
    print(f"TOTAL {len(results) - len(fails)}/{len(results)} passed")
    for r in fails:
        print(f"\n--- run {r['run']} #{r['n']} [{r['topic']}] {r['q']}")
        print("    FAILED: " + "; ".join(r["problems"]))
        print("    " + r["a"].replace("\n", "\n    "))
    if args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
