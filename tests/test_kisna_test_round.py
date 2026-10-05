"""Fix round from the Kisna test review (2026-10-05): policy questions are
answered, not handed off; the client's exact text for EMI banks and for
expert / human-agent requests; the sample certificate button; request-ID
suffixes; the booking-rate and no-invented-timelines KB rules."""

import asyncio
import os
import re
import unittest
import unittest.mock
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

    def test_list_number_needs_a_dot_or_bracket_and_a_space(self):
        from kisna_chatbot.processors.classifier import strip_list_number

        for kept in ("18k gold rings", "916 gold", "22 carat", "2 rings under 50k", "14KT vs 18KT",
                     "2.5 carat ring", "18.5k budget", "3)rings"):
            with self.subTest(kept=kept):
                self.assertEqual(strip_list_number(kept), kept)
        self.assertEqual(strip_list_number("2. rings under 50k"), "rings under 50k")
        self.assertEqual(strip_list_number("2) rings under 50k"), "rings under 50k")

    def test_untouched_messages_route_as_before(self):
        # The classifier receives the original text for these: same LLM input,
        # same programmatic verdicts as without the number stripping.
        from kisna_chatbot.processors.classifier import (
            _programmatic_intent_override,
            is_karat_comparison,
            strip_list_number,
        )

        for q in ("18k gold rings", "916 gold", "22 carat", "2 rings under 50k", "14KT vs 18KT"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(strip_list_number(q)), _programmatic_intent_override(q))
        self.assertEqual(_programmatic_intent_override("14KT vs 18KT"), ("karat_comparison", 0.95))
        self.assertTrue(is_karat_comparison(strip_list_number("14KT vs 18KT")))

    def test_customisation_questions_get_the_kb_answer(self):
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for q in ("Can you customise this?", "can you customize", "can I get it customised", "31. Can you customise this?",
                  "Could you customize this ring?", "is customisation possible?"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(q), ("general", 0.95))
        for q in ("I want to place a custom order", "can you do a bespoke necklace", "custom ring banwana hai"):
            with self.subTest(q=q):
                self.assertNotEqual(_programmatic_intent_override(q), ("general", 0.95))
        self.assertEqual(_programmatic_intent_override("can you do a bespoke necklace"), ("human_handoff", 0.95))

    def test_size_exchange_stays_an_exchange(self):
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for q in ("Can I exchange it for another size?", "exchange for a different size", "15. Can I exchange it for another size?"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(q), ("returns_refund", 0.92))
        self.assertIsNone(_programmatic_intent_override("Can I change the size?"))


# A Tuesday, 11:00 IST: inside working hours, no holiday.
_TUE_1100 = int(__import__("datetime").datetime(2026, 10, 6, 11, 0, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).timestamp())
EXPERT_FAQ = "Of course! 💬 I can arrange a conversation with a Kisna jewellery expert. Please choose your preferred callback time."
HUMAN_FAQ = "Certainly. I’ll connect you with a Kisna support representative."
Q48 = "48. I want to talk to an expert or connect to expert or call back"


class _FakeUsers:
    """The arm-once marker filter of _process_one_handoff and the candidate
    query of _sweep_callback_fallback, applied to one in-memory profile."""

    def __init__(self, profile):
        self.profile = profile

    def find_one_and_update(self, flt, update):
        sent = self.profile.get("handoff_callback_sent_at")
        ok = any(
            ("$exists" in c["handoff_callback_sent_at"] and sent is None)
            or ("$lt" in c["handoff_callback_sent_at"] and sent is not None and sent < c["handoff_callback_sent_at"]["$lt"])
            for c in flt["$or"]
        )
        if not ok:
            return None
        self.profile.update(update["$set"])
        return dict(self.profile)

    def find(self, query):
        p = self.profile
        match = (
            p.get("live_agent_required") is query["live_agent_required"]
            and (p.get("human_takeover") or {}).get("active") is not True
        )
        rows = [dict(p)] if match else []
        cursor = unittest.mock.MagicMock()
        cursor.sort.return_value.limit.return_value = rows
        return cursor


class _FakeCallbacks:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q):
        for d in self.docs:
            if d["phone_number"] == q["phone_number"] and d["status"] == q["status"] and d["preferred_date"] >= q["preferred_date"]["$gte"]:
                return d
        return None


