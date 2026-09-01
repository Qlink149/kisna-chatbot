"""Tests for callback intent routing and digital gold / KMR CTA buttons."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

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
from kisna_chatbot.processors.general_agent import GeneralAgent, _KMR_RE  # noqa: E402
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    DIGITAL_GOLD_URL,
    KMR_URL,
)


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

    def test_strip_url_mentions_drops_digital_gold_link(self):
        from kisna_chatbot.processors.general_agent import _strip_url_mentions

        text = "Register at https://www.kisna.com/digital-gold to get started."
        cleaned = _strip_url_mentions(text, DIGITAL_GOLD_URL)
        self.assertNotIn("kisna.com/digital-gold", cleaned)


class KmrTests(unittest.TestCase):
    def test_kmr_regex(self):
        self.assertTrue(_KMR_RE.search("tell me about kmr"))
        self.assertTrue(_KMR_RE.search("what is meri roshni"))
        self.assertTrue(_KMR_RE.search("koi scheme hai kya"))
        self.assertTrue(_KMR_RE.search("do you have a savings plan"))
        self.assertEqual(KMR_URL, "https://meriroshni.kisna.com/")

    def test_kmr_routes_general(self):
        intent, _ = _programmatic_intent_override("tell me about KMR")
        self.assertEqual(intent, "general")

    def _run_general_agent(self, query: str, message_text: str = "KMR info"):
        from kisna_chatbot.ai.types import GeneralAgentResult, ProviderName

        async def _run():
            agent = GeneralAgent()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": query}},
                "user_profile": {"service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.general_agent.run_general_agent",
                new_callable=AsyncMock,
                return_value=GeneralAgentResult(
                    message_text=message_text,
                    live_agent_requested=False,
                    provider=ProviderName.OPENAI,
                    model="test-model",
                ),
            ):
                return await agent.process(data)

        return asyncio.run(_run())

    def test_kmr_query_appends_cta_button(self):
        result = self._run_general_agent("Tell me about KMR")
        responses = result["bot_response"]
        self.assertEqual(responses[0]["type"], "text")
        self.assertEqual(responses[0]["text"], "KMR info")
        cta = next(r for r in responses if r.get("type") == "cta_url")
        self.assertEqual(cta["url"], KMR_URL)
        self.assertEqual(cta["display_text"], "Explore KMR")
        self.assertEqual(cta["_compose"], "kmr_cta")

    def test_non_kmr_query_has_no_cta_button(self):
        result = self._run_general_agent("what is your return policy?")
        types = [r.get("type") for r in result["bot_response"]]
        self.assertNotIn("cta_url", types)

    def test_llm_repeating_the_link_is_stripped_from_the_text(self):
        # Live bug: the model sometimes writes the link itself even though the
        # KB/prompt says not to -- the customer must never see it twice (once
        # in the message, once as the button).
        message_text = (
            "KMR is Kisna's savings plan. Enroll online at "
            "https://meriroshni.kisna.com/ or visit any store."
        )
        result = self._run_general_agent("tell me about KMR", message_text=message_text)
        responses = result["bot_response"]
        self.assertNotIn("meriroshni.kisna.com", responses[0]["text"])
        cta = next(r for r in responses if r.get("type") == "cta_url")
        self.assertEqual(cta["url"], KMR_URL)

    def test_strip_url_mentions_never_empties_the_message(self):
        from kisna_chatbot.processors.general_agent import _strip_url_mentions

        self.assertEqual(
            _strip_url_mentions(
                "https://meriroshni.kisna.com/", "https://meriroshni.kisna.com/"
            ),
            "https://meriroshni.kisna.com/",
        )
        self.assertEqual(_strip_url_mentions("", KMR_URL), "")
        self.assertEqual(
            _strip_url_mentions("KMR is great!", KMR_URL), "KMR is great!"
        )


if __name__ == "__main__":
    unittest.main()
