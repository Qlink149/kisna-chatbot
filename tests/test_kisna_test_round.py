"""Fix round from the Kisna test review (2026-10-05): policy questions are
answered, not handed off; the client's exact text for EMI banks and for
expert / human-agent requests; the sample certificate button; request-ID
suffixes; the booking-rate and no-invented-timelines KB rules."""

import asyncio
import os
import re
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test")
os.environ.setdefault("SYSTEM_API_KEY", "test")

from kisna_chatbot.processors import code_served_facts as csf  # noqa: E402
from kisna_chatbot.processors import support_handler as sh  # noqa: E402
from kisna_chatbot.processors.classifier import _is_custom_jewellery_query  # noqa: E402
from kisna_chatbot.processors.general_agent import GeneralAgent, SAMPLE_CERTIFICATE_URL  # noqa: E402
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier_intent as CLASSIFIER_PROMPT  # noqa: E402
from kisna_chatbot.prompts.general_agent_kisna import build_general_agent_prompt  # noqa: E402
from kisna_chatbot.utils.request_ids import generate_request_id  # noqa: E402

TESTER_POLICY_QUESTIONS = (
    "Is the diamond certified?",
    "Can I see the certificate?",
    "Can I change the size?",
    "What if the ring doesn't fit?",
    "Can I exchange old gold?",
    "Can I change the delivery address?",
    "Can you customise this?",
    "Can I change the stone?",
    "Can I cancel my order?",
    "How long will customization take?",
)


class ClassifierPromptTests(unittest.TestCase):
    def test_handoff_is_for_explicit_actions_only(self):
        self.assertIn("an action on a SPECIFIC order", CLASSIFIER_PROMPT)
        self.assertIn("never human_handoff", CLASSIFIER_PROMPT)
        self.assertNotIn("Order cancellation or modification → human_handoff (bot cannot cancel).", CLASSIFIER_PROMPT)

    def test_every_tester_question_is_a_few_shot(self):
        for q in TESTER_POLICY_QUESTIONS:
            with self.subTest(q=q):
                self.assertIn(f'"{q}"', CLASSIFIER_PROMPT)
        for numbered in ("46. Can I cancel my order?", "11. Can I change the size?", "6. Is the diamond certified?",
                         "9. Can I see the certificate?", "31. Can you customise this?"):
            self.assertIn(f'"{numbered}"', CLASSIFIER_PROMPT)
        self.assertIn('"diamond card" -> general', CLASSIFIER_PROMPT)

    def test_explicit_handoffs_stay(self):
        for line in ('"order cancel karna hai" -> human_handoff', '"cancel my order #KIS12345" -> human_handoff',
                     '"I want to place a custom order" -> human_handoff', '"talk to a human" -> human_handoff'):
            self.assertIn(line, CLASSIFIER_PROMPT)


class CustomOverrideTests(unittest.TestCase):
    def test_a_question_is_not_a_custom_order(self):
        for q in ("Can I engrave a name?", "32. Can I engrave a name?", "Can I get initials on it?"):
            with self.subTest(q=q):
                self.assertFalse(_is_custom_jewellery_query(q))

    def test_custom_order_requests_still_hand_off(self):
        # A request for the service, even phrased as a question, stays a handoff.
        for q in ("engraving chahiye", "custom ring banwana hai", "I want a custom ring", "naam likhwana hai",
                  "I want to design my own ring", "can you do a bespoke necklace", "Do you do personalised jewellery?"):
            with self.subTest(q=q):
                self.assertTrue(_is_custom_jewellery_query(q))


class RoutingHelperTests(unittest.TestCase):
    def test_list_number_is_dropped_for_routing(self):
        from kisna_chatbot.processors.classifier import strip_list_number

        self.assertEqual(strip_list_number("46.\tCan I cancel my order?"), "Can I cancel my order?")
        self.assertEqual(strip_list_number('"9.\tCan I see the certificate?'), "Can I see the certificate?")
        self.assertEqual(strip_list_number("1) gold rings"), "gold rings")
        for kept in ("2.5 carat ring", "2", "18K ring", "50000"):
            self.assertEqual(strip_list_number(kept), kept)

    def test_size_exchange_stays_an_exchange(self):
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for q in ("Can I exchange it for another size?", "exchange for a different size", "15. Can I exchange it for another size?"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(q), ("returns_refund", 0.92))
        self.assertIsNone(_programmatic_intent_override("Can I change the size?"))


class ExplicitHandoffTests(unittest.TestCase):
    def _build(self, text, in_hours):
        profile = {"username": "Asha"}
        with patch.object(sh, "is_within_working_hours", return_value=in_hours), \
             patch.object(sh, "send_customer_support_template") as notify, \
             patch("kisna_chatbot.config.gupshup.get_callback_flow_id", return_value="flow-cb"):
            out = sh.build_explicit_handoff_bot_response("919812345678", profile, text)
        return out, profile, notify

    def test_expert_or_callback_gets_the_client_text_and_the_form(self):
        for q in ("48. I want to talk to an expert or connect to expert or call back", "call back please",
                  "connect me to an expert"):
            with self.subTest(q=q):
                out, _, _ = self._build(q, True)
                self.assertEqual(out[0]["text"], "Of course! 💬 I can arrange a conversation with a Kisna jewellery "
                                                 "expert. Please choose your preferred callback time.")
                self.assertEqual(out[1]["type"], "flow")

    def test_human_agent_gets_the_client_text_and_the_form(self):
        out, _, _ = self._build("52. I want a connect human agent", True)
        self.assertEqual(out[0]["text"], "Certainly. I’ll connect you with a Kisna support representative.")
        self.assertEqual(out[1]["type"], "flow")

    def test_in_hours_also_flags_a_live_agent(self):
        _, profile, notify = self._build("I want a human agent", True)
        self.assertTrue(profile["live_agent_required"])
        self.assertTrue(notify.called)

    def test_out_of_hours_sends_the_form_without_flagging(self):
        out, profile, notify = self._build("I want a human agent", False)
        self.assertEqual(out[1]["type"], "flow")
        self.assertNotIn("live_agent_required", profile)
        self.assertFalse(notify.called)


