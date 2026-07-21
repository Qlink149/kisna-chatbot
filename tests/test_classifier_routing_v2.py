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

    def test_latin_refinement_now_classifies(self):
        # LLM-default policy: in-session refinements go through the classifier.
        self.assertTrue(
            self._should_run("show me gold rings", self._profile_in_product_session())
        )

    def test_pure_show_more_still_skips_llm(self):
        # The only surviving product-session skip: unambiguous continuations.
        self.assertFalse(
            self._should_run("show more", self._profile_in_product_session())
        )
        self.assertFalse(
            self._should_run("aur dikhao", self._profile_in_product_session())
        )

    def test_long_sentence_with_more_still_classifies(self):
        self.assertTrue(
            self._should_run(
                "can you show me some more affordable gold rings please",
                self._profile_in_product_session(),
            )
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


class PriceDirectionTests(unittest.TestCase):
    """LLM-detected relative price refinements (cheaper / pricier)."""

    def test_sanitizer_accepts_directions(self):
        from kisna_chatbot.processors.classifier import _sanitize_llm_entities

        self.assertEqual(
            _sanitize_llm_entities({"price_direction": "lower"})["price_direction"],
            "lower",
        )
        self.assertEqual(
            _sanitize_llm_entities({"price_direction": "HIGHER"})["price_direction"],
            "higher",
        )
        self.assertIsNone(
            _sanitize_llm_entities({"price_direction": "sideways"})["price_direction"]
        )
        self.assertIsNone(_sanitize_llm_entities({})["price_direction"])

    def test_lower_moves_band_30_percent_down(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _entities_for_price_direction,
        )

        profile = {
            "last_search_filters": {"category": "necklace", "max_price": 50000},
        }
        entities, bound = _entities_for_price_direction(profile, "lower")
        self.assertEqual(bound, 35000)
        self.assertEqual(entities["max_price"], 35000)
        self.assertIsNone(entities["min_price"])
        self.assertEqual(entities["category"], "necklace")

    def test_lower_anchors_on_shown_products_without_filter(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _entities_for_price_direction,
        )

        profile = {
            "last_search_filters": {"category": "ring"},
            "last_search_products": [{"price": 30000}, {"price": 45000}],
        }
        entities, bound = _entities_for_price_direction(profile, "lower")
        self.assertEqual(bound, 21000)  # 70% of cheapest shown
        self.assertEqual(entities["max_price"], 21000)

    def test_lower_has_price_floor(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _entities_for_price_direction,
        )

        profile = {"last_search_filters": {"max_price": 2500}}
        _entities, bound = _entities_for_price_direction(profile, "lower")
        self.assertEqual(bound, 2000)

    def test_higher_moves_band_30_percent_up(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _entities_for_price_direction,
        )

        profile = {"last_search_filters": {"category": "ring", "max_price": 50000}}
        entities, bound = _entities_for_price_direction(profile, "higher")
        self.assertEqual(bound, 65000)
        self.assertEqual(entities["min_price"], 65000)
        self.assertIsNone(entities["max_price"])

    def test_no_context_returns_none(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _entities_for_price_direction,
        )

        self.assertEqual(
            _entities_for_price_direction({}, "lower"), (None, None)
        )

    def test_prompts_teach_price_direction(self):
        from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor

        self.assertIn("price_direction", kisna_classifier)
        self.assertIn("price_direction", kisna_entity_extractor)

    def test_prompts_teach_range_suffix_distribution(self):
        # LLM-primary: the suffix-distribution rule (25-30k → 25k-30k) must be
        # in the prompts, not only the regex fallback.
        from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor

        self.assertIn("25-30k", kisna_classifier)
        self.assertIn("distribute", kisna_classifier.lower())
        self.assertIn("25-30k", kisna_entity_extractor)


class FlowSwitchAckDeadEndTests(unittest.TestCase):
    """The silent-switch ack must never suppress the service pipeline.

    Regression: 'Return krna hai' during browsing produced ONLY 'Sure — I'll
    help with returns.' because the ack became bot_response and every
    downstream agent skipped itself.
    """

    def test_switch_to_returns_still_reaches_returns_agent(self):
        import asyncio
        import json
        from unittest.mock import AsyncMock

        from kisna_chatbot.models.service_list import ServiceList as SL
        from kisna_chatbot.processors.classifier import (
            Classifier,
            _prepend_flow_switch_ack,
        )
        from kisna_chatbot.processors.returns_refund_agent import ReturnsRefundAgent

        async def _run():
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Return krna hai"}},
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "gold rings"}],
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {"intent": "returns_refund", "confidence": 0.9, "entities": {}}
                ),
            ):
                data = await Classifier().process(data)

            # Classifier must NOT have produced an ack-only bot_response.
            self.assertNotIn("bot_response", data)
            self.assertIn("_flow_switch_ack", data)

            data = await ReturnsRefundAgent().process(data)
            self.assertIn("bot_response", data)

            _prepend_flow_switch_ack(data)
            self.assertEqual(len(data["bot_response"]), 2)
            self.assertEqual(data["bot_response"][0]["type"], "text")
            self.assertEqual(data["bot_response"][1]["type"], "flow")
            self.assertNotIn("_flow_switch_ack", data)

        asyncio.run(_run())


