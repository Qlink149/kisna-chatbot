#!/usr/bin/env python3
"""Render a loadtest_harness.py output JSON as a compact, readable transcript.

Reading the raw JSON costs an enormous amount of context; this prints only
what a reviewer needs to judge each turn: what the user said, what the bot
actually replied, and the routing/entity state behind it.

Usage:
    python scripts/loadtest_view.py out.json [--id substr] [--full] [--width N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("outfile")
    ap.add_argument("--id", default="", help="only conversations whose id contains this")
    ap.add_argument("--full", action="store_true", help="do not truncate reply text")
    ap.add_argument("--width", type=int, default=420, help="reply truncation width")
    args = ap.parse_args()

    data = json.loads(Path(args.outfile).read_text(encoding="utf-8"))
    print(
        f"# {data['conversations']} conversations / {data['turns']} turns / "
        f"{data['exceptions']} exceptions / {data['elapsed_s']}s\n"
    )

    for conv in data["results"]:
        if args.id and args.id.lower() not in conv["id"].lower():
            continue
        print("=" * 78)
        print(f"CONV {conv['id']}" + (f"   — {conv['note']}" if conv.get("note") else ""))
        print("=" * 78)
        for t in conv["turns"]:
            if t.get("error"):
                print(f"  !! turn {t['i']} skipped: {t['error']}")
                continue
            inp = t["input"]
            label = f"tap[{inp['tap']!r}]" if inp.get("tap") is not None else repr(inp.get("text"))
            print(f"\nUSER  {label}")
            if t.get("tap_note"):
                print(f"      (tap fell back to text: {t['tap_note'][:110]})")
            if t.get("EXCEPTION"):
                print(f"  *** EXCEPTION: {t['EXCEPTION']}")
                print("  " + (t.get("traceback") or "").replace("\n", "\n  ")[-900:])
                continue
            meta = [
                f"intent={t.get('intent')}",
                f"conf={t.get('confidence')}",
                f"svc={t.get('service_selected')}",
                f"{t.get('ms')}ms",
            ]
            if t.get("total_count") is not None:
                meta.append(f"total={t['total_count']}")
            print("      " + "  ".join(str(m) for m in meta))
            ents = {k: v for k, v in (t.get("entities") or {}).items() if v not in (None, "", False, [])}
            if ents:
                print(f"      entities={json.dumps(ents, ensure_ascii=False)}")
            prof = t.get("profile") or {}
            interesting = {
                k: v
                for k, v in prof.items()
                if k
                in (
                    "last_search_filters",
                    "shopping_wizard_active",
                    "shopping_wizard_data",
                    "reply_language",
                    "pending_confirmation",
                )
                and v not in (None, "", False, [], {})
            }
            if interesting:
                print(f"      state={json.dumps(interesting, ensure_ascii=False, default=str)}")
            reply = t.get("reply") or "(no reply)"
            if not args.full and len(reply) > args.width:
                reply = reply[: args.width] + f" …(+{len(reply)-args.width} chars)"
            print("BOT   " + reply.replace("\n", "\n      "))
            for r in t.get("rendered") or []:
                if r["kind"] == "quickreply":
                    print(f"      [buttons: {r.get('options')}]")
                elif r["kind"] == "list":
                    print(f"      [list: {(r.get('options') or [])[:8]}]")
                elif r["kind"] == "flow":
                    print("      [FLOW form sent]")
        print()


if __name__ == "__main__":
    main()
