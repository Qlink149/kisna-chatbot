"""Daily classifier health review from message_traces.

Reads the last N hours of message traces and reports:
  - intent distribution
  - low-confidence classifications (potential misroutes)
  - language distribution
  - language/script mismatches (user typed script X, reply language mirrors Y)
  - outcome distribution (handoffs, fallbacks, errors)

Usage:
    python scripts/daily_log_review.py                # last 24h, kisna
    python scripts/daily_log_review.py --hours 48
    python scripts/daily_log_review.py --client kisna --limit 5000
    python scripts/daily_log_review.py --json          # machine-readable

Read-only. Intended for a daily cron / manual spot-check.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter

# Reuse the bot's own env bootstrap so Mongo is configured identically.
from kisna_chatbot.utils import env_load  # noqa: F401
from kisna_chatbot.database.collections import message_traces

_INDIC_SCRIPT_RE = re.compile(r"[ऀ-ൿ]")
_LOW_CONFIDENCE = 0.55


def _script_of(text: str) -> str:
    """Coarse script bucket of a message: 'indic' | 'latin' | 'other'."""
    if not text:
        return "other"
    if _INDIC_SCRIPT_RE.search(text):
        return "indic"
    if re.search(r"[A-Za-z]", text):
        return "latin"
    return "other"


def _reply_language_script(language: str | None) -> str | None:
    """Expected reply script from the stored language code."""
    if not language:
        return None
    if language == "en" or language.endswith("-Latn"):
        return "latin"
    # hi/gu/mr/... native-script codes
    return "indic"


def _fetch(client_id: str, since_ts: int, limit: int) -> list[dict]:
    cursor = (
        message_traces.find(
            {"client_id": client_id, "ts": {"$gte": since_ts}},
            {"_id": 0},
        )
        .sort("ts", -1)
        .limit(limit)
    )
    return list(cursor)


def _analyze(docs: list[dict]) -> dict:
    intents = Counter()
    languages = Counter()
    outcomes = Counter()
    low_conf: list[dict] = []
    lang_mismatches: list[dict] = []
    missing_intent = 0

    for d in docs:
        intent = d.get("intent")
        intents[intent or "∅ (none)"] += 1
        if not intent:
            missing_intent += 1

        languages[d.get("language") or "∅"] += 1
        outcomes[d.get("outcome") or "∅"] += 1

        conf = d.get("confidence")
        if isinstance(conf, (int, float)) and conf < _LOW_CONFIDENCE:
            low_conf.append(
                {
                    "user_message": d.get("user_message", ""),
                    "intent": intent,
                    "confidence": round(conf, 2),
                }
            )

        # Language/script mismatch: user typed native script but reply mirrors
        # Latin (or vice-versa). Only flag when we have a reply preview to judge.
        user_script = _script_of(d.get("user_message", ""))
        want_script = _reply_language_script(d.get("language"))
        reply_preview = d.get("reply_preview") or ""
        reply_script = _script_of(reply_preview)
        if (
            want_script
            and user_script in ("indic", "latin")
            and reply_script in ("indic", "latin")
            and user_script != reply_script
        ):
            lang_mismatches.append(
                {
                    "user_message": d.get("user_message", "")[:60],
                    "user_script": user_script,
                    "language": d.get("language"),
                    "reply_script": reply_script,
                    "reply_preview": reply_preview[:60],
                }
            )

    return {
        "total": len(docs),
        "missing_intent": missing_intent,
        "intents": intents.most_common(),
        "languages": languages.most_common(),
        "outcomes": outcomes.most_common(),
        "low_confidence": low_conf,
        "language_mismatches": lang_mismatches,
    }


def _print_report(report: dict, hours: int) -> None:
    total = report["total"]
    print(f"\n=== KISNA classifier daily review — last {hours}h ===")
    print(f"Messages analyzed: {total}")
    if total == 0:
        print("No traces in window. (Is message_traces populated?)")
        return

    def _bar(count: int) -> str:
        width = int(round(30 * count / total))
        return "█" * width

    print("\n-- Intent distribution --")
    for intent, count in report["intents"]:
        print(f"  {intent:<18} {count:>5}  {_bar(count)}")
    if report["missing_intent"]:
        pct = 100 * report["missing_intent"] / total
        print(f"  ⚠ {report['missing_intent']} ({pct:.0f}%) had no intent recorded")

    print("\n-- Language distribution --")
    for lang, count in report["languages"]:
        print(f"  {lang:<10} {count:>5}  {_bar(count)}")

    print("\n-- Outcome distribution --")
    for outcome, count in report["outcomes"]:
        print(f"  {outcome:<18} {count:>5}  {_bar(count)}")

    low = report["low_confidence"]
    print(f"\n-- Low-confidence (<{_LOW_CONFIDENCE}) classifications: {len(low)} --")
    for row in low[:25]:
        print(
            f"  [{row['confidence']}] {row['intent'] or '∅':<14} "
            f"{row['user_message'][:60]!r}"
        )
    if len(low) > 25:
        print(f"  … and {len(low) - 25} more")

    mism = report["language_mismatches"]
    print(f"\n-- Language/script mismatches: {len(mism)} --")
    for row in mism[:25]:
        print(
            f"  user[{row['user_script']}] {row['user_message']!r} "
            f"→ lang={row['language']} reply[{row['reply_script']}] "
            f"{row['reply_preview']!r}"
        )
    if len(mism) > 25:
        print(f"  … and {len(mism) - 25} more")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily classifier log review")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--client", default="kisna")
    parser.add_argument("--limit", type=int, default=10000)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    args = parser.parse_args()

    since_ts = int(time.time()) - args.hours * 3600
    docs = _fetch(args.client, since_ts, args.limit)
    report = _analyze(docs)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        _print_report(report, args.hours)


if __name__ == "__main__":
    main()