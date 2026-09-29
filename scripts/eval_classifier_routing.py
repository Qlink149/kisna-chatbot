"""Per-intent routing accuracy on tests/fixtures/classifier_routing_labelled.json.

Live LLM (the configured classifier provider/model -- the same code path prod
runs). Each row goes through classify_query_for_audit: shortcuts, the regex
overrides, then the LLM. A row passes when the intent is one of `expected`.

    python scripts/eval_classifier_routing.py --out result.json [--runs 1]

Point PYTHONPATH at another checkout to measure that code (before/after).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "classifier_routing_labelled.json"


async def _classify(sem, text):
    from kisna_chatbot.processors.classifier import classify_query_for_audit

    async with sem:
        try:
            r = await classify_query_for_audit(text, use_llm=True)
            return r.get("intent"), r.get("source")
        except Exception as e:  # noqa: BLE001
            return f"error:{type(e).__name__}", "error"


_BATCH_INSTRUCTION = """

## BATCH MODE (evaluation only)
The user message is a JSON object: {"<id>": {"text": "<customer message>", "hint": "<routing hint or null>"}, ...}.
Classify EACH message independently, exactly as the rules above say, as if it
were the only message (no chat history). Do not let one message influence another.
Return ONE JSON object and nothing else, with every id present:
{"<id>": {"intent": "<intent_name>", "confidence": <0.0-1.0>}, ...}
"""


async def _classify_batch(texts: list[str], batch_size: int) -> list[tuple[str, str]]:
    """Batch mode: regex shortcuts/overrides locally (no LLM, same as prod),
    then ONE LLM call per `batch_size` remaining messages, sent as a JSON
    object and answered as a JSON object. Same classifier prompt as prod."""
    from kisna_chatbot.ai import complete_chat
    from kisna_chatbot.ai.types import AgentName
    from kisna_chatbot.processors import classifier as clf

    out: dict[int, tuple[str, str]] = {}
    pending: list[int] = []
    for i, t in enumerate(texts):
        r = await clf.classify_query_for_audit(t, use_llm=False)
        if r.get("intent") != "unknown":
            out[i] = (r["intent"], r["source"])
        else:
            pending.append(i)

    system = clf._build_classifier_system_content({"chat_history": []}, "", hint=None) + _BATCH_INSTRUCTION
    for start in range(0, len(pending), batch_size):
        chunk = pending[start : start + batch_size]
        payload = {
            f"q{i}": {"text": texts[i], "hint": clf._programmatic_intent_hint(texts[i])}
            for i in chunk
        }
        parsed: dict = {}
        for _attempt in range(3):
            try:
                raw = await complete_chat(
                    agent=AgentName.CLASSIFIER,
                    agent_display_name="Classifier Agent (batch eval)",
                    instruction=clf.CONTEXT,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    max_output_tokens=60 * len(chunk) + 200,
                )
                text = raw.strip()
                text = text[text.find("{") : text.rfind("}") + 1]
                parsed = json.loads(text)
                break
            except Exception:  # noqa: BLE001 -- retry the batch
                await asyncio.sleep(2)
        for i in chunk:
            item = parsed.get(f"q{i}") or {}
            intent = item.get("intent") or "missing"
            source = "llm_batch"
            # Same post-LLM guard classify_query_for_audit applies.
            t = texts[i]
            if (
                clf._STORE_LOOKUP_RE.search(t)
                and not (clf._CATEGORY_WORD_RE.search(t) and clf._BROWSE_ACTION_RE.search(t))
                and intent in ("product_search", "product_info", "general", "menu_help", "greeting")
            ):
                intent, source = "store_info", "store_guard"
            out[i] = (intent, source)
    return [out[i] for i in range(len(texts))]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument(
        "--batch",
        type=int,
        default=0,
        help="N>0: one LLM call per N messages (JSON object in/out) instead of one per message",
    )
    args = ap.parse_args()

    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    sem = asyncio.Semaphore(args.concurrency)
    results = []
    for run in range(args.runs):
        if args.batch > 0:
            got = await _classify_batch([r["text"] for r in rows], args.batch)
        else:
            got = await asyncio.gather(*(_classify(sem, r["text"]) for r in rows))
        for r, (intent, source) in zip(rows, got):
            results.append(
                {
                    "run": run,
                    "text": r["text"],
                    "expected": r["expected"],
                    "tags": r["tags"],
                    "intent": intent,
                    "source": source,
                    "ok": intent in r["expected"],
                }
            )

    per_intent = defaultdict(lambda: [0, 0])
    per_tag = defaultdict(lambda: [0, 0])
    for x in results:
        key = x["expected"][0]
        per_intent[key][0] += x["ok"]
        per_intent[key][1] += 1
        for t in x["tags"] or ["untagged"]:
            per_tag[t][0] += x["ok"]
            per_tag[t][1] += 1
    summary = {
        "total": len(results),
        "correct": sum(x["ok"] for x in results),
        "per_intent": {k: {"correct": c, "total": n, "acc": round(c / n, 3)} for k, (c, n) in sorted(per_intent.items())},
        "per_tag": {k: {"correct": c, "total": n, "acc": round(c / n, 3)} for k, (c, n) in sorted(per_tag.items())},
    }
    pathlib.Path(args.out).write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=1))
    for x in results:
        if not x["ok"]:
            print(f"MISS run{x['run']} {x['text']!r}: got {x['intent']} ({x['source']}), expected {x['expected']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