class ExplicitHandoffTests(unittest.TestCase):
    def _build(self, text, in_hours):
        profile = {"username": "Asha"}
        with patch.object(sh, "is_within_working_hours", return_value=in_hours), \
             patch.object(sh, "send_customer_support_template") as notify, \
             patch("kisna_chatbot.config.gupshup.get_callback_flow_id", return_value="flow-cb"):
            out = sh.build_explicit_handoff_bot_response("919812345678", profile, text)
        return out, profile, notify

    def test_in_hours_connecting_message_and_no_form(self):
        from kisna_chatbot.constants import KIA_HANDOFF_MESSAGE

        for q in (Q48, "52. I want a connect human agent", "call back please"):
            with self.subTest(q=q):
                out, profile, notify = self._build(q, True)
                self.assertEqual([r["text"] for r in out], [KIA_HANDOFF_MESSAGE])
                self.assertFalse(any(r["type"] == "flow" for r in out))
                self.assertTrue(profile["live_agent_required"])
                self.assertNotIn("handoff_callback_sent_at", profile)  # the fallback stays armed
                self.assertTrue(notify.called)

    def test_out_of_hours_faq_text_and_form_immediately(self):
        out, profile, notify = self._build(Q48, False)
        self.assertEqual(out[0]["text"], EXPERT_FAQ)
        self.assertEqual(out[1]["type"], "flow")
        out, profile, notify = self._build("I want a human agent", False)
        self.assertEqual(out[0]["text"], HUMAN_FAQ)
        self.assertEqual(out[1]["type"], "flow")
        self.assertNotIn("live_agent_required", profile)
        self.assertFalse(notify.called)

    # --- the 5-minute fallback after an in-hours #48 -------------------------
    def _profile_after_48(self):
        _, profile, _ = self._build(Q48, True)
        profile.update(phone_number="919812345678", client_id="kisna", language="en", live_agent_requested_at=_TUE_1100)
        return profile

    def _fallback_at(self, profile, now, callbacks=()):
        from kisna_chatbot.processors import handoff_sweep as hs

        users = _FakeUsers(profile)
        with patch.object(hs, "users", users), \
             patch.object(hs, "callback_requests", _FakeCallbacks(list(callbacks))), \
             patch.object(hs, "send_callback_request_flow", return_value={"ok": True}) as flow, \
             patch.object(hs, "send_text_message_with_retry") as text, \
             patch.object(hs, "save_agent_message"), \
             patch.object(hs.logger, "info") as log:
            sent = asyncio.run(hs._process_one_handoff(dict(users.profile), now))
        return sent, flow, text, log

    def test_no_agent_reply_exactly_one_fallback_at_5_working_minutes(self):
        from kisna_chatbot.processors import handoff_sweep as hs

        profile = self._profile_after_48()
        sent, flow, _, _ = self._fallback_at(profile, _TUE_1100 + 200)
        self.assertFalse(sent)
        flow.assert_not_called()  # not due yet
        sent, flow, text, _ = self._fallback_at(profile, _TUE_1100 + 300)
        self.assertTrue(sent)
        flow.assert_called_once_with("919812345678", hs._FALLBACK_TEXT)  # apology + form, one message
        text.assert_not_called()
        sent, flow, _, log = self._fallback_at(profile, _TUE_1100 + 360)
        self.assertFalse(sent)
        flow.assert_not_called()  # never a second one
        self.assertEqual(log.call_args.kwargs["extra"]["reason"], "already_sent_this_episode")

    def test_agent_replies_in_time_no_fallback(self):
        from kisna_chatbot.processors import handoff_sweep as hs

        profile = self._profile_after_48()
        # The agent takes over (dashboard) at 2 minutes and replies.
        profile["human_takeover"] = {"active": True, "taken_at": _TUE_1100 + 120}
        users = _FakeUsers(profile)
        captured = {}

        def find(query):
            captured.update(query)
            return users.find(query)

        with patch.object(hs.users, "find", side_effect=find), \
             patch.object(hs, "send_callback_request_flow") as flow, \
             patch.object(hs, "send_text_message_with_retry") as text, \
             patch.object(hs.time, "time", return_value=_TUE_1100 + 300):
            sent = asyncio.run(hs._sweep_callback_fallback(25))
        self.assertEqual(sent, 0)
        flow.assert_not_called()
        text.assert_not_called()
        self.assertEqual(captured["human_takeover.active"], {"$ne": True})

    def test_past_dated_pending_callback_does_not_block_it(self):
        past = {"phone_number": "919812345678", "status": "pending", "preferred_date": "2026-08-15"}
        sent, flow, _, _ = self._fallback_at(self._profile_after_48(), _TUE_1100 + 300, [past])
        self.assertTrue(sent)
        flow.assert_called_once()

    def test_callback_today_or_later_blocks_it_and_the_skip_is_logged(self):
        for day in ("2026-10-06", "2026-10-09"):
            with self.subTest(day=day):
                booked = {"phone_number": "919812345678", "status": "pending", "preferred_date": day}
                sent, flow, _, log = self._fallback_at(self._profile_after_48(), _TUE_1100 + 300, [booked])
                self.assertFalse(sent)
                flow.assert_not_called()
                self.assertEqual(log.call_args.kwargs["extra"]["reason"], "pending_callback_today_or_later")


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
