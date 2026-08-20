#!/usr/bin/env python3
"""Pull recent-150 chat_messages per phone + join message_traces by request_id.

Join rules (strict — never positional / ts-order reply pairing):
  - Sort messages by (ts ASC, _id ASC) so equal-ts user/assistant stay stable.
  - Attach traces by request_id + client_id=kisna only.
  - Assistant content for a user turn is the chat_messages row with the SAME
    request_id (looked up by map), never session[i+1].
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=False)

from kisna_chatbot.database.database import db, ping_database

PHONES = ["916376925843", "918696979791"]
LIMIT = 150
OUT_DIR = ROOT / "audit" / "verification_raw"
MD_DIR = ROOT / "audit"
CLARA_RE = re.compile(
    r"GET\s+/api/v1/clara/products\s*\|\s*(.*?)\s*→\s*(\d+)\s*products",
    re.I,
)


def _fmt_ts(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _parse_clara(steps: list) -> tuple[str, str]:
    params, total = "", ""
    for s in steps or []:
        detail = s.get("detail") or ""
        m = CLARA_RE.search(detail)
        if m:
            return m.group(1).strip(), m.group(2)
        if "clara/products" in detail.lower() and not params:
            params = detail[:240]
    return params, total


def pull_phone(phone: str) -> dict:
    # Fetch newest LIMIT, then re-sort chronologically with _id tie-break.
    newest = list(
        db.chat_messages.find({"phone": phone}).sort([("ts", -1), ("_id", -1)]).limit(LIMIT)
    )
    msgs = sorted(newest, key=lambda m: (m.get("ts") or 0, str(m.get("_id"))))

    rids = [m.get("request_id") for m in msgs if m.get("request_id")]
    traces = {
        t["request_id"]: t
        for t in db.message_traces.find(
            {"request_id": {"$in": rids}, "client_id": "kisna"}
        )
    }

    # Map request_id → assistant content from THIS window (same request_id only).
    asst_by_rid: dict[str, str] = {}
    for m in msgs:
        rid = m.get("request_id")
        if rid and m.get("role") == "assistant":
            asst_by_rid.setdefault(rid, m.get("content") or "")

    turns = []
    user_missing = 0
    for m in msgs:
        rid = m.get("request_id")
        tr = traces.get(rid) if rid else None
        if m.get("role") == "user" and not tr:
            user_missing += 1
        clara_params, total_count = _parse_clara((tr or {}).get("steps") or [])
        paired_reply = asst_by_rid.get(rid) if (rid and m.get("role") == "user") else None
        turns.append(
            {
                "ts": m.get("ts"),
                "ts_iso": _fmt_ts(m.get("ts")),
                "role": m.get("role"),
                "content": m.get("content") or "",
                "request_id": rid,
                "intent": (tr or {}).get("intent"),
                "confidence": (tr or {}).get("confidence"),
                "outcome": (tr or {}).get("outcome"),
                "reply_preview": (tr or {}).get("reply_preview"),
                "paired_assistant_by_request_id": paired_reply,
                "clara_params": clara_params,
                "total_count": total_count,
                "steps": (tr or {}).get("steps") or [],
                "trace_missing": m.get("role") == "user" and not tr,
            }
        )

    return {
        "phone": phone,
        "message_count": len(msgs),
        "traces_joined_by_request_id": len(traces),
        "user_turns_missing_trace": user_missing,
        "ts_range": {
            "first": _fmt_ts(msgs[0]["ts"]) if msgs else "",
            "last": _fmt_ts(msgs[-1]["ts"]) if msgs else "",
        },
        "join_method": "request_id+client_id=kisna; sort=(ts,_id); no positional fallback",
        "turns": turns,
    }


def write_markdown(data: dict) -> None:
    phone = data["phone"]
    lines = [
        f"# Transcript — {phone} (recent {data['message_count']}, request_id join)",
        "",
        f"- Window: {data['ts_range']['first']} → {data['ts_range']['last']}",
        f"- Join: `{data['join_method']}`",
        f"- Traces joined: {data['traces_joined_by_request_id']}",
        f"- User turns missing trace: {data['user_turns_missing_trace']}",
        "",
        "| timestamp | dir | message | intent | conf | Clara | totalCount | outcome | paired_reply_head |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for t in data["turns"]:
        direction = "IN" if t["role"] == "user" else "OUT"
        msg = (t["content"] or "").replace("|", "\\|").replace("\n", " ")[:100]
        paired = ""
        if t["role"] == "user":
            paired = (t.get("paired_assistant_by_request_id") or "").replace("|", "\\|").replace(
                "\n", " "
            )[:80]
        gap = " TRACE_GAP" if t.get("trace_missing") else ""
        lines.append(
            f"| {t['ts_iso']} | {direction} | {msg} | {t.get('intent') or ''} | "
            f"{t.get('confidence') if t.get('confidence') is not None else ''} | "
            f"{(t.get('clara_params') or '')[:60]} | {t.get('total_count') or ''} | "
            f"{t.get('outcome') or ''}{gap} | {paired} |"
        )
    (MD_DIR / f"transcripts_{phone}_recent150.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    ping_database()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for phone in PHONES:
        data = pull_phone(phone)
        (OUT_DIR / f"transcript_{phone}_recent150.json").write_text(
            json.dumps(data, indent=2, default=str)
        )
        write_markdown(data)
        print(
            phone,
            "msgs",
            data["message_count"],
            "traces",
            data["traces_joined_by_request_id"],
            "missing",
            data["user_turns_missing_trace"],
        )


if __name__ == "__main__":
    main()
