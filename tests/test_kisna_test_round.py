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
        for line in ('"cancel my order #KIS12345" -> human_handoff',
                     '"I want to place a custom order" -> human_handoff', '"talk to a human" -> human_handoff'):
            self.assertIn(line, CLASSIFIER_PROMPT)
        # No specific order: the KB says how to cancel (pinned in code too).
        self.assertIn('"order cancel karna hai" | "cancel order" | "how do I cancel my order" -> general', CLASSIFIER_PROMPT)


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

    def test_ring_fit_and_cancel_questions_get_the_kb_answer(self):
        # Tester 917977104875, 2026-10-06: the ring question reached the
        # shopping wizard, the cancel question a live-agent handoff.
        from kisna_chatbot.processors.classifier import _programmatic_intent_override, strip_list_number

        for q in ("What if the ring doesn't fit?", "12. What if the ring doesn't fit?", "what if the ring doesn’t fit?",
                  "What if the ring doesn't fit",
                  "what if the size does not fit", "Can I cancel my order?", "46. Can I cancel my order?",
                  ". Can I cancel my order?", "can i cancel my order?", "Can I cancel my order", "how do I cancel my order",
                  "cancel order", "order cancel karna hai", "is cancellation possible?"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(strip_list_number(q)), ("general", 0.95))

    def test_specific_orders_complaints_and_shopping_keep_their_routes(self):
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for q in ("cancel my order #1234", "cancel order KIS-SV-20260929-D172", "cancel my order 12345678",
                  "cancel order id ABC", "I want to cancel my order, the product is damaged",
                  "connect me to an agent to cancel my order", "wrong size delivered", "the ring I received doesn't fit",
                  "ring delivered yesterday doesnt fit", "show me rings in size 12", "I have a complaint",
                  "My product is damaged", "How do I know my ring size?", "Is resizing free?"):
            with self.subTest(q=q):
                self.assertNotEqual(_programmatic_intent_override(q), ("general", 0.95))
        self.assertEqual(_programmatic_intent_override("Can I exchange it for another size?"), ("returns_refund", 0.92))

    def test_ring_fit_statements_get_the_complaint_form(self):
        # A customer saying the ring does not fit has a real problem: the
        # complaint form, not the "reach out to us" sentence (client, 2026-10-07).
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for q in ("ring doesnt fit", "ring size is wrong what now", "my ring is loose", "my ring is too tight",
                  "the ring I received doesn't fit", "wrong ring size"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(q), ("complaint", 0.92))
        for q in ("show me rings in size 12", "small ring for my daughter", "How do I know my ring size?"):
            with self.subTest(q=q):
                self.assertIsNone(_programmatic_intent_override(q))

    def test_ring_fit_statement_gets_the_form_end_to_end(self):
        from kisna_chatbot.processors.classifier import Classifier

        async def _go(text):
            data = {"phone_number": "919999999999", "messages": {"text": {"body": text}},
                    "user_profile": {"chat_history": [], "service_selected": ""}, "client_id": "kisna"}
            llm = AsyncMock(side_effect=AssertionError("model must not be called"))
            with patch("kisna_chatbot.processors.classifier.complete_chat", llm):
                return await Classifier().process(data)

        for text in ("ring doesnt fit", "ring size is wrong what now", "my ring is loose"):
            with self.subTest(text=text):
                data = asyncio.run(_go(text))
                self.assertEqual(data["classified_category"], "complaint")
                self.assertEqual(data["user_profile"]["service_selected"], "complaint")
                self.assertIn("type", data["bot_response"][0])

    def test_compliant_typo_is_a_complaint(self):
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for q in ("Compliant", "compliant.", "complain", "Complaint"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(q), ("complaint", 0.95))
        self.assertIsNone(_programmatic_intent_override("I have a complaint about the compliant process"))

    def test_engraving_question_gets_the_kb_answer(self):
        # With the tester's history the LLM handed it off 10/10.
        from kisna_chatbot.processors.classifier import _programmatic_intent_override, strip_list_number

        for q in ("Can I engrave a name?", "32. Can I engrave a name?", "32.\tCan I engrave a name?",
                  "can i get it engraved", "Can I personalise it?"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(strip_list_number(q)), ("general", 0.95))
        for q in ("engraving chahiye", "I want my name engraved", "naam likhwana hai", "I want to place a custom order"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(q), ("human_handoff", 0.95))

    def test_natural_diamond_question_gets_the_kb_answer(self):
        # 9/10 the LLM returned "product_question" (an entity field, not an
        # intent), which ends in "Sorry, I didn't catch that".
        from kisna_chatbot.processors.classifier import _programmatic_intent_override, strip_list_number

        for q in ("Is this natural diamond?", "3. Is this natural diamond?", "is it natural or lab grown",
                  "Are these lab-grown?", "Is the diamond natural?", "Are your diamonds real?"):
            with self.subTest(q=q):
                self.assertEqual(_programmatic_intent_override(strip_list_number(q)), ("general", 0.95))
        for q in ("show me natural diamond rings", "natural diamond earrings under 50k", "Is this genuine?"):
            with self.subTest(q=q):
                self.assertIsNone(_programmatic_intent_override(q))

    def test_ring_fit_skips_the_category_guard(self):
        # The LLM said general; its "ring" entity then turned that into
        # product_search. The pin answers before either model call.
        import json as _json

        from kisna_chatbot.processors.classifier import Classifier

        async def _go(text):
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": text}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            llm = AsyncMock(return_value=_json.dumps({"intent": "general", "confidence": 0.9, "entities": {"category": "ring"}}))
            with patch("kisna_chatbot.processors.classifier.complete_chat", llm), patch(
                "kisna_chatbot.processors.entity_extractor.extract_entities_with_llm",
                new_callable=AsyncMock,
                return_value={"category": "ring"},
            ):
                return await Classifier().process(data), llm

        for text in ("What if the ring doesn't fit?", "12. What if the ring doesn't fit?", "Can I cancel my order?"):
            with self.subTest(text=text):
                data, llm = asyncio.run(_go(text))
                self.assertEqual(data["classified_category"], "general")
                llm.assert_not_called()


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