class EmiBanksTests(unittest.TestCase):
    CLIENT = (
        "Please note that EMI options are currently not available directly at KISNA. However, you can "
        "conveniently make your payment using a Credit Card from a major bank and, if your bank offers the "
        "option, convert the transaction into an EMI.\n\nFor any assistance or queries regarding the EMI "
        "conversion process, we kindly recommend reaching out to your bank’s customer support team. They will "
        "be happy to guide you further. 💳✨"
    )

    def test_exact_client_paragraph(self):
        self.assertEqual(csf.EMI_BANKS_TEXT, self.CLIENT)

    def test_trigger(self):
        for q in ("Which banks offer EMI?", "36. Which banks offer EMI?", "emi kaun se bank pe milega", "which bank gives emi"):
            with self.subTest(q=q):
                self.assertTrue(csf.is_emi_banks_question(q))
        for q in ("Is EMI available?", "bank holiday today?", "Can I pay by UPI?"):
            with self.subTest(q=q):
                self.assertFalse(csf.is_emi_banks_question(q))

    def test_general_agent_serves_it_without_the_model(self):
        data = {"phone_number": "919812345678", "client_id": "kisna",
                "messages": {"text": {"body": "36. Which banks offer EMI?"}}, "user_profile": {"language": "en"}}
        with patch("kisna_chatbot.processors.general_agent.run_general_agent", new_callable=AsyncMock) as run:
            out = asyncio.run(GeneralAgent().process(data))
        run.assert_not_awaited()
        self.assertEqual(out["bot_response"][0]["text"], self.CLIENT)
        self.assertEqual(out["_trace_outcome"], "canned_sent")

    def test_registry_names_it_with_the_reason(self):
        self.assertIn("client requires exact wording", csf.__doc__)


class CertificateButtonTests(unittest.TestCase):
    def _run(self, query):
        from kisna_chatbot.ai.types import GeneralAgentResult, ProviderName

        data = {"phone_number": "919812345678", "client_id": "kisna",
                "messages": {"text": {"body": query}}, "user_profile": {"service_selected": ""}}
        with patch("kisna_chatbot.processors.general_agent.run_general_agent", new_callable=AsyncMock,
                   return_value=GeneralAgentResult(message_text=f"Certainly! 💎 See {SAMPLE_CERTIFICATE_URL}",
                                                   live_agent_requested=False, provider=ProviderName.OPENAI,
                                                   model="test")):
            return asyncio.run(GeneralAgent().process(data))["bot_response"]

    def test_certificate_and_diamond_card_get_the_sample(self):
        for q in ("Can I see the certificate?", "9. Can I see the certificate?", "diamond card", "Show me the diamond card"):
            with self.subTest(q=q):
                out = self._run(q)
                cta = out[-1]
                self.assertEqual(cta["type"], "cta_url")
                self.assertEqual(cta["url"], SAMPLE_CERTIFICATE_URL)
                self.assertEqual(cta["text"], "This is a sample; your actual certificate may differ.")
                self.assertLessEqual(len(cta["display_text"]), 20)
                self.assertNotIn(SAMPLE_CERTIFICATE_URL, out[0]["text"])  # the link lives on the button

    def test_lost_or_missing_certificate_gets_no_sample(self):
        for q in ("I lost my certificate", "My diamond came without a certificate"):
            with self.subTest(q=q):
                self.assertFalse(any(r.get("type") == "cta_url" for r in self._run(q)))


class RequestIdTests(unittest.TestCase):
    def test_suffix_always_starts_with_a_letter(self):
        for prefix in ("CB", "VC", "CMP", "SV"):
            for _ in range(400):
                rid = generate_request_id(prefix)
                m = re.fullmatch(rf"KIS-{prefix}-\d{{8}}-([0-9A-F]{{4}})", rid)
                self.assertIsNotNone(m, rid)
                self.assertIn(m.group(1)[0], "ABCDEF", rid)


class KbRuleTests(unittest.TestCase):
    PROMPT = build_general_agent_prompt()

    def test_booking_rate_for_all_orders_and_locked(self):
        self.assertIn("Gold weight difference (all orders, not only GRP)", self.PROMPT)
        self.assertIn("charged or refunded at the booking rate (the gold rate at the time of booking)", self.PROMPT)
        self.assertIn("- Gold weight difference: charged or refunded at the booking rate", self.PROMPT)

    def test_no_invented_timelines(self):
        self.assertIn("never state a timeline, notification method or process that this knowledge base doesn't give", self.PROMPT)

    def test_cancellation_names_customer_support(self):
        self.assertIn("through My Account or by contacting Customer Support", self.PROMPT)

    def test_diamond_card_is_the_certificate(self):
        self.assertIn('Sample diamond certificate (a "diamond card" means the certificate)', self.PROMPT)


if __name__ == "__main__":
    unittest.main()
