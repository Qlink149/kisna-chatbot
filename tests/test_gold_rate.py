"""Tests for gold rate handler."""

import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from kisna_chatbot.processors.gold_rate_handler import (  # noqa: E402
    format_gold_rates_reply,
    build_gold_rate_bot_response,
)


class TestGoldRate(unittest.TestCase):
    def test_format_rates_from_list(self):
        body = {
            "data": [
                {"label": "22K Gold", "rate": 5850},
                {"label": "24K Gold", "rate": 6380},
            ]
        }
        text = format_gold_rates_reply(body)
        self.assertIn("22K Gold", text)
        self.assertIn("5850", text)

    def test_format_rates_fallback_on_empty(self):
        text = format_gold_rates_reply({})
        self.assertIn("kisna.com", text.lower())

    @patch(
        "kisna_chatbot.processors.gold_rate_handler.get_cached_gold_rates",
        new_callable=AsyncMock,
    )
    def test_build_gold_rate_bot_response(self, mock_get):
        mock_get.return_value = {
            "data": [{"label": "24K", "rate": 6400}]
        }
        import asyncio

        responses = asyncio.run(build_gold_rate_bot_response())
        self.assertEqual(responses[0]["type"], "text")
        self.assertIn("6400", responses[0]["text"])


if __name__ == "__main__":
    unittest.main()
