"""Tests for one-time chat history migration."""

import os
import unittest
from unittest.mock import MagicMock

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from scripts.migrate_chat_history import (  # noqa: E402
    _synthetic_timestamps,
    migrate_user,
)


class TestMigrateChatHistory(unittest.TestCase):
    def test_migration_preserves_order(self):
        entries = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}]
        ts = _synthetic_timestamps(entries, updated_at=1000)
        self.assertEqual(ts, [998, 999, 1000])
        self.assertEqual(ts, sorted(ts))

    def test_migration_idempotent(self):
        chat_messages = MagicMock()
        # First run: no migrated rows
        chat_messages.count_documents.side_effect = [
            0,  # already-migrated check
            0,  # dedup for msg1
            0,  # dedup for msg2
            2,  # second run: already migrated
        ]
        user = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "updated_at": 2000,
            "chat_history": [
                {"role": "user", "content": "hi", "timestamp": 100},
                {"role": "assistant", "content": "hello", "timestamp": 101},
            ],
        }
        first = migrate_user(user, chat_messages)
        self.assertEqual(first, 2)
        self.assertEqual(chat_messages.insert_one.call_count, 2)

        second = migrate_user(user, chat_messages)
        self.assertEqual(second, -1)
        self.assertEqual(chat_messages.insert_one.call_count, 2)


if __name__ == "__main__":
    unittest.main()
