"""Facts served by code, not by the model (processors/code_served_facts.py),
and GeneralAgent's sentence-initial "Unfortunately" replacement."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.processors import code_served_facts as csf  # noqa: E402
from kisna_chatbot.processors import general_agent as ga  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    _programmatic_intent_fallback,
    _programmatic_intent_override,
    _route_resolved_intent,
)
from kisna_chatbot.utils import message_trace, reply_composer  # noqa: E402

CLIENT_TEXT = (
    "Certainly! 💍 The main difference between 14KT and 18KT is the gold purity "
    "— 18KT contains 75% pure gold, 14KT a little less. Visually, there is "
    "generally no significant difference. Both are available at KISNA. If you'd "
    "like, I can help you find a design in either. ✨"
)


class KaratTriggerTests(unittest.TestCase):
    def test_comparisons_trigger(self):
        for t in (
            "14K or 18K which is better?",
            "14kt vs 18kt",
            "difference between 14 karat and 18 karat",
            "is 18K better?",
            "18kt ya 14kt kaunsa accha hai",
            "compare 14k and 18k",
        ):
            with self.subTest(t=t):
                self.assertTrue(csf.is_karat_comparison(t))

    def test_shopping_and_single_karat_do_not_trigger(self):
        for t in (
            "show me 18K rings or earrings",
            "18k rings under 50k",
            "I want 18kt gold",
            "14K ring price",
            "do you have 22k?",
            "which is better, gold or diamond?",
        ):
            with self.subTest(t=t):
                self.assertFalse(csf.is_karat_comparison(t))


class KaratAnswerTests(unittest.TestCase):
    def test_client_wording_verbatim_and_tagged_canned(self):
        (item,) = csf.karat_comparison_response()
        self.assertEqual(item["text"], CLIENT_TEXT)
        self.assertEqual(item["_compose"], "karat_comparison_canned")
        self.assertEqual(item["_pin"], ("14KT", "18KT", "75%"))

    def test_classifier_hard_override_and_outage_fallback(self):
        self.assertEqual(_programmatic_intent_override("14K or 18K which is better?"), ("karat_comparison", 0.95))
        self.assertEqual(_programmatic_intent_fallback("14kt vs 18kt"), ("karat_comparison", 0.95))

    def test_routed_intent_serves_canned_and_marks_outcome(self):
        data = {"phone_number": "919812345678", "client_id": "kisna", "messages": {}}
        profile = {"service_selected": "product_search"}
        stop = _route_resolved_intent(data, profile, "919812345678", "14k vs 18k", [], "karat_comparison", 0.95)
        self.assertTrue(stop)
        self.assertEqual(data["bot_response"][0]["text"], CLIENT_TEXT)
        self.assertEqual(data["_trace_outcome"], "canned_sent")
        self.assertEqual(profile["service_selected"], "")
        self.assertIn("canned_sent", message_trace._OUTCOMES)

    def test_general_agent_backstop_never_calls_the_model(self):
        data = {
            "phone_number": "919812345678",
            "client_id": "kisna",
            "messages": {"text": {"body": "14K or 18K which is better?"}},
            "user_profile": {"language": "en"},
        }
        with patch.object(ga, "run_general_agent", new_callable=AsyncMock) as run:
            out = asyncio.run(ga.GeneralAgent().process(data))
        run.assert_not_awaited()
        self.assertEqual(out["bot_response"][0]["text"], CLIENT_TEXT)
        self.assertEqual(out["_trace_outcome"], "canned_sent")

    def _localize(self, language):
        data = {
            "messages": {"type": "text", "text": {"body": "14k or 18k?"}},
            "user_profile": {"language": language},
            "bot_response": csf.karat_comparison_response(),
        }
        with patch.object(
            reply_composer, "compose", new_callable=AsyncMock, side_effect=lambda key, text, **k: text
        ) as comp, patch.object(reply_composer, "narrate", new_callable=AsyncMock) as narr:
            asyncio.run(reply_composer.localize_bot_responses(data))
        return data, comp, narr

    def test_english_is_verbatim(self):
        data, comp, narr = self._localize("en")
        comp.assert_not_awaited()
        narr.assert_not_awaited()
        self.assertEqual(data["bot_response"][0]["text"], CLIENT_TEXT)
        self.assertNotIn("_pin", data["bot_response"][0])

    def test_other_languages_translate_with_figures_pinned(self):
        _, comp, narr = self._localize("hi")
        narr.assert_not_awaited()
        kwargs = comp.await_args.kwargs
        self.assertEqual(kwargs["language"], "hi")
        for pin in ("14KT", "18KT", "75%"):
            self.assertIn(pin, kwargs["pin"])


class UnfortunatelyReplacementTests(unittest.TestCase):
    def test_sentence_initial_is_replaced(self):
        self.assertEqual(
            ga._replace_sentence_unfortunately(
                "Please note that currently we deliver in 4–5 working days. "
                "Unfortunately, express delivery is not available."
            ),
            "Please note that currently we deliver in 4–5 working days. "
            "Please note that express delivery is not available.",
        )
        self.assertEqual(
            ga._replace_sentence_unfortunately("unfortunately, We cannot ship today."),
            "Please note that we cannot ship today.",
        )
        self.assertEqual(
            ga._replace_sentence_unfortunately("Line one\nUnfortunately, the store is closed."),
            "Line one\nPlease note that the store is closed.",
        )

    def test_sentence_start_after_emoji(self):
        # The exact live shape from the 52-question eval: emoji between the
        # full stop and "Unfortunately".
        self.assertEqual(
            ga._replace_sentence_unfortunately(
                "KISNA offers standard delivery within 4–5 working days across India. "
                "🚚✨ Unfortunately, express delivery is not available at this time."
            ),
            "KISNA offers standard delivery within 4–5 working days across India. "
            "🚚✨ Please note that express delivery is not available at this time.",
        )

    def test_keeps_case_of_I_and_acronyms(self):
        self.assertEqual(
            ga._replace_sentence_unfortunately("Unfortunately, KISNA does not offer 22KT."),
            "Please note that KISNA does not offer 22KT.",
        )
        self.assertEqual(
            ga._replace_sentence_unfortunately("Unfortunately, I cannot help with that."),
            "Please note that I cannot help with that.",
        )

    def test_mid_sentence_word_and_its_comma_are_removed(self):
        # The live shape from the KB eval (#39, "Can I return a sale item?").
        self.assertEqual(
            ga._replace_sentence_unfortunately(
                "We offer a 7-day return window for regular items, but "
                "unfortunately, this does not apply to sale items."
            ),
            "We offer a 7-day return window for regular items, but this does "
            "not apply to sale items.",
        )
        self.assertEqual(
            ga._replace_sentence_unfortunately("The parcel was unfortunately delayed by the courier."),
            "The parcel was delayed by the courier.",
        )

    def test_sentence_end_drops_the_comma_before_it(self):
        self.assertEqual(
            ga._replace_sentence_unfortunately("It is not available, unfortunately."),
            "It is not available.",
        )
        self.assertEqual(
            ga._replace_sentence_unfortunately("That design is sold out unfortunately!"),
            "That design is sold out!",
        )

    def test_start_and_mid_in_one_text(self):
        self.assertEqual(
            ga._replace_sentence_unfortunately(
                "Fine. Unfortunately, the store is closed, but unfortunately, it reopens Monday."
            ),
            "Fine. Please note that the store is closed, but it reopens Monday.",
        )


class RegistryTests(unittest.TestCase):
    def test_registry_names_both_code_served_facts(self):
        doc = csf.__doc__
        self.assertIn("Making-charge percentages", doc)
        self.assertIn("14KT vs 18KT", doc)
        self.assertIn("revisit the model choice", doc)


if __name__ == "__main__":
    unittest.main()
