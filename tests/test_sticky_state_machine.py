"""Sticky-state machine: waits are mutually exclusive and always escapable.

Fixtures are drawn from two real production conversations (12 Aug 2026) in
which both users ended with awaiting_store_pincode AND shopping_wizard_active
set at the same time. The wizard won every turn, so store pincodes were read
as budgets and requests for a human were answered with "what's your budget?".
"""

import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_TOKEN": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "JWT_SECRET_KEY": "test",
    "SYSTEM_API_KEY": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_OFFERS_API": "http://localhost/offers",
    "KISNA_STORE_API": "http://localhost/stores",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "KB_ENABLED": "false",
}.items():
    os.environ.setdefault(_k, _v)


def _fresh_ts() -> int:
    return int(time.time())


from kisna_chatbot.models.service_list import ServiceList as SL  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    _store_language,
    detect_language_override,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    advance_wizard,
    budget_rejection_reason,
    start_wizard,
)
from kisna_chatbot.utils.session_state import start_store_lookup  # noqa: E402


class MutualExclusionTests(unittest.TestCase):
    """FIX A — two sticky waits must never be armed at once."""

    def test_starting_store_lookup_clears_wizard(self):
        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "budget",
            "shopping_wizard_data": {"category": "mangalsutra"},
        }
        start_store_lookup(profile)
        self.assertTrue(profile["awaiting_store_pincode"])
        self.assertFalse(profile.get("shopping_wizard_active"))
        self.assertIsNone(profile.get("shopping_wizard_step"))
        self.assertIsNone(profile.get("shopping_wizard_data"))

    def test_starting_wizard_clears_store_wait(self):
        profile = {"awaiting_store_pincode": True, "store_pincode_attempts": 2}
        start_wizard(profile)
        self.assertTrue(profile["shopping_wizard_active"])
        self.assertFalse(profile.get("awaiting_store_pincode"))
        self.assertIsNone(profile.get("store_pincode_attempts"))

    def test_wizard_start_also_clears_custom_budget_wait(self):
        profile = {"awaiting_custom_budget": True, "custom_budget_attempts": 1}
        start_wizard(profile)
        self.assertFalse(profile.get("awaiting_custom_budget"))
        self.assertIsNone(profile.get("custom_budget_attempts"))

    def test_transcript_repro_store_ask_during_active_wizard(self):
        """Yogansh 17:47 mangalsutra funnel, 17:48 'store in Udaipur?'.

        The store ask must take the funnel down with it, so the pincode that
        follows reaches the store lookup instead of the budget slot.
        """
        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "budget",
            "shopping_wizard_data": {"category": "mangalsutra", "gender": "women"},
            "service_selected": SL.PRODUCT_SEARCH.value,
        }
        start_store_lookup(profile)
        self.assertTrue(profile["awaiting_store_pincode"])
        self.assertFalse(profile.get("shopping_wizard_active"))


