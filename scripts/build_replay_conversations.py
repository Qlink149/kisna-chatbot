#!/usr/bin/env python3
"""Build tests/replay/real_conversations.json from recent-150 windows.

CRITICAL: prod_reply is joined ONLY by request_id.
Never use positional pairing or "next assistant" fallback — that produces a
systematic one-turn lag when equal-ts rows sort assistant-before-user.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "audit" / "verification_raw"
OUT = ROOT / "tests" / "replay" / "real_conversations.json"

PHONES = ["916376925843", "918696979791"]
SESSION_GAP_S = 3 * 3600


def sessions_from_turns(turns: list[dict]) -> list[list[dict]]:
    if not turns:
        return []
    sessions: list[list[dict]] = [[turns[0]]]
    for t in turns[1:]:
        prev = sessions[-1][-1]
        if (t.get("ts") or 0) - (prev.get("ts") or 0) > SESSION_GAP_S:
            sessions.append([t])
        else:
            sessions[-1].append(t)
    return sessions


def pair_turns(session: list[dict]) -> list[dict]:
    """User turns only; reply = assistant content sharing the same request_id."""
    asst_by_rid: dict[str, str] = {}
    for t in session:
        rid = t.get("request_id")
        if rid and t.get("role") == "assistant":
            asst_by_rid.setdefault(rid, t.get("content") or "")

    out = []
    for t in session:
        if t.get("role") != "user":
            continue
        rid = t.get("request_id")
        # Prefer precomputed paired field from pull script; else map.
        reply = t.get("paired_assistant_by_request_id")
        if reply is None:
            reply = asst_by_rid.get(rid or "", "") if rid else ""
        # NEVER fall back to session[i+1] — that caused the off-by-one lag.
        out.append(
            {
                "ts": t.get("ts"),
                "ts_iso": t.get("ts_iso"),
                "message": t.get("content") or "",
                "request_id": rid,
                "prod_intent": t.get("intent"),
                "prod_confidence": t.get("confidence"),
                "prod_outcome": t.get("outcome"),
                "prod_clara_params": t.get("clara_params"),
                "prod_total_count": t.get("total_count"),
                "prod_reply": (reply or "")[:500],
                "prod_trace_missing": t.get("trace_missing"),
                "join": "request_id",
                "want_product_search": any(
                    w in (t.get("content") or "").lower()
                    for w in (
                        "ring",
                        "earring",
                        "chain",
                        "gold",
                        "diamond",
                        "bangle",
                        "bracelet",
                        "pendant",
                        "rakhi",
                        "collection",
                        "evil",
                        "necklace",
                        "show me",
                        "under",
                        "carat",
                    )
                ),
            }
        )
    return out


def main() -> None:
    conversations = []
    for phone in PHONES:
        path = RAW / f"transcript_{phone}_recent150.json"
        data = json.loads(path.read_text())
        for idx, sess in enumerate(sessions_from_turns(data["turns"])):
            user_turns = pair_turns(sess)
            if not user_turns:
                continue
            keep = any(
                u.get("want_product_search")
                or u.get("prod_outcome") in ("fallback_used", "no_products", "error")
                or u.get("prod_intent") == "product_search"
                for u in user_turns
            )
            if not keep and len(user_turns) < 2:
                continue
            conversations.append(
                {
                    "id": f"{phone}_s{idx}",
                    "phone": phone,
                    "session_index": idx,
                    "start_ts": user_turns[0]["ts_iso"],
                    "end_ts": user_turns[-1]["ts_iso"],
                    "turns": user_turns,
                }
            )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "recent_150_x2",
        "session_gap_hours": 3,
        "join_method": "request_id_only_no_positional_fallback",
        "conversation_count": len(conversations),
        "turn_count": sum(len(c["turns"]) for c in conversations),
        "conversations": conversations,
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(
        f"wrote {OUT} conversations={payload['conversation_count']} "
        f"user_turns={payload['turn_count']}"
    )


if __name__ == "__main__":
    main()
