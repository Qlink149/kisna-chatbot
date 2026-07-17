"""Tests for cross-flow switch UX and classifier escape hatches."""

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
from kisna_chatbot.processors.classifier import Classifier
from kisna_chatbot.processors.service_list import (
    ServiceList,
    build_flow_switch_bot_response,
    handle_flow_switch_quick_reply,
)


def _browse_profile(**extra):
    base = {
        "service_selected": SL.PRODUCT_SEARCH.value,
        "chat_history": [{"role": "user", "content": "diamond rings"}],
        "last_search_products": [{"_id": "p1", "title": "Ring"}],
    }
    base.update(extra)
    return base


class FlowSwitchEscapeTests(unittest.TestCase):
    def test_should_run_escape_returns_in_product_search(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "wapas karna hai"}},
            "user_profile": _browse_profile(),
        }
        self.assertTrue(clf.should_run(data))

    def test_should_run_escape_complaint_not_product_category(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "galat item aaya mera"}},
            "user_profile": _browse_profile(),
        }
        self.assertTrue(clf.should_run(data))

    def test_should_run_skips_comparative_in_product_search(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "show me cheapest"}},
            "user_profile": _browse_profile(),
        }
        self.assertFalse(clf.should_run(data))


class FlowSwitchPromptTests(unittest.TestCase):
    def test_returns_silent_switch_while_browsing(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "wapas karna hai"}},
                "user_profile": _browse_profile(),
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "returns_refund", "confidence": 0.9, "language": "en", "entities": {}}',
            ):
                result = await clf.process(data)
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.RETURNS_REFUND.value,
            )
            self.assertEqual(result["classified_category"], "returns_refund")
            if result.get("bot_response"):
                self.assertEqual(result["bot_response"][0]["type"], "text")
                for msg in result["bot_response"]:
                    self.assertNotEqual(msg.get("type"), "quickreply")

        asyncio.run(_run())

    def test_offers_silent_switch_while_browsing(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "koi offer hai?"}},
                "user_profile": _browse_profile(),
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "offers", "confidence": 0.9, "language": "en", "entities": {}}',
            ):
                result = await clf.process(data)
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.OFFERS.value,
            )
            self.assertEqual(result["classified_category"], "offers")
            if result.get("bot_response"):
                self.assertEqual(result["bot_response"][0]["type"], "text")
                for msg in result["bot_response"]:
                    self.assertNotEqual(msg.get("type"), "quickreply")

        asyncio.run(_run())

    def test_hi_no_flow_switch_prompt(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "hi"}},
                "user_profile": _browse_profile(),
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "greeting", "confidence": 0.95}',
            ):
                result = await clf.process(data)
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            if result.get("bot_response"):
                for msg in result["bot_response"]:
                    self.assertNotEqual(
                        msg.get("msgid"),
                        QuickReplyId.FLOW_SWITCH_CONFIRM.value,
                    )

        asyncio.run(_run())

    def test_human_handoff_immediate_no_prompt(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "kisi se baat karni hai"}},
                "user_profile": _browse_profile(),
                "client_id": "kisna",
            }
            with (
                patch(
                    "kisna_chatbot.processors.classifier.complete_chat",
                    new_callable=AsyncMock,
                    return_value='{"intent": "human_handoff", "confidence": 0.95, "entities": {}}',
                ),
                patch(
                    "kisna_chatbot.processors.support_handler.get_support_status",
                    return_value={"status": "open"},
                ),
                patch(
                    "kisna_chatbot.processors.classifier.send_customer_support_template"
                ),
                patch(
                    "kisna_chatbot.processors.support_handler.send_customer_support_template"
                ),
            ):
                result = await clf.process(data)
            self.assertIn("bot_response", result)
            self.assertIn("connecting you", result["bot_response"][0]["text"].lower())
            self.assertNotIn("pending_flow_switch", result["user_profile"])

        asyncio.run(_run())

    def test_complaint_silent_switch_sends_form(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "galat item aaya mera"}},
                "user_profile": _browse_profile(),
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "complaint", "confidence": 0.92, "language": "en", "entities": {}}',
            ):
                result = await clf.process(data)
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.COMPLAINT.value,
            )
            flow_msgs = [
                m for m in result["bot_response"] if m.get("type") == "flow"
            ]
            self.assertEqual(flow_msgs[-1]["flow"], "damage_complaint")
            for msg in result["bot_response"]:
                self.assertNotEqual(msg.get("type"), "quickreply")

        asyncio.run(_run())


class FlowSwitchHandlerTests(unittest.TestCase):
    def test_yes_switches_to_returns_refund(self):
        user_profile = _browse_profile(
            pending_flow_switch={
                "intent": "returns_refund",
                "service": SL.RETURNS_REFUND.value,
            }
        )
        data = {"_flow_switch_button_title": "Yes, help with return"}
        handled = handle_flow_switch_quick_reply(
            QuickReplyId.FLOW_SWITCH_CONFIRM.value, user_profile, data
        )
        self.assertTrue(handled)
        self.assertEqual(user_profile["service_selected"], SL.RETURNS_REFUND.value)
        self.assertEqual(data["classified_category"], "returns_refund")
        self.assertNotIn("bot_response", data)
        self.assertEqual(user_profile["last_search_filters"], {})
        self.assertEqual(user_profile["shown_product_ids"], [])

    def test_no_keeps_browsing_and_sends_text_prompt(self):
        user_profile = _browse_profile(
            pending_flow_switch={
                "intent": "offers",
                "service": SL.OFFERS.value,
            }
        )
        data = {"_flow_switch_button_title": "No, keep browsing"}
        handled = handle_flow_switch_quick_reply(
            QuickReplyId.FLOW_SWITCH_CONFIRM.value, user_profile, data
        )
        self.assertTrue(handled)
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertIn("bot_response", data)
        self.assertEqual(len(data["bot_response"]), 2)
        self.assertTrue(all(m["type"] == "text" for m in data["bot_response"]))

    def test_service_list_handles_flow_switch_yes(self):
        async def _run():
            processor = ServiceList()
            user_profile = _browse_profile(
                pending_flow_switch={
                    "intent": "offers",
                    "service": SL.OFFERS.value,
                }
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {
                            "id": QuickReplyId.FLOW_SWITCH_CONFIRM.value,
                            "title": "Yes, show offers",
                        },
                    }
                },
                "user_profile": user_profile,
            }
            result = await processor.process(data)
            self.assertEqual(
                result["user_profile"]["service_selected"], SL.OFFERS.value
            )
            self.assertNotIn("bot_response", result)

        asyncio.run(_run())

    def test_build_flow_switch_product_to_offers(self):
        resp = build_flow_switch_bot_response(SL.PRODUCT_SEARCH.value, "offers")
        self.assertEqual(resp[0]["type"], "text")
        self.assertIn("offers", resp[0]["text"].lower())
        self.assertNotIn("options", resp[0])


if __name__ == "__main__":
    unittest.main()