class RingFitTests(unittest.TestCase):
    # Client's answer, 2026-10-07: a pre-purchase "what if", not a complaint --
    # no "I'm sorry for the inconvenience" opener.
    CLIENT = ("No worries! If the ring doesn't fit, just reach out to us and we'll help "
              "you with the available size exchange or resizing options.")

    def test_exact_client_sentence(self):
        self.assertEqual(csf.RING_FIT_TEXT, self.CLIENT)
        self.assertNotIn("sorry", csf.RING_FIT_TEXT.lower())

    def test_trigger(self):
        for q in ("What if the ring doesn't fit?", "12. What if the ring doesn\u2019t fit?", "12.\tWhat if the ring doesn't fit?",
                  "what if the ring doesn't fit", "what if the size does not fit"):
            with self.subTest(q=q):
                self.assertTrue(csf.is_ring_fit_question(q))
        for q in ("ring doesnt fit", "ring size is wrong what now", "my ring is loose",
                  "the ring I received doesn't fit", "ring delivered yesterday doesnt fit", "wrong size delivered",
                  "How do I know my ring size?", "Is resizing free?", "show me rings in size 12"):
            with self.subTest(q=q):
                self.assertFalse(csf.is_ring_fit_question(q))

    def test_general_agent_serves_it_without_the_model(self):
        for q in ("12. What if the ring doesn't fit?", "what if the ring doesn't fit"):
            data = {"phone_number": "919812345678", "client_id": "kisna",
                    "messages": {"text": {"body": q}}, "user_profile": {"language": "en"}}
            with patch("kisna_chatbot.processors.general_agent.run_general_agent", new_callable=AsyncMock) as run:
                out = asyncio.run(GeneralAgent().process(data))
            with self.subTest(q=q):
                run.assert_not_awaited()
                self.assertEqual(out["bot_response"][0]["text"], self.CLIENT)
                self.assertEqual(out["_trace_outcome"], "canned_sent")