class UniversalEscapeTests(unittest.TestCase):
    """FIX B — some intents leave any wait, whatever the phrasing."""

    def _wizard_data(self, body: str) -> dict:
        return {
            "phone_number": "919999999999",
            "messages": {"text": {"body": body}},
            "user_profile": {
                "chat_history": [],
                "service_selected": SL.PRODUCT_SEARCH.value,
                "shopping_wizard_active": True,
                "shopping_wizard_step": "fulfillment",
                "shopping_wizard_data": {"category": "mangalsutra"},
                "last_message_at": _fresh_ts(),
            },
            "client_id": "kisna",
        }

    def test_unmatched_handoff_phrasing_escapes_wizard(self):
        """Yogansh 18:01 — the phrase no escape regex knew."""

        async def _run():
            clf = Classifier()
            data = self._wizard_data("I want to talk to a representative from Kisna")
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                side_effect=[
                    "new_request",  # escape gate
                    json.dumps(
                        {
                            "intent": "human_handoff",
                            "confidence": 0.95,
                            "entities": {},
                        }
                    ),
                ],
            ) as mock_llm, patch(
                "kisna_chatbot.processors.support_handler."
                "send_customer_support_template"
            ), patch(
                "kisna_chatbot.processors.support_handler.get_support_status",
                return_value={"status": "open"},
            ):
                result = await clf.process(data)

            # Gate + full classifier: the wait was released, then the LLM
            # decided the intent (never the gate).
            self.assertEqual(mock_llm.await_count, 2)
            self.assertFalse(result["user_profile"].get("shopping_wizard_active"))
            self.assertEqual(result["classified_category"], "human_handoff")
            text = (result["bot_response"][0].get("text") or "").lower()
            self.assertNotIn("budget", text)
            self.assertNotIn("ready to ship", text)

        asyncio.run(_run())

    def test_gate_declining_keeps_the_wizard(self):
        """A real slot answer must NOT be torn out of the funnel.

        "made to order" is the wizard's own button label. It used to match
        _CUSTOM_JEWELLERY_RE and hand the user to a live agent mid-funnel.
        """

        async def _run():
            clf = Classifier()
            data = self._wizard_data("made to order")
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value="answer",
            ) as mock_llm:
                result = await clf.process(data)

            self.assertEqual(mock_llm.await_count, 1)  # gate only
            self.assertTrue(result["user_profile"].get("shopping_wizard_active"))

        asyncio.run(_run())

    def test_gate_sees_the_pending_question(self):
        """The gate judges against what we actually asked, not a fixed list."""

        async def _run():
            clf = Classifier()
            data = self._wizard_data("Any thing Whatever is your bestseller")
            with patch(
                "kisna_chatbot.processors.classifier._quick_escape_classify",
                new_callable=AsyncMock,
                return_value=False,
            ) as gate:
                await clf.process(data)
            gate.assert_awaited_once()
            question = gate.await_args.args[1]
            self.assertIn("Ready to ship", question)

        asyncio.run(_run())

    def test_offtopic_message_no_regex_knows_still_escapes(self):
        """'show me something cheaper' matched no escape regex and was eaten."""

        async def _run():
            clf = Classifier()
            data = self._wizard_data("show me something cheaper")
            with patch(
                "kisna_chatbot.processors.classifier._quick_escape_classify",
                new_callable=AsyncMock,
                return_value=True,  # gate: new_request
            ), patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "intent": "product_search",
                        "confidence": 0.85,
                        "entities": {"price_direction": "lower"},
                    }
                ),
            ):
                result = await clf.process(data)
            self.assertFalse(result["user_profile"].get("shopping_wizard_active"))
            self.assertEqual(result["classified_category"], "product_search")

        asyncio.run(_run())

    def test_gate_outage_falls_back_to_regex_not_worse(self):
        """A gate outage must land on the PRE-GATE behaviour, never worse.

        No regex knows this phrasing, so the funnel keeps the turn — which is
        exactly what shipped before the gate existed.
        """

        async def _run():
            clf = Classifier()
            data = self._wizard_data("Any thing Whatever is your bestseller")
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("gate down"),
            ):
                result = await clf.process(data)
            self.assertTrue(result["user_profile"].get("shopping_wizard_active"))

        asyncio.run(_run())

    def test_gate_outage_still_honours_a_regex_escape(self):
        """The regex escapes we ship today must survive a gate outage."""

        async def _run():
            clf = Classifier()
            data = self._wizard_data("do you have a store in udaipur")
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("everything down"),
            ):
                result = await clf.process(data)
            self.assertFalse(result["user_profile"].get("shopping_wizard_active"))
            self.assertEqual(result["classified_category"], "store_info")

        asyncio.run(_run())

    def test_gate_verdict_beats_the_regex_for_a_real_slot_answer(self):
        """"ring" at the category step is an ANSWER, not a new search.

        _looks_like_browse_escape reads a bare category word as a product
        search, so the regex alone would tear down the funnel the user is
        halfway through. The gate outranks it.
        """

        async def _run():
            clf = Classifier()
            data = self._wizard_data("ring")
            data["user_profile"]["shopping_wizard_step"] = "category"
            with patch(
                "kisna_chatbot.processors.classifier._quick_escape_classify",
                new_callable=AsyncMock,
                return_value=False,  # gate: this answers the question
            ):
                result = await clf.process(data)
            self.assertTrue(result["user_profile"].get("shopping_wizard_active"))

        asyncio.run(_run())

    def test_gate_not_called_without_a_sticky_wait(self):
        """Normal turns pay nothing for this feature."""

        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "show me gold rings"}},
                "user_profile": {
                    "chat_history": [],
                    "service_selected": "",
                    "last_message_at": _fresh_ts(),
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "intent": "product_search",
                        "confidence": 0.95,
                        "entities": {"category": "ring"},
                    }
                ),
            ) as mock_llm:
                await clf.process(data)
            self.assertEqual(mock_llm.await_count, 1)  # classifier only, no gate

        asyncio.run(_run())

    def test_regex_matched_handoff_escapes_store_wait_without_gate(self):
        """'Connect me to an agent' is known to the regex — no extra call."""

        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Connect me to an agent"}},
                "user_profile": {
                    "chat_history": [],
                    "service_selected": SL.AD_FLOW.value,
                    "awaiting_store_pincode": True,
                    "last_message_at": _fresh_ts(),
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {"intent": "human_handoff", "confidence": 0.95, "entities": {}}
                ),
            ) as mock_llm, patch(
                "kisna_chatbot.processors.support_handler."
                "send_customer_support_template"
            ), patch(
                "kisna_chatbot.processors.support_handler.get_support_status",
                return_value={"status": "open"},
            ):
                result = await clf.process(data)

            self.assertEqual(mock_llm.await_count, 1)  # no gate needed
            self.assertFalse(result["user_profile"].get("awaiting_store_pincode"))
            self.assertEqual(result["classified_category"], "human_handoff")
            self.assertTrue(result["user_profile"].get("live_agent_required"))

        asyncio.run(_run())


