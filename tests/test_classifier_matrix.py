"""Classifier accuracy matrix — programmatic routing and mocked LLM cases."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.processors.classifier import (
    Classifier,
    _programmatic_intent_override,
    classify_query_for_audit,
)

PROGRAMMATIC_MATRIX = [
    ("what is the price of Elysia ring?", "product_info"),
    ("Maggio ring ki price kya hai?", "product_info"),
    ("koi offer hai kya?", "offers"),
    ("making charge offer batao", "offers"),
    ("nearest store", "store_info"),
    ("302001", "store_info"),
    ("mera order kahan hai?", "order_tracking"),
    ("delivery kab hogi?", "order_tracking"),
    ("order status", "order_tracking"),
    ("return karna hai", "returns_refund"),
    ("exchange possible hai?", "returns_refund"),
    ("complaint darz karni hai", "complaint"),
    ("wrong item aaya", "complaint"),
    ("agent se baat karni hai", "human_handoff"),
    ("help", "menu_help"),
]

LLM_DEFERRED_MATRIX = [
    "show me diamond rings",
    "gold earrings",
    "sone ki anguthi dikhao",
    "heere ki bali 50k tak",
    "necklace under 30000",
    "Rivaah collection",
    "mangalsutra dikhao",
    "Evil Eye bracelet",
]

GREETING_MATRIX = [
    "hey",
    "heyy!!!",
    "good morning",
    "ram ram",
    "kaise ho",
]


class ClassifierMatrixTests(unittest.TestCase):
    def test_programmatic_matrix(self):
        for text, expected in PROGRAMMATIC_MATRIX:
            if expected == "human_handoff":
                continue
            if expected == "menu_help":
                continue
            actual = _programmatic_intent_override(text, {})
            self.assertEqual(
                actual,
                expected,
                msg=f"{text!r}: expected {expected}, got {actual}",
            )

    def test_product_search_defers_to_llm(self):
        for text in LLM_DEFERRED_MATRIX:
            self.assertIsNone(
                _programmatic_intent_override(text, {}),
                msg=f"{text!r} should defer to LLM",
            )

    def test_greeting_programmatic(self):
        for text in GREETING_MATRIX:
            self.assertEqual(
                _programmatic_intent_override(text, {}),
                "greeting",
                msg=f"{text!r} should be greeting",
            )

    def test_price_query_is_product_info_not_search(self):
        self.assertEqual(
            _programmatic_intent_override(
                "what is the price of Elysia ring?", {}
            ),
            "product_info",
        )

    def test_bare_gold_defers_to_llm(self):
        self.assertIsNone(_programmatic_intent_override("gold", {}))

    def test_menu_help_shortcut(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "help"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            result = await clf.process(data)
            self.assertEqual(result["classified_category"], "menu_help")

        asyncio.run(_run())

    def test_low_confidence_triggers_clarification(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "product_search", "confidence": 0.35}',
            ):
                result = await clf.process(data)
            self.assertTrue(result["user_profile"]["pending_clarification"])
            self.assertIn("bot_response", result)
            self.assertEqual(result["bot_response"][0]["type"], "quickreply")

        asyncio.run(_run())

    def test_classify_query_for_audit_programmatic(self):
        async def _run():
            result = await classify_query_for_audit(
                "Maggio ring ki price kya hai?", use_llm=False
            )
            self.assertEqual(result["intent"], "product_info")
            self.assertEqual(result["source"], "programmatic")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