class NativeScriptExtractionTests(unittest.TestCase):
    """Native script must not be second-class: the Latin regex gate must never
    strip the LLM's correct extraction on Devanagari / Gujarati text."""

    def test_evidence_gate_trusts_llm_on_devanagari(self):
        from kisna_chatbot.processors.entity_extractor import apply_llm_evidence_gate

        llm = {
            "category": "ring",
            "material_type": "gold",
            "metal_colour": None,
            "karat": None,
            "size": None,
            "occasion": None,
            "style": None,
            "gender": None,
            "collection": None,
        }
        out = apply_llm_evidence_gate("सोने की अंगूठी", llm)
        self.assertEqual(out["material_type"], "gold")  # not stripped

    def test_evidence_gate_trusts_llm_on_gujarati(self):
        from kisna_chatbot.processors.entity_extractor import apply_llm_evidence_gate

        llm = {"category": "earring", "material_type": "diamond", "gender": "women"}
        out = apply_llm_evidence_gate("મારે હીરાની બુટ્ટી જોઈએ", llm)
        self.assertEqual(out["material_type"], "diamond")
        self.assertEqual(out["gender"], "women")

    def test_evidence_gate_still_strips_unevidenced_latin(self):
        from kisna_chatbot.processors.entity_extractor import apply_llm_evidence_gate

        llm = {"category": "ring", "material_type": "gold", "gender": "men"}
        out = apply_llm_evidence_gate("gold ring", llm)
        self.assertIsNone(out["gender"])  # Latin gate still guards hallucination

    def test_prompts_carry_native_script_examples(self):
        from kisna_chatbot.prompts.classifier_kisna import (
            kisna_classifier,
            kisna_entity_extractor,
        )

        # Devanagari + Gujarati present in both prompts now.
        self.assertIn("अंगूठी", kisna_classifier)
        self.assertIn("બુટ્ટી", kisna_classifier)
        self.assertIn("हज़ार", kisna_entity_extractor)


class CategoryDrivenSearchGuardTests(unittest.TestCase):
    """A extracted jewellery category means the user is shopping — never
    clarify or hand off, even on a low-confidence native-script classification."""

    def _run(self, body, llm_json):
        import asyncio
        import json as _json
        from unittest.mock import AsyncMock, patch

        from kisna_chatbot.processors.classifier import Classifier

        async def _go():
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": body}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=_json.dumps(llm_json),
            ):
                return await Classifier().process(data)

        return asyncio.run(_go())

    def test_low_conf_general_with_category_routes_to_search(self):
        data = self._run(
            "मुझे 4 हज़ार से ज़्यादा कीमत वाली अंगूठी चाहिए",
            {"intent": "general", "confidence": 0.3, "language": "hi",
             "entities": {"category": "ring", "min_price": 4000}},
        )
        self.assertEqual(data["classified_category"], "product_search")
        self.assertNotIn("bot_response", data)  # search pipeline will run

    def test_product_info_with_category_routes_to_search(self):
        data = self._run(
            "५० हज़ार से ज़्यादा कीमत वाला नेकलेस",
            {"intent": "product_info", "confidence": 0.4,
             "entities": {"category": "necklace", "min_price": 50000}},
        )
        self.assertEqual(data["classified_category"], "product_search")
        self.assertNotIn("bot_response", data)

    def test_genuine_faq_not_hijacked(self):
        # Classifier general + second extractor finds no category → stays general.
        import asyncio
        import json as _json
        from unittest.mock import AsyncMock, patch

        from kisna_chatbot.processors.classifier import Classifier

        async def _go():
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "return policy kya hai"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=_json.dumps(
                    {"intent": "general", "confidence": 0.9, "entities": {}}
                ),
            ), patch(
                "kisna_chatbot.processors.entity_extractor.extract_entities_with_llm",
                new_callable=AsyncMock,
                return_value={"category": None},
            ):
                return await Classifier().process(data)

        data = asyncio.run(_go())
        self.assertEqual(data["classified_category"], "general")

    def test_second_chance_rescues_native_product_query(self):
        # Classifier returns general + NO category (the real native-script
        # failure); the focused entity extractor finds the category → search.
        import asyncio
        import json as _json
        from unittest.mock import AsyncMock, patch

        from kisna_chatbot.processors.classifier import Classifier

        async def _go():
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "मुझे 4 हज़ार से ज़्यादा कीमत वाली अंगूठी चाहिए"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=_json.dumps(
                    {"intent": "general", "confidence": 0.3, "language": "hi",
                     "entities": {}}
                ),
            ), patch(
                "kisna_chatbot.processors.entity_extractor.extract_entities_with_llm",
                new_callable=AsyncMock,
                return_value={"category": "ring", "min_price": 4000},
            ):
                return await Classifier().process(data)

        data = asyncio.run(_go())
        self.assertEqual(data["classified_category"], "product_search")
        self.assertNotIn("bot_response", data)
        self.assertEqual(data["llm_extracted_entities"]["category"], "ring")