class BudgetGuardTests(unittest.TestCase):
    """FIX C — pincodes and phone numbers are not budgets."""

    def test_reason_classification(self):
        self.assertEqual(budget_rejection_reason("987654321"), "too_large")
        self.assertEqual(budget_rejection_reason("313001"), "pincode")
        self.assertEqual(budget_rejection_reason("123456"), "pincode")
        # Real budgets must pass straight through.
        self.assertIsNone(budget_rejection_reason("30000"))
        self.assertIsNone(budget_rejection_reason("50k"))
        self.assertIsNone(budget_rejection_reason("1 lakh"))
        self.assertIsNone(budget_rejection_reason("20 hazaar ke aas pass"))
        self.assertIsNone(budget_rejection_reason("100000"))

    def _budget_profile(self) -> dict:
        return {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "budget",
            "shopping_wizard_data": {"category": "ring", "gender": "women"},
        }

    def test_nine_digit_number_rejected_as_budget(self):
        """Laksh 17:55 — '987654321' became a Rs 98.7 crore search."""
        profile = self._budget_profile()
        status, responses = advance_wizard(profile, {}, text="987654321")
        self.assertEqual(status, "reask")
        collected = profile["shopping_wizard_data"]
        self.assertIsNone(collected.get("min_price"))
        self.assertIsNone(collected.get("max_price"))
        self.assertIn("budget", (responses[0].get("text") or "").lower())

    def test_six_digit_pincode_rejected_as_budget(self):
        """Yogansh 17:48 / Laksh 17:47 — '313001' at the budget step."""
        profile = self._budget_profile()
        status, _ = advance_wizard(profile, {}, text="313001")
        self.assertEqual(status, "reask")
        collected = profile["shopping_wizard_data"]
        self.assertIsNone(collected.get("min_price"))
        self.assertIsNone(collected.get("max_price"))

    def test_real_budget_still_accepted(self):
        profile = self._budget_profile()
        advance_wizard(profile, {}, text="30000")
        collected = profile["shopping_wizard_data"]
        self.assertIsNotNone(
            collected.get("min_price") or collected.get("max_price")
        )


class MtoIsAFilterNotAHandoffTests(unittest.TestCase):
    """Made-to-order is a catalogue filter sent to the search API.

    _CUSTOM_JEWELLERY_RE used to contain "made to order" and a bare
    "custom|customize|customise" — the exact strings _FULFILLMENT_TITLE_MAP
    accepts as availability answers. Since that regex feeds a hard 0.95
    override that beats the LLM, typing the wizard's own button label routed
    the user to a design expert instead of filtering the catalogue.
    """

    FILTER_PHRASES = [
        "made to order",
        "Made to order",
        "made-to-order",
        "make to order",
        "custom",
        "customize",
        "customise",
        "ready to ship",
        "either is fine",
        "Mujhe make to order chahiye",
        "made to order gold necklace",
    ]

    BESPOKE_PHRASES = [
        "custom ring banwana hai",
        "custom design chahiye",
        "engraving chahiye",
        "personalised ring for my wife",
        "I want custom jewellery",
        "can you do a bespoke necklace",
        "I want to connect with someone for custom jewellery",
        "naam likhwana hai ring pe",
        "design my own ring",
    ]

    def _hands_off(self, text: str) -> bool:
        from kisna_chatbot.processors.classifier import (
            _is_custom_jewellery_query,
            _programmatic_intent_override,
        )

        override = _programmatic_intent_override(text)
        return bool(_is_custom_jewellery_query(text)) or (
            override is not None and override[0] == "human_handoff"
        )

    def test_availability_answers_never_hand_off(self):
        for text in self.FILTER_PHRASES:
            with self.subTest(text=text):
                self.assertFalse(self._hands_off(text))

    def test_bespoke_requests_still_hand_off(self):
        for text in self.BESPOKE_PHRASES:
            with self.subTest(text=text):
                self.assertTrue(self._hands_off(text))

    def test_ordinary_search_not_hijacked(self):
        for text in ("personally I like gold", "show me gold rings"):
            with self.subTest(text=text):
                self.assertFalse(self._hands_off(text))

    def test_mto_phrases_still_extract_as_fulfillment(self):
        """The filter meaning must survive — this is what the API needs."""
        from kisna_chatbot.processors.entity_extractor import extract_fulfillment

        for text in ("made to order", "make to order", "customize"):
            with self.subTest(text=text):
                self.assertEqual(extract_fulfillment(text), "mto")


