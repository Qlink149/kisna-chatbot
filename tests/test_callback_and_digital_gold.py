"""Tests for callback intent routing and digital gold CTA."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")
os.environ.setdefault("GUPSHUP_WEBHOOK_SECRET", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("SYSTEM_API_KEY", "test")
os.environ.setdefault("KISNA_PRODUCT_API", "http://localhost")
os.environ.setdefault("KISNA_OFFERS_API", "http://localhost")
os.environ.setdefault("KISNA_STORE_API", "http://localhost")
os.environ.setdefault("KISNA_VTIGER_BASE", "http://localhost")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test")
os.environ["KISNA_CALLBACK_FLOW_ID"] = "flow_callback_test"

from kisna_chatbot.processors.classifier import (  # noqa: E402
    _CALLBACK_RE,
    _DIGITAL_GOLD_RE,
    _programmatic_intent_hint,
    _programmatic_intent_override,
    _route_resolved_intent,
)
from kisna_chatbot.processors.shopping_wizard import DIGITAL_GOLD_URL  # noqa: E402


class CallbackIntentTests(unittest.TestCase):
    def test_callback_regex(self):
        self.assertTrue(_CALLBACK_RE.search("please call me back"))
        self.assertTrue(_CALLBACK_RE.search("I want a callback"))
        self.assertTrue(_CALLBACK_RE.search("mujhe call karo"))
        self.assertFalse(_CALLBACK_RE.search("talk to an agent"))

    def test_callback_is_llm_primary_with_soft_hint(self):
        self.assertIsNone(_programmatic_intent_override("call me back please"))
        hint = _programmatic_intent_hint("call me back please")
        self.assertIsNotNone(hint)
        self.assertIn("callback", hint.lower())

    @patch(
        "kisna_chatbot.config.gupshup.get_callback_flow_id",
        return_value="flow_callback_test",
    )
    def test_callback_sends_flow(self, _mock_flow):
        data = {"phone_number": "919999999999", "bot_response": None}
        data.pop("bot_response")
        profile = {"chat_history": [], "service_selected": ""}
        handled = _route_resolved_intent(
            data,
            profile,
            "919999999999",
            "call me back",
            [],
            "callback",
            0.95,
        )
        self.assertTrue(handled)
        types = [r.get("type") for r in data["bot_response"]]
        self.assertIn("flow", types)
        self.assertEqual(profile["service_selected"], "callback")
        flow = next(r for r in data["bot_response"] if r.get("type") == "flow")
        self.assertEqual(flow.get("flow"), "callback_request")


class DigitalGoldTests(unittest.TestCase):
    def test_digital_gold_regex(self):
        self.assertTrue(_DIGITAL_GOLD_RE.search("tell me about digital gold"))
        self.assertTrue(_DIGITAL_GOLD_RE.search("SafeGold"))
        self.assertEqual(DIGITAL_GOLD_URL, "https://www.kisna.com/digital-gold")

    def test_digital_gold_routes_general(self):
        intent, _ = _programmatic_intent_override("what is digital gold?")
        self.assertEqual(intent, "general")


if __name__ == "__main__":
    unittest.main()
