#!/usr/bin/env python3
"""Mechanical defect scan over a loadtest_harness run.

Flags shapes that are wrong regardless of taste — it does not judge phrasing.

WHY IT TAKES THE INPUT FILE TOO. The harness does not copy ``lang`` into its
output, so an earlier version of this scanner read ``conversation["lang"]`` from
the RESULTS, always got "", and silently skipped every script and language check
in three consecutive sweeps — while reporting "0 foreign-script characters" as
though it had tested something. A check that cannot fail is worse than no check:
it manufactures confidence. ``lang`` is re-joined from the input file by id, and
the summary prints how many conversations actually carried one so a silent
regression to that state is visible.

Usage:
    python scripts/qa_scan.py <out.json> <in.json>
"""
from __future__ import annotations

import collections
import io
import json
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Each language's own script block.
SCRIPTS: dict[str, tuple[int, int]] = {
    "hi": (0x0900, 0x097F), "mr": (0x0900, 0x097F),
    "bn": (0x0980, 0x09FF), "as": (0x0980, 0x09FF),
    "pa": (0x0A00, 0x0A7F), "gu": (0x0A80, 0x0AFF),
    "or": (0x0B00, 0x0B7F), "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F), "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F), "ur": (0x0600, 0x06FF),
}

# Every script a reply might wrongly contain.
ALL_BLOCKS = [
    (0x0900, 0x097F), (0x0980, 0x09FF), (0x0A00, 0x0A7F), (0x0A80, 0x0AFF),
    (0x0B00, 0x0B7F), (0x0B80, 0x0BFF), (0x0C00, 0x0C7F), (0x0C80, 0x0CFF),
    (0x0D00, 0x0D7F), (0x0600, 0x06FF), (0x4E00, 0x9FFF), (0x3040, 0x30FF),
    (0x0400, 0x04FF), (0x0E00, 0x0E7F),
]

# Danda and the zero-width joiners are shared across Indic scripts — Bengali and
# Gurmukhi both end sentences with "।". Flagging them made clean replies look
# contaminated.
SHARED_CODEPOINTS = {0x0964, 0x0965, 0x200C, 0x200D}

# Hindi and Marathi share Devanagari; Bengali and Assamese share their block. No
# script check can separate them, so use function words that only one language
# uses. This is the ONLY way a wrong-language reply in the right script shows up.
MARKERS: dict[str, tuple[str, ...]] = {
    "hi": ("हूँ", "हूं", "क्या", "कीजिए", "आपको", "रहा है", "करता हूँ", "हैं।"),
    "mr": ("आहे", "आहात", "तुम्हाला", "करतो", "काय", "शोधतो", "मी "),
    "bn": ("আপনার", "করছি", "আছে", "কী", "আপনি"),
    "as": ("আপোনাৰ", "কৰিছো", "আছে", "মই", "আপুনি"),
}
SAME_SCRIPT_PAIRS = {"hi": "mr", "mr": "hi", "bn": "as", "as": "bn"}

# Latin that is SUPPOSED to survive translation: identifiers, units, the pinned
# metal names, and the phrase a customer must type back verbatim.
EXPECTED_LATIN = re.compile(
    r"(?:https?://\S+|kisna\.com|KISNA|Kisna|SKU|GST|IST|EMI|BIS|KMR|"
    r"\d+KT|gold|diamond|gemstone|silver|platinum|pearl|"
    r"I want to return my order|Buy on KISNA|SafeGold)",
    re.I,
)
LATIN_RUN = re.compile(r"(?:\b[A-Za-z][A-Za-z'’]*\b[ ,.:;!?-]+){5,}")

LEAK_TOKENS = (
    "system prompt", "You are the intent classifier", "gpt-4o", "gpt-5",
    "instruction:", "FACTS:", "_compose", "llm_extracted_entities",
)


