"""Tests for plain-language message traces."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from kisna_chatbot.utils.message_trace import (  # noqa: E402
    persist_message_trace,
    summarize_filters,
    trace_step,
)


class TestMessageTrace(unittest.TestCase):
    def test_search_trace_steps(self):
        data = {
            "request_id": "rid-search",
            "client_id": "kisna",
            "phone_number": "9199",
            "messages": {"type": "text", "text": {"body": "Under 10k"}},
            "bot_response": [
                {"type": "image_with_cta", "url": "x"},
                {"type": "image_with_cta", "url": "y"},
                {"type": "image_with_cta", "url": "z"},
                {"type": "button"},
            ],
        }
        trace_step(data, "Message received", "Under 10k")
        trace_step(data, "Understood as", "Product search (90% confidence)")
        trace_step(
            data,
            "Filters detected",
            summarize_filters(
                {"category": "earring", "material_type": "gold", "max_price": 10000}
            ),
        )
        trace_step(
            data,
            "Searched catalogue",
            "Category: Earrings, Material: Gold, Price: ₹0–₹10,000 → 14 products found",
        )
        trace_step(data, "Reply sent", "3 product cards + buttons")

        labels = [s["label"] for s in data["_trace_steps"]]
        self.assertEqual(
            labels,
            [
                "Message received",
                "Understood as",
                "Filters detected",
                "Searched catalogue",
                "Reply sent",
            ],
        )
        self.assertIn("Earring", data["_trace_steps"][2]["detail"])

    def test_zero_result_warn_outcome(self):
        data = {
            "request_id": "rid-zero",
            "client_id": "kisna",
            "phone_number": "9199",
            "messages": {"type": "text", "text": {"body": "Under 10k"}},
            "bot_response": [{"type": "text", "text": "No products"}],
            "_trace_outcome": "no_products",
        }
        trace_step(data, "Message received", "Under 10k")
        trace_step(data, "Understood as", "Product search")
        trace_step(
            data,
            "Searched catalogue",
            "0 products found",
            status="warn",
        )

        with patch(
            "kisna_chatbot.database.collections.message_traces"
        ) as mock_coll:
            mock_coll.update_one = MagicMock()
            persist_message_trace(data)
            mock_coll.update_one.assert_called_once()
            doc = mock_coll.update_one.call_args[0][1]["$set"]
            self.assertEqual(doc["outcome"], "no_products")
            searched = [s for s in doc["steps"] if s["label"] == "Searched catalogue"][0]
            self.assertEqual(searched["status"], "warn")

    def test_persist_failure_does_not_raise(self):
        data = {
            "request_id": "rid-fail",
            "client_id": "kisna",
            "phone_number": "9199",
            "messages": {"type": "text", "text": {"body": "hi"}},
            "bot_response": [{"type": "text", "text": "hello"}],
        }
        trace_step(data, "Message received", "hi")
        with patch(
            "kisna_chatbot.database.collections.message_traces"
        ) as mock_coll:
            mock_coll.update_one.side_effect = RuntimeError("db down")
            persist_message_trace(data)  # must not raise


if __name__ == "__main__":
    unittest.main()
