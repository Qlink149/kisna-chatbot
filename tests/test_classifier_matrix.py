"""Classifier accuracy matrix — LLM routing and minimal shortcuts."""

import asyncio
import json
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
    _looks_like_faq_query,
    classify_query_for_audit,
)
from kisna_chatbot.processors.entity_extractor import extract_entities

LLM_INTENT_MATRIX = [
    ("what is the price of Elysia ring?", "product_info"),
    ("Maggio ring ki price kya hai?", "product_info"),
    ("koi offer hai kya?", "offers"),
    ("making charge offer batao", "offers"),
    ("nearest store", "store_info"),
    ("mera order kahan hai?", "order_tracking"),
    ("delivery kab hogi?", "order_tracking"),
    ("order status", "order_tracking"),
    ("complaint darz karni hai", "complaint"),
    ("wrong item aaya", "complaint"),
    ("agent se baat karni hai", "human_handoff"),
    ("show me diamond rings", "product_search"),
    ("What is kisna Jewellery?", "general"),
    ("What are current offers available?", "offers"),
]

OVERRIDE_INTENT_MATRIX = [
    ("return karna hai", "returns_refund"),
    ("exchange possible hai?", "general"),
    ("return kaise karu?", "general"),
    ("buyback kitna milega?", "general"),
]

GREETING_MATRIX = [
    "hey",
    "heyy!!!",
    "good morning",
    "ram ram",
    "kaise ho",
]


class ClassifierMatrixTests(unittest.TestCase):
    def test_llm_intent_matrix(self):
        async def _run():
            for text, expected_intent in LLM_INTENT_MATRIX:
                llm_response = json.dumps(
                    {"intent": expected_intent, "confidence": 0.92, "entities": {}}
                )
                with patch(
                    "kisna_chatbot.processors.classifier.complete_chat",
                    new_callable=AsyncMock,
                    return_value=llm_response,
                ):
                    result = await classify_query_for_audit(text, use_llm=True)
                self.assertEqual(
                    result["intent"],
                    expected_intent,
                    msg=f"{text!r}: expected {expected_intent}, got {result['intent']}",
                )
                self.assertEqual(result["source"], "llm")

        asyncio.run(_run())

    def test_override_intent_matrix(self):
        async def _run():
            for text, expected_intent in OVERRIDE_INTENT_MATRIX:
                with patch(
                    "kisna_chatbot.processors.classifier.complete_chat",
                    new_callable=AsyncMock,
                ) as mock_llm:
                    result = await classify_query_for_audit(text, use_llm=True)
                mock_llm.assert_not_called()
                self.assertEqual(
                    result["intent"],
                    expected_intent,
                    msg=f"{text!r}: expected {expected_intent}, got {result['intent']}",
                )
                self.assertEqual(result["source"], "override")

        asyncio.run(_run())

    def test_greeting_shortcut(self):
        for text in GREETING_MATRIX:
            result = asyncio.run(
                classify_query_for_audit(text, use_llm=False)
            )
            self.assertEqual(result["intent"], "greeting", msg=text)
            self.assertEqual(result["source"], "shortcut")

    def test_faq_question_defers_to_llm_classifier(self):
        self.assertTrue(_looks_like_faq_query("What is kisna Jewellery?"))

    def test_faq_query_does_not_extract_spurious_title(self):
        entities = extract_entities("What is kisna Jewellery?")
        self.assertIsNone(entities.get("title"))
        self.assertIsNone(entities.get("category"))

    def test_classifier_runs_faq_in_product_search_session(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "What is kisna Jewellery?"}},
            "user_profile": {
                "service_selected": "product_search",
                "chat_history": [{"role": "user", "content": "gold rings"}],
            },
        }
        self.assertTrue(clf.should_run(data))

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
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn(
                "jewellery",
                result["bot_response"][0]["text"].lower(),
            )

        asyncio.run(_run())

    def test_classify_query_for_audit_uses_llm_when_enabled(self):
        async def _run():
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "product_info", "confidence": 0.91, "entities": {}}',
            ):
                result = await classify_query_for_audit(
                    "Maggio ring ki price kya hai?", use_llm=True
                )
            self.assertEqual(result["intent"], "product_info")
            self.assertEqual(result["source"], "llm")

        asyncio.run(_run())

    def test_pincode_shortcut_only_when_awaiting_store_pincode(self):
        async def _run():
            result = await classify_query_for_audit(
                "302001",
                {"awaiting_store_pincode": True},
                use_llm=False,
            )
            self.assertEqual(result["intent"], "store_info")
            self.assertEqual(result["source"], "shortcut")

            unknown = await classify_query_for_audit("302001", {}, use_llm=False)
            self.assertEqual(unknown["intent"], "unknown")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
