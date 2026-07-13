#!/usr/bin/env python3
"""
One-time migration: copy users.chat_history into chat_messages.

Deploy order:
  1. Deploy dual-write (new messages land in chat_messages)
  2. Run this script once
  3. Spot-check counts
  4. Switch dashboard to paginated chat_messages endpoint

Idempotent: skips users that already have migrated:true rows.
Also skips inserts that already exist with the same phone/role/content/ts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv

load_dotenv(ROOT_DIR / ".env")


def _synthetic_timestamps(entries: list[dict], updated_at: int | None) -> list[int]:
    """Space missing timestamps 1s apart, ending at updated_at."""
    n = len(entries)
    if n == 0:
        return []
    end = int(updated_at or 0)
    if end <= 0:
        end = n
    start = end - (n - 1)
    return [start + i for i in range(n)]


def migrate_user(user: dict, chat_messages, *, force: bool = False) -> int:
    """Migrate one user. Returns number of messages inserted."""
    phone = user.get("phone_number") or user.get("phone")
    client_id = user.get("client_id") or "kisna"
    history = user.get("chat_history") or []
    if not phone or not history:
        return 0

    if not force:
        already = chat_messages.count_documents(
            {"phone": phone, "client_id": client_id, "migrated": True}
        )
        if already > 0:
            return -1  # skipped

    updated_at = user.get("updated_at")
    try:
        updated_at = int(updated_at) if updated_at is not None else None
    except (TypeError, ValueError):
        updated_at = None

    missing_ts = [e for e in history if not e.get("timestamp") and not e.get("ts")]
    synthetic = (
        _synthetic_timestamps(history, updated_at) if missing_ts else None
    )

    inserted = 0
    for idx, entry in enumerate(history):
        role = entry.get("role") or "user"
        content = entry.get("content") or ""
        ts = entry.get("timestamp") or entry.get("ts")
        if ts is None and synthetic is not None:
            ts = synthetic[idx]
        elif ts is None:
            ts = (updated_at or 0) - (len(history) - 1 - idx)
        try:
            ts = int(ts)
        except (TypeError, ValueError):
            ts = (updated_at or 0) - (len(history) - 1 - idx)

        # Overlap guard with dual-written rows
        if chat_messages.count_documents(
            {
                "phone": phone,
                "client_id": client_id,
                "role": role,
                "content": content,
                "ts": ts,
            },
            limit=1,
        ):
            continue

        doc = {
            "phone": phone,
            "client_id": client_id,
            "role": role,
            "content": content,
            "ts": ts,
            "request_id": entry.get("request_id"),
            "migrated": True,
        }
        chat_messages.insert_one(doc)
        inserted += 1
    return inserted


def run_migration(*, force: bool = False) -> tuple[int, int, int]:
    from kisna_chatbot.database.collections import chat_messages, users

    migrated_users = 0
    migrated_messages = 0
    skipped = 0

    cursor = users.find({}, {"phone_number": 1, "client_id": 1, "chat_history": 1, "updated_at": 1})
    for i, user in enumerate(cursor, start=1):
        result = migrate_user(user, chat_messages, force=force)
        if result < 0:
            skipped += 1
        else:
            migrated_users += 1
            migrated_messages += result
        if i % 100 == 0:
            print(
                f"Progress: scanned {i} users — "
                f"migrated {migrated_users} users / {migrated_messages} messages, "
                f"skipped {skipped}"
            )

    return migrated_users, migrated_messages, skipped


def main() -> None:
    if not (os.environ.get("MONGO_URI") or "").strip():
        raise SystemExit("MONGO_URI is required")
    users_n, msgs_n, skipped = run_migration()
    print(
        f"Migrated {users_n} users, {msgs_n} messages, skipped {skipped} already-migrated."
    )


if __name__ == "__main__":
    main()