class FlowSwitchAckDoublingTests(unittest.TestCase):
    def test_ack_suppressed_before_slot_fill(self):
        from kisna_chatbot.processors.classifier import _prepend_flow_switch_ack

        data = {
            "_flow_switch_ack": "Sure — let's browse some jewellery.",
            "bot_response": [
                {"type": "text", "text": "What are you after?", "_compose": "slot_fill"}
            ],
        }
        _prepend_flow_switch_ack(data)
        self.assertEqual(len(data["bot_response"]), 1)  # no redundant ack

    def test_ack_prepended_before_normal_response(self):
        from kisna_chatbot.processors.classifier import _prepend_flow_switch_ack

        data = {
            "_flow_switch_ack": "Sure — let's look at your order.",
            "bot_response": [{"type": "text", "text": "Order tracking link…"}],
        }
        _prepend_flow_switch_ack(data)
        self.assertEqual(len(data["bot_response"]), 2)
        self.assertEqual(data["bot_response"][0]["_compose"], "flow_switch_ack")

    def test_ack_suppressed_before_products(self):
        # A Hinglish ack glued before an English product intro is jarring —
        # suppress it when the response already shows products.
        from kisna_chatbot.processors.classifier import _prepend_flow_switch_ack

        data = {
            "_flow_switch_ack": "Sure — let's browse jewellery.",
            "bot_response": [
                {"type": "text", "text": "Here are some lovely rings ✨"},
                {"type": "image_with_cta", "url": "x", "caption": "Ring"},
            ],
        }
        _prepend_flow_switch_ack(data)
        self.assertEqual(len(data["bot_response"]), 2)  # no ack prepended

    def test_ack_suppressed_before_pincode_prompt(self):
        from kisna_chatbot.processors.classifier import _prepend_flow_switch_ack

        data = {
            "_flow_switch_ack": "Sure — let's find a store.",
            "bot_response": [
                {"type": "text", "text": "Share your pincode", "_compose": "store_pincode"}
            ],
        }
        _prepend_flow_switch_ack(data)
        self.assertEqual(len(data["bot_response"]), 1)


