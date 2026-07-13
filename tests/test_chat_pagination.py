"""Tests for chat_messages pagination and dual-write shape."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")


class TestChatPagination(unittest.TestCase):
    @patch("kisna_chatbot.database.db_utils.chat_messages")
    def test_cursor_returns_page_and_has_more(self, mock_coll):
        from kisna_chatbot.database.db_utils import get_paginated_chat_messages

        docs = [
            {"_id": f"id{i}", "role": "user", "content": f"m{i}", "ts": 1000 + i}
            for i in range(55)
        ]
        # Query sorts ts desc — newest first; we reverse for display
        newest_first = list(reversed(docs))

        class FakeCursor(list):
            def sort(self, *_a, **_k):
                return self

            def limit(self, n):
                return FakeCursor(self[:n])

        mock_coll.find.return_value = FakeCursor(newest_first)

        page = get_paginated_chat_messages("9199", "kisna", limit=50)
        self.assertEqual(len(page["messages"]), 50)
        self.assertTrue(page["has_more"])
        # oldest→newest in response
        self.assertEqual(page["messages"][0]["content"], "m5")
        self.assertEqual(page["messages"][-1]["content"], "m54")

        # Second page before oldest of first page
        older = newest_first[50:]
        mock_coll.find.return_value = FakeCursor(older)
        page2 = get_paginated_chat_messages(
            "9199", "kisna", before=page["messages"][0]["timestamp"], limit=50
        )
        self.assertEqual(len(page2["messages"]), 5)
        self.assertFalse(page2["has_more"])

    @patch("kisna_chatbot.database.db_utils.chat_messages")
    def test_dual_write_insert_shape(self, mock_coll):
        from kisna_chatbot.database.db_utils import dual_write_chat_entries

        dual_write_chat_entries(
            "9199",
            "kisna",
            [
                {
                    "role": "assistant",
                    "content": "hello",
                    "timestamp": 123,
                    "request_id": "rid-1",
                }
            ],
        )
        mock_coll.insert_one.assert_called_once()
        doc = mock_coll.insert_one.call_args[0][0]
        self.assertEqual(doc["phone"], "9199")
        self.assertEqual(doc["client_id"], "kisna")
        self.assertEqual(doc["role"], "assistant")
        self.assertEqual(doc["ts"], 123)
        self.assertEqual(doc["request_id"], "rid-1")


if __name__ == "__main__":
    unittest.main()
