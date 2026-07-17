"""Tests for low-confidence clarification flow."""

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
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.enums import QuickReplyId
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import Classifier, _should_offer_clarification
from kisna_chatbot.processors.service_list import (
    ServiceList,
    build_clarification_bot_response,
    handle_clarification_quick_reply,
)


class ClarificationFlowTests(unittest.TestCase):
    def test_build_clarification_completely_unclear(self):
        resp = build_clarification_bot_response("general", 0.2)
        self.assertEqual(resp[0]["type"], "text")
        self.assertIn("jewellery", resp[0]["text"].lower())

    def test_clarify_browse_quick_reply_legacy(self):
        user_profile = {"pending_clarification": True}
        data = {"_clarify_button_title": "Browse Jewellery"}
        handled = handle_clarification_quick_reply(
            QuickReplyId.CLARIFY_BROWSE.value, user_profile, data
        )
        self.assertTrue(handled)
        self.assertFalse(user_profile["pending_clarification"])
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertEqual(data["bot_response"][0]["type"], "text")

    def test_pending_clarification_prepends_context(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "rings"}},
                "user_profile": {
                    "chat_history": [],
                    "service_selected": "",
                    "pending_clarification": True,
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "product_search", "confidence": 0.9, "language": "en"}',
            ) as mock_llm:
                result = await clf.process(data)
            call_messages = mock_llm.await_args.kwargs["messages"]
            user_content = call_messages[-1]["content"]
            self.assertIn("clarify", user_content.lower())
            self.assertEqual(result["classified_category"], "product_search")

        asyncio.run(_run())

    def test_off_topic_ambiguous_in_product_search_offers_clarification(self):
        user_profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "chat_history": [{"role": "user", "content": "rings"}],
        }
        data = {}
        self.assertTrue(
            _should_offer_clarification(data, "hmm maybe something", user_profile)
        )

    def test_service_list_handles_clarify_button(self):
        async def _run():
            processor = ServiceList()
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {
                            "id": QuickReplyId.CLARIFY_BROWSE.value,
                            "title": "Browse Jewellery",
                        },
                    }
                },
                "user_profile": {"pending_clarification": True},
            }
            result = await processor.process(data)
            self.assertIn("bot_response", result)
            self.assertEqual(
                result["user_profile"]["service_selected"], SL.PRODUCT_SEARCH.value
            )

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