class LanguageOverrideTests(unittest.TestCase):
    """FIX D — an explicit language request outranks detection."""

    def test_detection(self):
        self.assertEqual(
            detect_language_override("talk to me in English only please"), "en"
        )
        self.assertEqual(detect_language_override("sirf English mein baat karo"), "en")
        self.assertEqual(detect_language_override("please reply in Hindi"), "hi")
        self.assertEqual(
            detect_language_override("Can you tell me about kisna in English please?"),
            "en",
        )
        self.assertIsNone(detect_language_override("show me gold rings"))
        self.assertIsNone(detect_language_override("mujhe ring chahiye"))

    def test_override_persists_against_later_detection(self):
        """Yogansh 15:43 — asked for English, got three more Hindi replies."""
        profile: dict = {}
        _store_language(
            profile,
            None,
            "I want to increase my budget from 35,000 to 60,000 and more "
            "talk to me in English only please",
        )
        self.assertEqual(profile.get("language_override"), "en")
        self.assertEqual(profile["language"], "en")

        # A later Devanagari-labelled turn must not undo the request.
        _store_language(profile, "hi", "मुझे पेंडेंट दिखाओ")
        self.assertEqual(profile["language"], "en")

    def test_override_cleared_on_fresh_start(self):
        from kisna_chatbot.utils.session_state import reset_session_on_fresh_start

        profile = {"language_override": "en", "language": "en"}
        reset_session_on_fresh_start(profile)
        self.assertIsNone(profile.get("language_override"))

    def test_language_switch_right_after_a_wizard_prompt_is_not_swallowed(self):
        """A real tester's "In English" was answered with the same stale
        Hindi prompt, twice running -- right after the wizard's category
        question, "In English" reads as an attempted ANSWER to that question,
        so Classifier.process() returned before _store_language (the only
        caller of detect_language_override) ever ran. Only a longer, more
        distinctive phrasing on the third try escaped and reached it.

        detect_language_override must now be checked before that decision,
        so the message escapes on the FIRST try and the escape gate's own
        LLM call is skipped entirely -- there is nothing for it to decide.
        """

        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "In English"}},
                "user_profile": {
                    "chat_history": [],
                    "language": "hi",
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "shopping_wizard_active": True,
                    "shopping_wizard_step": "category",
                    "shopping_wizard_data": {},
                    "last_message_at": _fresh_ts(),
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                side_effect=[
                    json.dumps(
                        {"intent": "general", "confidence": 0.9, "entities": {}}
                    ),
                ],
            ) as mock_llm:
                result = await clf.process(data)

            # Exactly one call: the full classifier. The escape gate's own
            # LLM call never fires -- detect_language_override decided this
            # before the gate was even consulted.
            self.assertEqual(mock_llm.await_count, 1)
            profile = result["user_profile"]
            self.assertEqual(profile.get("language_override"), "en")
            self.assertEqual(profile.get("language"), "en")

        asyncio.run(_run())


class EscapeRoutingTests(unittest.TestCase):
    """Stage 3c — an escape must survive a classifier LLM failure."""

    def test_classified_category_set_on_escape_when_llm_fails(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold rings"}},
                "user_profile": {
                    "awaiting_store_pincode": True,
                    "service_selected": SL.AD_FLOW.value,
                    "chat_history": [{"role": "user", "content": "find store"}],
                    "last_message_at": _fresh_ts(),
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ):
                result = await clf.process(data)

            self.assertFalse(result["user_profile"].get("awaiting_store_pincode"))
            self.assertEqual(result["classified_category"], "product_search")
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.PRODUCT_SEARCH.value,
            )
            text = (result.get("bot_response") or [{}])[0].get("text") or ""
            self.assertNotIn("didn't catch", text.lower())

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
