"""Seed the dashboard admin accounts into MongoDB.

Idempotent — upserts by username, so it's safe to re-run (e.g. to rotate a
password: edit ADMIN_ACCOUNTS below and run again).

Usage:
    python scripts/seed_admin_users.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bcrypt

from kisna_chatbot.database.collections import admin_users

ADMIN_ACCOUNTS = [
    {"username": "customersupport@kisna.com", "password": "Kisna@2026"},
    {"username": "clara_admin", "password": "clara_kisna_admin"},
]


def seed() -> None:
    for account in ADMIN_ACCOUNTS:
        password_hash = bcrypt.hashpw(
            account["password"].encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
        admin_users.update_one(
            {"username": account["username"]},
            {
                "$set": {
                    "username": account["username"],
                    "password_hash": password_hash,
                    "role": "super_admin",
                },
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)},
            },
            upsert=True,
        )
        print(f"Seeded admin user: {account['username']}")


if __name__ == "__main__":
    seed()