def script_chars(text: str, lo: int, hi: int) -> int:
    return sum(1 for ch in text if lo <= ord(ch) <= hi)


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    out_path, in_path = sys.argv[1], sys.argv[2]
    rows = json.load(io.open(out_path, encoding="utf-8"))["results"]
    src = json.load(io.open(in_path, encoding="utf-8"))
    if isinstance(src, dict):
        src = src.get("conversations") or src.get("results") or []
    lang_by_id = {c["id"]: (c.get("lang") or "") for c in src}

    findings: dict[str, list] = collections.defaultdict(list)

    def flag(kind, cid, turn, detail):
        findings[kind].append((cid, turn, detail))

    for conv in rows:
        cid = conv["id"]
        lang = lang_by_id.get(cid, "")
        own = SCRIPTS.get(lang)

        for i, turn in enumerate(conv.get("turns", [])):
            reply = turn.get("reply") or ""
            if not reply.strip():
                flag("EMPTY REPLY", cid, i, "(blank)")
                continue

            # --- WhatsApp markdown -------------------------------------
            if reply.count("*") % 2:
                flag("UNBALANCED BOLD", cid, i, f"{reply.count('*')} asterisks")
            if "**" in reply:
                flag("MARKDOWN ** LEAKED", cid, i, reply[max(0, reply.find("**") - 25):][:60])

            # --- literal escape sequences -------------------------------
            for esc in ("\\n", "\\t", "\\u"):
                if esc in reply:
                    flag("LITERAL ESCAPE", cid, i, f"{esc!r} x{reply.count(esc)}")

            # --- script purity -----------------------------------------
            if own:
                bad = {
                    ch for ch in reply
                    if ord(ch) not in SHARED_CODEPOINTS
                    and not (own[0] <= ord(ch) <= own[1])
                    and any(lo <= ord(ch) <= hi for lo, hi in ALL_BLOCKS)
                }
                if bad:
                    flag("FOREIGN SCRIPT", cid, i, "".join(sorted(bad))[:24])

                # --- same script, wrong language -----------------------
                sibling = SAME_SCRIPT_PAIRS.get(lang)
                if sibling:
                    theirs = [m for m in MARKERS.get(sibling, ()) if m in reply]
                    ours = [m for m in MARKERS.get(lang, ()) if m in reply]
                    if theirs and not ours:
                        flag("WRONG LANGUAGE (same script)", cid, i,
                             f"{lang} reply carries {sibling} markers {theirs[:3]}")

                # --- canned English that never got translated ----------
                if script_chars(reply, own[0], own[1]) > 0:
                    # Blank the expected Latin FIRST. Searching for runs
                    # and stripping afterwards flagged the pinned phrase
                    # "I want to return my order" -- which must stay
                    # English -- because the run matched a truncated
                    # prefix of it that no longer contained the full
                    # phrase to strip.
                    residue = EXPECTED_LATIN.sub(" ", reply)
                    for run in LATIN_RUN.findall(residue):
                        if len(run.split()) >= 5:
                            flag("ENGLISH LEAK", cid, i, f"[{lang}] {run.strip()[:70]}")

            # --- duplicate / oversize / leakage -------------------------
            lines = [ln.strip() for ln in reply.split("\n") if ln.strip()]
            dupes = [x for x, n in collections.Counter(lines).items()
                     if n > 1 and len(x) > 25]
            if dupes:
                flag("DUPLICATE LINE", cid, i, dupes[0][:60])
            if len(reply) > 1600:
                flag("VERY LONG REPLY", cid, i, f"{len(reply)} chars")
            for token in LEAK_TOKENS:
                if token.lower() in reply.lower():
                    flag("POSSIBLE LEAK", cid, i, token)

    with_lang = sum(1 for c in rows if lang_by_id.get(c["id"]))
    print(f"scanned {len(rows)} conversations — {with_lang} carried a lang "
          f"(script/language checks only run on those)\n")
    if with_lang == 0:
        print("!! NO conversation had a lang: every script and language check "
              "was skipped. Add \"lang\" to the input fixtures.\n")
    if not findings:
        print("no mechanical defects found")
    for kind, items in sorted(findings.items(), key=lambda kv: -len(kv[1])):
        print(f"### {kind}  ({len(items)})")
        for cid, turn, detail in items[:8]:
            print(f"    {cid} turn{turn}: {detail}")
        if len(items) > 8:
            print(f"    ... and {len(items) - 8} more")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
