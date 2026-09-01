"""Tests for gold rate handler."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.processors.gold_rate_handler import (  # noqa: E402
    build_gold_rate_bot_response,
    format_gold_rates_reply,
)

_CLARA_PAYLOAD = {
    "data": {
        "data": [
            {
                "active": True,
                "kt": "24kt",
                "price": 14727,
            },
            {
                "active": True,
                "kt": "22kt",
                "price": 13489.932,
            },
            {
                "active": True,
                "kt": "18kt",
                "price": 11045.25,
            },
            {
                "active": True,
                "kt": "14kt",
                "price": 8590.2591,
            },
            {
                "active": True,
                "kt": "9kt",
                "price": 5522.625,
            },
            {
                "active": False,
                "kt": "20kt",
                "price": 99999,
            },
        ],
        "totalCount": 6,
    },
    "status": 200,
    "message": "Success",
}


class TestGoldRate(unittest.TestCase):
    def test_format_clara_kt_payload(self):
        text = format_gold_rates_reply(_CLARA_PAYLOAD)
        self.assertIn("*24KT*", text)
        self.assertIn("*22KT*", text)
        self.assertIn("₹14,727/g", text)
        self.assertIn("₹13,489.93/g", text)
        self.assertNotIn("99999", text)
        self.assertNotIn("20KT", text)
        # Highest purity first
        self.assertLess(text.index("24KT"), text.index("9KT"))

    def test_format_rates_from_list(self):
        body = {
            "data": [
                {"label": "22K Gold", "rate": 5850},
                {"label": "24K Gold", "rate": 6380},
            ]
        }
        text = format_gold_rates_reply(body)
        self.assertIn("22K Gold", text)
        self.assertIn("5,850", text)

    def test_skips_inactive(self):
        body = {
            "data": [
                {"kt": "24kt", "price": 100, "active": False},
                {"kt": "22kt", "price": 90, "active": True},
            ]
        }
        text = format_gold_rates_reply(body)
        self.assertIn("22KT", text)
        self.assertNotIn("24KT", text)

    def test_format_rates_fallback_on_empty(self):
        text = format_gold_rates_reply({})
        self.assertIn("kisna.com", text.lower())

    def test_excludes_20kt_even_when_active(self):
        # KISNA doesn't sell 20KT; it must be dropped even when Clara marks it
        # active=True (the reported bug — the fixture above only covers the
        # active=False case, which was never actually the failure mode).
        body = {
            "data": [
                {"kt": "24kt", "price": 15733, "active": True},
                {"kt": "20kt", "price": 12012, "active": True},
                {"kt": "9kt", "price": 5899.88, "active": True},
            ]
        }
        text = format_gold_rates_reply(body)
        self.assertIn("24KT", text)
        self.assertIn("9KT", text)
        self.assertNotIn("20KT", text)
        self.assertNotIn("12,012", text)

    @patch(
        "kisna_chatbot.processors.gold_rate_handler.get_cached_gold_rates",
        new_callable=AsyncMock,
    )
    def test_build_gold_rate_bot_response(self, mock_get):
        mock_get.return_value = _CLARA_PAYLOAD
        responses = asyncio.run(build_gold_rate_bot_response())
        self.assertEqual(responses[0]["type"], "text")
        self.assertIn("24KT", responses[0]["text"])
        self.assertIn("14,727", responses[0]["text"])
        # The inline "Browse jewellery: <url>" line is gone -- it's now a
        # separate CTA button so the URL survives translation untouched.
        self.assertNotIn("Browse jewellery", responses[0]["text"])
        self.assertNotIn("http", responses[0]["text"])

        self.assertEqual(len(responses), 2)
        cta = responses[1]
        self.assertEqual(cta["type"], "cta_url")
        self.assertEqual(cta["display_text"], "Browse Jewellery")
        self.assertTrue(cta["url"].startswith("https://www.kisna.com"))

    @patch(
        "kisna_chatbot.processors.gold_rate_handler.get_cached_gold_rates",
        new_callable=AsyncMock,
    )
    def test_no_cta_button_on_fallback(self, mock_get):
        mock_get.return_value = {}
        responses = asyncio.run(build_gold_rate_bot_response())
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["type"], "text")


if __name__ == "__main__":
    unittest.main()
