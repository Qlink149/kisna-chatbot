"""Routing upgrades for the text-first classifier: video_call, scheme/KMR, gold rate."""

import os
import unittest
from unittest.mock import patch

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

from kisna_chatbot.main import app  # noqa: F401  (breaks logger/env init cycle)
from kisna_chatbot.processors.classifier import (
    _programmatic_intent_override,
    _route_resolved_intent,
)
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier


class ProgrammaticOverrideTests(unittest.TestCase):
    def test_video_call_english(self):
        self.assertEqual(
            _programmatic_intent_override("Can you schedule a video call?"),
            ("video_call", 0.95),
        )

    def test_video_call_hinglish(self):
        self.assertEqual(
            _programmatic_intent_override("video pe jewellery dikha sakte ho"),
            ("video_call", 0.95),
        )

    def test_video_consultation(self):
        self.assertEqual(
            _programmatic_intent_override("video consultation book karni hai"),
            ("video_call", 0.95),
        )

    def test_unboxing_video_not_video_call(self):
        self.assertIsNone(_programmatic_intent_override("unboxing video bhej du kya"))

    def test_scheme_generic(self):
        self.assertEqual(
            _programmatic_intent_override("Koi scheme hai kya"),
            ("general", 0.9),
        )

    def test_scheme_kmr(self):
        self.assertEqual(
            _programmatic_intent_override("KMR ke baare mein batao"),
            ("general", 0.9),
        )

    def test_scheme_meri_roshni(self):
        self.assertEqual(
            _programmatic_intent_override("meri roshni plan kya hai"),
            ("general", 0.9),
        )

    def test_scheme_saving_plan(self):
        self.assertEqual(
            _programmatic_intent_override("gold saving plan available?"),
            ("general", 0.9),
        )

    def test_offer_still_routes_via_llm_not_scheme(self):
        # Plain offer queries must NOT be swallowed by the scheme override.
        self.assertIsNone(_programmatic_intent_override("koi offer hai kya"))

    def test_gold_rate_conversational(self):
        self.assertEqual(
            _programmatic_intent_override("sona kitne ka chal raha hai"),
            ("gold_rate", 0.95),
        )

    def test_gold_rate_karat(self):
        self.assertEqual(
            _programmatic_intent_override("22kt ka bhav batao"),
            ("gold_rate", 0.95),
        )


class VideoCallRoutingTests(unittest.TestCase):
    def _route(self, profile):
        data = {"phone_number": "919999999999", "user_profile": profile}
        stopped = _route_resolved_intent(
            data,
            profile,
            "919999999999",
            "can you schedule a video call?",
            [],
            "video_call",
            0.95,
        )
        return stopped, data

    def test_sends_video_call_flow_when_configured(self):
        with patch(
            "kisna_chatbot.config.gupshup.get_videocall_flow_id",
            return_value="flow-123",
        ):
            profile = {"chat_history": []}
            stopped, data = self._route(profile)
        self.assertTrue(stopped)
        self.assertEqual(data["bot_response"][0]["type"], "flow")
        self.assertEqual(data["bot_response"][0]["flow"], "video_call_request")

    def test_falls_back_to_text_capture_without_flow_id(self):
        with patch(
            "kisna_chatbot.config.gupshup.get_videocall_flow_id",
            return_value=None,
        ):
            profile = {"chat_history": []}
            stopped, data = self._route(profile)
        self.assertTrue(stopped)
        self.assertEqual(data["bot_response"][0]["type"], "text")
        self.assertEqual(profile.get("callback_capture_step"), 1)
        self.assertEqual(
            profile.get("callback_draft", {}).get("request_type"), "video_call"
        )


class EntityExtractorPromptTests(unittest.TestCase):
    """Extractor prompt must stay in sync with _sanitize_llm_entities allowlists."""

    def test_style_schema_matches_sanitizer(self):
        from kisna_chatbot.processors.classifier import _LLM_ENTITY_STYLES
        from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor

        for style in _LLM_ENTITY_STYLES:
            self.assertIn(style, kisna_entity_extractor, f"style '{style}' missing")

    def test_lightweight_maps_to_minimal(self):
        from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor

        self.assertIn("lightweight", kisna_entity_extractor)
        self.assertIn("halka", kisna_entity_extractor)

    def test_disambiguation_rules_present(self):
        from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor

        self.assertIn("NEGATION", kisna_entity_extractor)
        self.assertIn("gram", kisna_entity_extractor.lower())
        self.assertIn("under 22k", kisna_entity_extractor)

    def test_classifier_prompt_mirrors_key_entity_rules(self):
        self.assertIn("lightweight", kisna_classifier)
        self.assertIn("NEGATION", kisna_classifier)


class IndicScriptGateTests(unittest.TestCase):
    """Indic-script messages must always reach the LLM classifier."""

    def _profile_in_product_session(self):
        from kisna_chatbot.models.service_list import ServiceList as SL

        return {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "chat_history": [{"role": "user", "content": "necklace dikhao"}],
            "last_search_filters": {"category": "necklace"},
        }

    def _should_run(self, text, profile):
        from kisna_chatbot.processors.classifier import Classifier

        data = {
            "phone_number": "919999999999",
            "messages": {"text": {"body": text}},
            "user_profile": profile,
        }
        return Classifier().should_run(data)

    def test_devanagari_always_classifies_in_sticky_session(self):
        # Gujarati-in-Devanagari "do you have rings" previously reused the
        # stale necklace search because no Latin regex matched.
        self.assertTrue(
            self._should_run("तमारा पासे रिंग छे", self._profile_in_product_session())
        )

    def test_gujarati_script_always_classifies(self):
        self.assertTrue(
            self._should_run("તમારી પાસે રિંગ છે?", self._profile_in_product_session())
        )

    def test_latin_refinement_still_skips_llm(self):
        # Cost control: plain Latin in-session refinements keep skipping the LLM.
        self.assertFalse(
            self._should_run("show me gold rings", self._profile_in_product_session())
        )


class BudgetReplyGateTests(unittest.TestCase):
    def test_budget_like_replies(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _looks_like_budget_reply,
        )

        for text in ("50000", "under 25k", "1 lakh", "das hazaar", "15000-35000"):
            self.assertTrue(_looks_like_budget_reply(text), text)

    def test_non_budget_sentences_escape(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _looks_like_budget_reply,
        )

        for text in (
            "इसका price बहुत ज्यादा है।",
            "that's too costly",
            "mehnga hai yaar",
        ):
            self.assertFalse(_looks_like_budget_reply(text), text)


class ClassifierPromptContentTests(unittest.TestCase):
    """The LLM prompt must agree with the code's intent set."""

    def test_prompt_declares_new_intents(self):
        self.assertIn("**video_call**", kisna_classifier)
        self.assertIn("**gold_rate**", kisna_classifier)

    def test_prompt_routes_schemes_to_general(self):
        self.assertIn("KMR", kisna_classifier)
        self.assertIn("Meri Roshni", kisna_classifier)

    def test_prompt_explains_active_context(self):
        self.assertIn("Active context:", kisna_classifier)


if __name__ == "__main__":
    unittest.main()