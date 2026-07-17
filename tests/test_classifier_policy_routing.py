"""Tests for policy-vs-action classifier routing and programmatic overrides."""

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
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import (
    Classifier,
    _CUSTOM_JEWELLERY_HANDOFF_MESSAGE,
    _build_classifier_system_content,
    _format_active_product_context,
    _is_acknowledgement_message,
    _is_policy_action_query,
    _is_policy_information_query,
    _is_product_price_signal,
    _programmatic_intent_override,
    classify_query_for_audit,
)

POLICY_INFO_MATRIX = [
    ("return kaise karu?", "general"),
    ("return policy kya hai?", "general"),
    ("buyback kitna milega?", "general"),
    ("making charges kitna hai?", "general"),
    ("exchange policy kya hai?", "general"),
    ("exchange possible hai?", "general"),
]

POLICY_ACTION_MATRIX = [
    ("return karna hai", "returns_refund"),
    ("exchange karna hai", "returns_refund"),
    ("refund chahiye mujhe", "returns_refund"),
    ("mujhe return karna hai", "returns_refund"),
]


class PolicyRoutingUnitTests(unittest.TestCase):
    def test_policy_information_queries(self):
        for text, _ in POLICY_INFO_MATRIX:
            self.assertTrue(
                _is_policy_information_query(text),
                msg=f"expected info query: {text!r}",
            )
            self.assertFalse(
                _is_policy_action_query(text),
                msg=f"should not be action: {text!r}",
            )

    def test_policy_action_queries(self):
        for text, _ in POLICY_ACTION_MATRIX:
            self.assertTrue(
                _is_policy_action_query(text),
                msg=f"expected action query: {text!r}",
            )

    def test_programmatic_override_matrix(self):
        for text, expected in POLICY_INFO_MATRIX + POLICY_ACTION_MATRIX:
            override = _programmatic_intent_override(text)
            self.assertIsNotNone(override, msg=text)
            self.assertEqual(override[0], expected, msg=text)

    def test_custom_jewellery_override(self):
        override = _programmatic_intent_override("custom ring banwana hai")
        self.assertEqual(override, ("human_handoff", 0.95))

    def test_product_price_signal_guard(self):
        self.assertTrue(_is_product_price_signal("is ring ka price kitna hai"))
        self.assertFalse(_is_product_price_signal("buyback kitna milega"))
        self.assertFalse(_is_product_price_signal("making charges kitna hai"))

    def test_acknowledgement_detection(self):
        self.assertTrue(_is_acknowledgement_message("thank you", {}))
        self.assertTrue(_is_acknowledgement_message("ok", {}))
        self.assertFalse(
            _is_acknowledgement_message(
                "thank you",
                {"awaiting_store_pincode": True},
            )
        )

    def test_greeting_suffix_still_not_product_query(self):
        self.assertIsNone(_programmatic_intent_override("hi show me rings"))


class PolicyRoutingIntegrationTests(unittest.TestCase):
    def test_override_skips_llm_for_policy_info(self):
        async def _run():
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
            ) as mock_llm:
                result = await classify_query_for_audit(
                    "return kaise karu?", use_llm=True
                )
            mock_llm.assert_not_called()
            self.assertEqual(result["intent"], "general")
            self.assertEqual(result["source"], "override")

        asyncio.run(_run())

    def test_post_llm_override_corrects_wrong_intent(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "buyback kitna milega?"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {"intent": "product_info", "confidence": 0.92, "entities": {}}
                ),
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "general")
            self.assertEqual(result["user_profile"]["service_selected"], SL.GENERAL.value)

        asyncio.run(_run())

    def test_return_action_routes_to_returns_refund(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "return karna hai"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
            ) as mock_llm:
                result = await clf.process(data)
            mock_llm.assert_not_called()
            self.assertEqual(result["classified_category"], "returns_refund")
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.RETURNS_REFUND.value,
            )

        asyncio.run(_run())

    def test_custom_jewellery_handoff_message(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "custom ring banwana hai"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.send_customer_support_template"
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "human_handoff")
            self.assertIn("design expert", result["bot_response"][0]["text"].lower())
            self.assertIn(
                "design expert",
                _CUSTOM_JEWELLERY_HANDOFF_MESSAGE.lower(),
            )
            self.assertTrue(result["user_profile"]["live_agent_required"])

        asyncio.run(_run())

    def test_acknowledgement_shortcut_no_llm(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "thank you"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
            ) as mock_llm:
                result = await clf.process(data)
            mock_llm.assert_not_called()
            self.assertEqual(result["classified_category"], "acknowledgement")
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn("happy to help", result["bot_response"][0]["text"].lower())

        asyncio.run(_run())

    def test_product_price_skips_classifier_in_session(self):
        clf = Classifier()
        data = {
            "messages": {
                "text": {"body": "is ring ka price kitna hai"},
            },
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "gold ring"}],
                "last_viewed_product": {"_id": "1", "title": "Ring"},
            },
        }
        self.assertFalse(clf.should_run(data))

        policy_data = {
            "messages": {"text": {"body": "buyback kitna milega?"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "gold ring"}],
                "last_viewed_product": {"_id": "1", "title": "Ring"},
            },
        }
        self.assertTrue(clf.should_run(policy_data))


class ClassifierActiveContextTests(unittest.TestCase):
    def test_last_viewed_product_context(self):
        profile = {"last_viewed_product": {"title": "Gold Ring"}}
        ctx = _format_active_product_context(profile)
        self.assertIn("Gold Ring", ctx)
        self.assertTrue(ctx.startswith("Active context:"))

    def test_last_search_filters_context(self):
        profile = {
            "last_search_filters": {
                "category": "ring",
                "material_type": "gold",
                "max_price": 50000,
            }
        }
        ctx = _format_active_product_context(profile)
        self.assertIn("ring", ctx)
        self.assertIn("gold", ctx)
        self.assertIn("50000", ctx)

    def test_system_content_prepends_active_context(self):
        profile = {"last_viewed_product": {"title": "Gold Ring"}}
        content = _build_classifier_system_content(profile, "User: hi")
        self.assertIn("Active context:", content)
        self.assertIn("Chat history: User: hi", content)


if __name__ == "__main__":
    unittest.main()