class ReferenceCompareRepairTests(unittest.TestCase):
    _SHOWN = [
        {"_id": "1", "title": "Estaa Necklace", "price": {"finalPrice": 29504}},
        {"_id": "2", "title": "Harini Necklace", "price": {"finalPrice": 32100}},
        {"_id": "3", "title": "Sibhani Necklace", "price": {"finalPrice": 27800}},
    ]

    def test_shown_products_context_numbered(self):
        from kisna_chatbot.processors.classifier import _format_shown_products

        ctx = _format_shown_products({"last_search_products": self._SHOWN})
        self.assertIn("1. Estaa Necklace", ctx)
        self.assertIn("2. Harini Necklace", ctx)

    def test_product_reference_sanitized(self):
        from kisna_chatbot.processors.classifier import _sanitize_llm_entities

        self.assertEqual(_sanitize_llm_entities({"product_reference": "2"})["product_reference"], 2)
        self.assertIsNone(_sanitize_llm_entities({"product_reference": 99})["product_reference"])
        self.assertIsNone(_sanitize_llm_entities({})["product_reference"])

    def test_reference_opens_that_product(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _handle_product_reference,
        )

        data = {
            "user_profile": {"last_search_products": self._SHOWN},
            "llm_extracted_entities": {"product_reference": 2},
        }
        result = _handle_product_reference(data)
        self.assertIsNotNone(result)
        self.assertIn("Harini", str(result["bot_response"]))
        # opening it marks it as viewed
        self.assertIsNotNone(data["user_profile"].get("last_viewed_product"))

    def test_reference_out_of_range_falls_through(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _handle_product_reference,
        )

        data = {
            "user_profile": {"last_search_products": self._SHOWN},
            "llm_extracted_entities": {"product_reference": 9},
        }
        self.assertIsNone(_handle_product_reference(data))

    def test_compare_is_grounded_and_factual(self):
        from kisna_chatbot.processors.product_search_agent_v3 import _handle_compare

        data = {"user_profile": {"last_search_products": self._SHOWN}}
        result = _handle_compare(data)
        self.assertIsNotNone(result)
        text = result["bot_response"][0]["text"]
        # cheapest/priciest stated factually from real prices
        self.assertIn("Sibhani Necklace", text)  # cheapest 27,800
        self.assertIn("Harini Necklace", text)   # priciest 32,100
        self.assertIn("27,800", text)
        self.assertIn("32,100", text)

    def test_repair_intent_acknowledges_and_clarifies(self):
        import asyncio
        import json as _json
        from unittest.mock import AsyncMock, patch

        from kisna_chatbot.processors.classifier import Classifier

        async def _go():
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "no that's not what I meant"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=_json.dumps({"intent": "repair", "confidence": 0.9, "entities": {}}),
            ):
                return await Classifier().process(data)

        data = asyncio.run(_go())
        self.assertEqual(data["classified_category"], "repair")
        self.assertEqual(data["bot_response"][0]["_compose"], "repair")
        self.assertNotIn("Sent flow", str(data["bot_response"]))

    def test_prompts_teach_reference_compare_repair(self):
        self.assertIn("product_reference", kisna_classifier)
        self.assertIn("**compare**", kisna_classifier)
        self.assertIn("**repair**", kisna_classifier)


class NarratorGuardrailTests(unittest.TestCase):
    def test_narrator_prompt_forbids_inventing_products(self):
        # The greeting narrator hallucinated "want to see silver rings?" — the
        # instruction must forbid inventing products and mentioning silver.
        import inspect

        from kisna_chatbot.utils import reply_composer

        src = inspect.getsource(reply_composer.narrate)
        self.assertIn("Do NOT invent", src)
        self.assertIn("silver", src)


class ScriptMirrorLanguageTests(unittest.TestCase):
    """Reply language: identity from the LLM, SCRIPT from the user's message."""

    def _resolve(self, lang, text):
        from kisna_chatbot.processors.classifier import resolve_reply_language

        return resolve_reply_language(lang, text)

    def test_latin_message_forces_latn_variant(self):
        # Model says "hi" but user typed Latin → Hinglish, not Devanagari.
        self.assertEqual(self._resolve("hi", "Return krna hai"), "hi-Latn")
        self.assertEqual(self._resolve("gu", "tamara kem che"), "gu-Latn")
        self.assertEqual(self._resolve("mr", "mala ring pahije"), "mr-Latn")

    def test_native_script_forces_plain_code(self):
        self.assertEqual(self._resolve("hi-Latn", "रिटर्न करना है"), "hi")
        self.assertEqual(self._resolve("gu-Latn", "તમારી પાસે રિંગ છે?"), "gu")

    def test_english_unaffected(self):
        self.assertEqual(self._resolve("en", "I want to return"), "en")

    def test_matching_script_passes_through(self):
        self.assertEqual(self._resolve("hi", "रिटर्न करना है"), "hi")
        self.assertEqual(self._resolve("hi-Latn", "Return krna hai"), "hi-Latn")

    def test_store_language_last_message_wins(self):
        from kisna_chatbot.processors.classifier import _store_language

        profile = {}
        _store_language(profile, "hi", "रिटर्न करना है")
        self.assertEqual(profile["language"], "hi")
        # Next message is Hinglish; even without a fresh LLM label the stored
        # language's script is corrected to this message.
        _store_language(profile, None, "Return krna hai")
        self.assertEqual(profile["language"], "hi-Latn")
        _store_language(profile, "en", "I want to return")
        self.assertEqual(profile["language"], "en")

    def test_composer_labels_romanized_variants(self):
        from kisna_chatbot.utils.reply_composer import _language_label

        self.assertIn("Latin", _language_label("gu-Latn"))
        self.assertIn("Gujarati", _language_label("gu-Latn"))
        self.assertIn("Hinglish", _language_label("hi-Latn"))


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