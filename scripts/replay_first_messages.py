"""Classify the FIRST user message of every conversation in
tests/replay/real_conversations.json (plus, if given, extra corpora) and
write {conversation id, masked phone, message, intent, source} per row.

    python scripts/replay_first_messages.py --out routing.json [--corpus path ...] [--runs 3]

Run it once per checkout (PYTHONPATH) and diff the two outputs. Phones are
masked to the last 4 digits; nothing is sent anywhere but the LLM.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def mask(phone: str) -> str:
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    return f"xxxxxx{digits[-4:]}" if digits else ""


def first_messages(paths: list[pathlib.Path]) -> list[dict]:
    seen: set[str] = set()
    rows = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        for conv in data.get("conversations", []):
            turns = conv.get("turns") or []
            if not turns:
                continue
            key = conv.get("id") or f"{conv.get('phone')}:{conv.get('start_ts')}"
            if key in seen:
                continue
            seen.add(key)
            first = turns[0]
            rows.append(
                {
                    "id": key,
                    "phone": mask(conv.get("phone")),
                    "message": first.get("message") or "",
                    "prod_logged_intent": first.get("prod_intent"),
                }
            )
    return rows


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--corpus", action="append", default=[])
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()

    from kisna_chatbot.processors.classifier import classify_query_for_audit

    paths = [pathlib.Path(p) for p in args.corpus] or [ROOT / "tests" / "replay" / "real_conversations.json"]
    rows = first_messages(paths)
    for r in rows:
        got = []
        for _ in range(args.runs):
            res = await classify_query_for_audit(r["message"], use_llm=True)
            got.append(res.get("intent"))
        r["intents"] = dict(collections.Counter(got))
        r["intent"] = collections.Counter(got).most_common(1)[0][0]
    pathlib.Path(args.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(f"{r['phone']:>12} {r['intent']:<16} {r['intents']}  {r['message'][:70]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
