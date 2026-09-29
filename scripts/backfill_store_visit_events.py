"""One-off: push store visits booked while the Salesforce push was off.

Once KISNA_STORE_VISIT_EVENTS_ENABLED (and KISNA_CLARA_EVENTS_ENABLED) are on,
every store_visits booking whose Salesforce status is "Not sent" -- no
clara_events row with event_id == request_id -- is enqueued on the normal
Clara outbox, with the same payload a live booking sends.

Idempotent on request ID: a booking that already has an outbox row is
skipped, and the outbox's unique event_id refuses a second insert, so
re-running (or running while the app runs) never sends one twice.

    python scripts/backfill_store_visit_events.py --dry-run   # list only
    python scripts/backfill_store_visit_events.py             # enqueue + send
    python scripts/backfill_store_visit_events.py --limit 20  # first N only

Rows still failing after the inline retries stay "pending" in the outbox and
are retried by the app's sweeper, like any other event.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def find_unsent(store_visits, clara_events, *, client_id: str, limit: int | None) -> list[dict]:
    from kisna_chatbot.processors.store_visit_agent import SOURCE

    query = {"source": SOURCE, "client_id": client_id, "request_id": {"$type": "string"}}
    rows = list(store_visits.find(query, {"_id": 0}).sort("created_at", 1))
    ids = [r["request_id"] for r in rows]
    queued = {
        e["event_id"] for e in clara_events.find({"event_id": {"$in": ids}}, {"event_id": 1})
    } if ids else set()
    unsent = [r for r in rows if r["request_id"] not in queued]
    return unsent[:limit] if limit else unsent


async def push(rows: list[dict]) -> dict:
    from kisna_chatbot.integrations import clara_events as outbox
    from kisna_chatbot.processors.store_visit_agent import store_visit_event_from_doc

    for doc in rows:
        await outbox.enqueue_event(store_visit_event_from_doc(doc))
    # enqueue_event starts delivery in the background; wait for it here, or
    # the script would exit mid-send. Anything unfinished stays pending.
    pending = list(outbox._BACKGROUND_TASKS)
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    statuses: dict[str, int] = {}
    ids = [d["request_id"] for d in rows]
    for e in outbox._events.find({"event_id": {"$in": ids}}, {"status": 1}):
        statuses[e.get("status", "?")] = statuses.get(e.get("status", "?"), 0) + 1
    return statuses


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list what would be sent; send nothing")
    ap.add_argument("--client-id", default="kisna")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    from kisna_chatbot.config.store_visit import store_visit_events_enabled
    from kisna_chatbot.database.collections import clara_events, store_visits
    from kisna_chatbot.integrations.clara_events import is_enabled as clara_events_enabled

    rows = find_unsent(store_visits, clara_events, client_id=args.client_id, limit=args.limit)
    print(f"{len(rows)} store visit(s) with Salesforce status 'Not sent'")
    for r in rows:
        store = r.get("store") or {}
        print(
            f"  {r['request_id']}  booked {r.get('preferred_date', '')} {r.get('preferred_time', '')}"
            f"  store {store.get('store_id', '')} {store.get('name', '')}"
        )
    if args.dry_run or not rows:
        print("dry run: nothing sent" if args.dry_run else "nothing to send")
        return 0

    missing = [
        name
        for name, on in (
            ("KISNA_STORE_VISIT_EVENTS_ENABLED", store_visit_events_enabled()),
            ("KISNA_CLARA_EVENTS_ENABLED", clara_events_enabled()),
        )
        if not on
    ]
    if missing:
        print(f"REFUSED: {', '.join(missing)} not on. Turn the push on first (or use --dry-run).")
        return 2

    statuses = asyncio.run(push(rows))
    print("outbox status after sending:", statuses or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
