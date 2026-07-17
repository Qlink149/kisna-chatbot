"""Tests for conversational text-flow helpers (composer, TTL, entity carry-over)."""

import asyncio
import os
import time
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
from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    _parse_classifier_json,
    _parse_rating_reply,
)
from kisna_chatbot.processors.entity_extractor import merge_search_entities  # noqa: E402
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    _is_price_only_refinement,
)
from kisna_chatbot.processors.service_list import (  # noqa: E402
    build_acknowledgement_bot_response,
    flow_switch_acknowledgement,
)
from kisna_chatbot.utils.reply_composer import (  # noqa: E402
    compose,
    sanitize_classifier_language,
)
from kisna_chatbot.utils.session_state import (  # noqa: E402
    maybe_expire_session,
    reset_transient_state,
)


class ReplyComposerTests(unittest.TestCase):
    def test_english_bypasses_llm(self):
        async def _run():
            with patch(
                "kisna_chatbot.utils.reply_composer.complete_chat",
                new_callable=AsyncMock,
            ) as mocked:
                out = await compose("acknowledgement", "Hello!", language="en")
            mocked.assert_not_called()
            self.assertEqual(out, "Hello!")

        asyncio.run(_run())

    def test_language_sanitization(self):
        self.assertEqual(sanitize_classifier_language("hi"), "hi")
        self.assertEqual(sanitize_classifier_language("hi-Latn"), "hi-Latn")
        self.assertEqual(sanitize_classifier_language("hinglish"), "hi-Latn")
        self.assertEqual(sanitize_classifier_language(""), "en")

    def test_composer_failure_falls_back(self):
        async def _run():
            with patch(
                "kisna_chatbot.utils.reply_composer.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("boom"),
            ):
                out = await compose("acknowledgement", "Hello!", language="hi")
            self.assertEqual(out, "Hello!")

        asyncio.run(_run())

    def test_classifier_language_field(self):
        parsed = _parse_classifier_json(
            '{"intent":"greeting","confidence":0.9,"language":"hi-Latn","entities":{}}'
        )
        self.assertEqual(parsed["language"], "hi-Latn")


class SessionHygieneTests(unittest.TestCase):
    def test_ttl_clears_stale_wizard(self):
        profile = {
            "service_selected": "product_search",
            "awaiting_store_pincode": True,
            "pending_clarification": True,
            "last_message_at": int(time.time()) - (3 * 60 * 60),
            "last_search_filters": {"category": "ring"},
        }
        maybe_expire_session(profile)
        self.assertEqual(profile.get("service_selected"), "")
        self.assertNotIn("awaiting_store_pincode", profile)
        self.assertNotIn("pending_clarification", profile)
        self.assertNotIn("last_search_filters", profile)

    def test_fresh_session_keeps_state(self):
        profile = {
            "service_selected": "product_search",
            "awaiting_store_pincode": True,
            "last_message_at": int(time.time()),
        }
        maybe_expire_session(profile)
        self.assertEqual(profile["service_selected"], "product_search")
        self.assertTrue(profile["awaiting_store_pincode"])

    def test_reset_transient_state(self):
        profile = {
            "pending_clarification": True,
            "awaiting_rating": True,
            "username": "Priya",
        }
        reset_transient_state(profile, keep=frozenset({"awaiting_rating"}))
        self.assertNotIn("pending_clarification", profile)
        self.assertTrue(profile["awaiting_rating"])
        self.assertEqual(profile["username"], "Priya")


class EntityCarryOverTests(unittest.TestCase):
    def test_price_only_inherits_category(self):
        profile = {
            "last_search_filters": {
                "category": "ring",
                "material_type": "gold",
                "max_price": 50000,
            },
            "service_selected": "product_search",
        }
        self.assertTrue(_is_price_only_refinement("under 40k", profile))

        # When merge sees an explicit refinement phrase, it also inherits.
        prior = {"category": "ring", "material_type": "gold", "max_price": 50000}
        new = {
            "category": None,
            "material_type": None,
            "min_price": None,
            "max_price": 40000,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "I want them under 40k")
        self.assertEqual(merged["category"], "ring")
        self.assertEqual(merged["max_price"], 40000)

    def test_new_category_drops_old_budget(self):
        prior = {"category": "ring", "material_type": "gold", "max_price": 50000}
        new = {
            "category": "necklace",
            "material_type": None,
            "min_price": None,
            "max_price": None,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "show me necklaces")
        self.assertEqual(merged["category"], "necklace")
        self.assertIsNone(merged["max_price"])
        self.assertIsNone(merged["material_type"])

    def test_new_category_with_budget_uses_message_budget(self):
        prior = {"category": "ring", "max_price": 30000}
        new = {
            "category": "necklace",
            "material_type": None,
            "min_price": None,
            "max_price": 50000,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "necklaces under 50k")
        self.assertEqual(merged["category"], "necklace")
        self.assertEqual(merged["max_price"], 50000)


class SilentFlowSwitchTests(unittest.TestCase):
    def test_flow_switch_ack_text(self):
        self.assertIn(
            "order",
            flow_switch_acknowledgement("product_search", "order_tracking").lower(),
        )

    def test_acknowledgement_is_text(self):
        resp = build_acknowledgement_bot_response()
        self.assertEqual(resp[0]["type"], "text")
        self.assertNotIn("options", resp[0])

    def test_rating_parser(self):
        self.assertEqual(_parse_rating_reply("5"), 5)
        self.assertEqual(_parse_rating_reply("paanch"), 5)
        self.assertEqual(_parse_rating_reply("three"), 3)
        self.assertIsNone(_parse_rating_reply("rings"))

    def test_silent_switch_on_complaint_from_search(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "user_profile": {
                    "service_selected": "product_search",
                    "chat_history": [{"role": "user", "content": "rings"}],
                    "awaiting_store_pincode": False,
                },
                "messages": {"text": {"body": "I want to raise a complaint"}},
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=(
                    '{"intent":"complaint","confidence":0.9,"language":"en","entities":{}}'
                ),
            ):
                result = await clf.process(data)
            self.assertEqual(result["bot_response"][-1]["type"], "flow")
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            # No quickreply confirmation
            for msg in result["bot_response"]:
                self.assertNotEqual(msg.get("type"), "quickreply")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
