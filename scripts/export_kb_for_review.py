#!/usr/bin/env python3
"""Export what the bot actually reads -- KB V2, today's live campaigns and
the locked values -- to a Markdown document for client review.

    python scripts/export_kb_for_review.py [--date YYYY-MM-DD] [--out PATH]

Each block is taken from the same objects build_general_agent_prompt() uses,
and the script refuses to write unless every block appears word for word in
the assembled prompt for that date -- so the document cannot drift from the
bot. Nothing is sent anywhere.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

IST = timezone(timedelta(hours=5, minutes=30))


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


def _sections(text: str) -> list[tuple[str, str]]:
    """Split on '## ' headings -> [(title, body)], keeping sub-headings."""
    out = []
    for chunk in re.split(r"\n(?=## )", text.strip()):
        lines = chunk.strip().splitlines()
        if lines and lines[0].startswith("## "):
            out.append((lines[0][3:].strip(), "\n".join(lines[1:]).strip()))
        elif chunk.strip():
            out.append(("", chunk.strip()))
    return out


def build(today: date) -> str:
    from kisna_chatbot.prompts.general_agent_kisna import build_general_agent_prompt, build_locked_values
    from kisna_chatbot.prompts.kisna_knowledge_base import KISNA_KNOWLEDGE_BASE_V2, build_campaigns_block

    prompt = build_general_agent_prompt(today)
    kb = KISNA_KNOWLEDGE_BASE_V2
    campaigns = build_campaigns_block(today)
    locked = build_locked_values()
    for name, block in (("KB V2", kb), ("campaigns", campaigns), ("locked values", locked)):
        if block and block not in prompt:
            raise SystemExit(f"REFUSED: {name} is not verbatim in the assembled prompt for {today}")

    kb_sections = [(t, b) for t, b in _sections(kb) if t]
    lines = [
        "# KISNA chatbot knowledge — client review",
        "",
        f"Generated {datetime.now(IST):%d %B %Y, %H:%M IST} from code `{_git_sha()}`, "
        f"for conversations on **{today:%d %B %Y}**.",
        "",
        "This is exactly what the chatbot reads when it answers questions: the knowledge base, "
        "today's live campaigns and the fixed values it must quote word for word. Each block below "
        "was checked to appear verbatim in the bot's prompt. Lines starting \"Bot handling rule\" "
        "are instructions to the bot rather than customer-facing facts.",
        "",
        "Please mark anything that is wrong, missing or out of date.",
        "",
        "## Contents",
        "",
    ]
    lines += [f"{i}. {t}" for i, (t, _) in enumerate(kb_sections, 1)]
    lines += [f"{len(kb_sections) + 1}. Live campaigns (today)", f"{len(kb_sections) + 2}. Fixed values (quoted exactly)", ""]
    lines += ["---", "", "# Part 1 — Knowledge base", ""]
    for i, (title, body) in enumerate(kb_sections, 1):
        lines += [f"## {i}. {title}", "", body.replace("\n### ", "\n\n### "), ""]
    lines += ["---", "", "# Part 2 — Live campaigns (today)", ""]
    if campaigns:
        body = campaigns.split("\n", 1)[1].strip() if campaigns.startswith("#") else campaigns.strip()
        lines += [body, ""]
    else:
        lines += ["No live campaigns on this date.", ""]
    lines += ["---", "", "# Part 3 — Fixed values (the bot quotes these exactly)", "", locked.strip(), ""]
    return "\n".join(lines)


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today IST)")
    ap.add_argument("--out")
    args = ap.parse_args()
    today = date.fromisoformat(args.date) if args.date else datetime.now(IST).date()
    out = Path(args.out) if args.out else ROOT / "audit" / "kb_review" / f"KISNA_KB_client_review_{today:%Y-%m-%d}.md"
    text = build(today)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out} ({len(text):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