class CancelOrderTests(unittest.TestCase):
    # Client's text, 2026-10-07: all three ways, served by code for the plain
    # English question (the model dropped the email when an older answer was
    # in the chat).
    CLIENT = ("You can cancel your order any time before it has been shipped. 📦 Please raise a cancellation "
              "request through My Account, contact our Customer Support team, or email us at support@kisna.com "
              "with all the relevant details. Once the order has been shipped, cancellation may no longer be possible.")

    def test_exact_client_text(self):
        self.assertEqual(csf.CANCEL_ORDER_TEXT, self.CLIENT)

    def test_trigger_plain_english_only(self):
        for q in ("Can I cancel my order?", "46. Can I cancel my order?", "46.\tCan I cancel my order?",
                  ". Can I cancel my order?", "can i cancel my order", "how do I cancel my order", "cancel order"):
            with self.subTest(q=q):
                self.assertTrue(csf.is_cancel_order_question(q))
        for q in ("cancel my order #1234", "cancel order KIS12345", "order cancel karna hai", "mera order cancel karo",
                  "Can I cancel a digital gold purchase?", "I want to cancel my order, the product is damaged"):
            with self.subTest(q=q):
                self.assertFalse(csf.is_cancel_order_question(q))

    def test_hinglish_still_goes_to_the_model(self):
        # Routed to general (the KB answer, in the customer's language) but
        # not code-served: the model writes it.
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        self.assertEqual(_programmatic_intent_override("order cancel karna hai"), ("general", 0.95))
        self.assertFalse(csf.is_cancel_order_question("order cancel karna hai"))
        self.assertIn("names all three ways to cancel", __import__(
            "kisna_chatbot.prompts.kisna_knowledge_base", fromlist=["x"]).KISNA_KNOWLEDGE_BASE_V2)


class HistoryVariantTests(unittest.TestCase):
    """An older, DIFFERENT answer to the same question is in the chat history;
    today's code-served answer must come back, without the model."""

    OLD = "Certainly! You can do this through My Account or by contacting Customer Support. 18K is richer, 14K is more durable."

    def _ask(self, q):
        profile = {"language": "en", "chat_history": [
            {"role": "user", "content": q}, {"role": "assistant", "content": self.OLD},
            {"role": "user", "content": "ok thanks"}, {"role": "assistant", "content": "You're welcome!"}]}
        data = {"phone_number": "919812345678", "client_id": "kisna",
                "messages": {"text": {"body": q}}, "user_profile": profile}
        with patch("kisna_chatbot.processors.general_agent.run_general_agent", new_callable=AsyncMock) as run:
            out = asyncio.run(GeneralAgent().process(data))
        run.assert_not_awaited()
        return out["bot_response"][0]["text"]

    def test_code_served_answers_ignore_an_older_answer(self):
        for q, text in (("What if the ring doesn't fit?", csf.RING_FIT_TEXT),
                        ("Can I cancel my order?", csf.CANCEL_ORDER_TEXT),
                        ("Which banks offer EMI?", csf.EMI_BANKS_TEXT),
                        ("14K or 18K which is better?", csf.KARAT_COMPARISON_TEXT)):
            with self.subTest(q=q):
                self.assertEqual(self._ask(q), text)

    def test_engraving_route_ignores_history(self):
        # Pinned before the LLM, so an older "yes, we engrave" answer in the
        # chat cannot change where it goes (the KB eval checks the answer).
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        self.assertEqual(_programmatic_intent_override("Can I engrave a name?"), ("general", 0.95))


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
        # Client's wording names all three: My Account, Customer Support, support@kisna.com.
        self.assertIn("through My Account, by contacting Customer Support, or by emailing support@kisna.com", self.PROMPT)
        self.assertIn("My Account, Customer Support, and the email support@kisna.com", self.PROMPT)

    def test_diamond_card_is_the_certificate(self):
        self.assertIn('Sample diamond certificate (a "diamond card" means the certificate)', self.PROMPT)


if __name__ == "__main__":
    unittest.main()
