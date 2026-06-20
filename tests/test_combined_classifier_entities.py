"""Tests for combined classifier + entity extraction."""

import asyncio
import json
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
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import (
    Classifier,
    _parse_classifier_json,
    _sanitize_llm_entities,
)
from kisna_chatbot.processors.entity_extractor import (
    apply_occasion_style_hints,
    combine_search_entities,
    extract_entities_with_llm,
    extract_structured_fields,
    finalize_search_entities,
    is_spurious_title,
    merge_llm_and_regex_entities,
)


class ParseClassifierJsonTests(unittest.TestCase):
    def test_parses_intent_confidence_entities(self):
        raw = json.dumps(
            {
                "intent": "product_search",
                "confidence": 0.93,
                "entities": {
                    "category": "ring",
                    "material_type": "gold",
                    "max_price": 50000,
                },
            }
        )
        parsed = _parse_classifier_json(raw)
        self.assertEqual(parsed["intent"], "product_search")
        self.assertEqual(parsed["confidence"], 0.93)
        self.assertEqual(parsed["entities"]["category"], "ring")


class SanitizeLlmEntitiesTests(unittest.TestCase):
    def test_nose_ring_maps_to_nosewear(self):
        out = _sanitize_llm_entities({"category": "nose_ring"})
        self.assertEqual(out["category"], "nosewear")

    def test_string_null_becomes_none(self):
        out = _sanitize_llm_entities({"category": "null", "title": ""})
        self.assertIsNone(out["category"])
        self.assertIsNone(out["title"])


class MergeEntitiesTests(unittest.TestCase):
    def test_llm_occasion_wins_regex_price_fills(self):
        merged = merge_llm_and_regex_entities(
            {"occasion": "anniversary", "max_price": None, "category": "ring"},
            {"max_price": 50000, "category": "pendant"},
        )
        self.assertEqual(merged["occasion"], "anniversary")
        self.assertEqual(merged["max_price"], 50000)
        self.assertEqual(merged["category"], "ring")

    def test_regex_title_ignored_when_llm_title_null(self):
        merged = merge_llm_and_regex_entities(
            {"title": None, "category": "ring"},
            {"title": "what", "category": "ring"},
        )
        self.assertIsNone(merged.get("title"))

    def test_llm_title_wins_over_regex(self):
        merged = merge_llm_and_regex_entities(
            {"title": "elysia", "category": "ring"},
            {"title": "nitara", "category": "ring"},
        )
        self.assertEqual(merged["title"], "elysia")

    def test_regex_price_fills_when_llm_max_price_null(self):
        merged = merge_llm_and_regex_entities(
            {"max_price": None, "category": "earring"},
            {"max_price": 30000, "category": "earring"},
        )
        self.assertEqual(merged["max_price"], 30000)


class FinalizeSearchEntitiesTests(unittest.TestCase):
    def test_chain_category_maps_to_necklace_with_api_override(self):
        finalized = finalize_search_entities(
            {"category": "chain", "material_type": "gold", "title": "chains"},
        )
        self.assertEqual(finalized["category"], "necklace")
        self.assertEqual(finalized["clara_category_override"], "chain")
        self.assertIsNone(finalized["title"])

    def test_is_spurious_title_blocks_question_words(self):
        self.assertTrue(is_spurious_title("What"))
        self.assertTrue(is_spurious_title("kisna"))
        self.assertFalse(is_spurious_title("elysia"))


class OccasionStyleHintsTests(unittest.TestCase):
    def test_anniversary_prefix(self):
        entities, prefix = apply_occasion_style_hints({"occasion": "anniversary"})
        self.assertIn("anniversary", prefix.lower())

    def test_birthday_defaults_to_earring(self):
        entities, _ = apply_occasion_style_hints({"occasion": "birthday"})
        self.assertEqual(entities["category"], "earring")


class ClassifierEntityStorageTests(unittest.TestCase):
    def test_llm_path_stores_entities(self):
        async def _run():
            clf = Classifier()
            llm_response = json.dumps(
                {
                    "intent": "product_search",
                    "confidence": 0.9,
                    "entities": {
                        "category": "ring",
                        "material_type": "gold",
                        "max_price": 50000,
                    },
                }
            )
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "sone ki anguthi 50k tak"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=llm_response,
            ):
                result = await clf.process(data)
            self.assertEqual(
                result["llm_extracted_entities"]["category"],
                "ring",
            )
            self.assertEqual(result["llm_extracted_entities"]["max_price"], 50000)

        asyncio.run(_run())

    def test_returns_refund_routes_via_llm_classifier(self):
        async def _run():
            clf = Classifier()
            llm_response = json.dumps(
                {"intent": "returns_refund", "confidence": 0.9, "entities": {}}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "wapas karna hai"}},
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "rings"}],
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=llm_response,
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "returns_refund")

        asyncio.run(_run())

    def test_combine_search_entities_structured_price_only(self):
        combined = combine_search_entities(
            {"category": "ring"},
            extract_structured_fields("rings under 30k"),
        )
        self.assertEqual(combined["category"], "ring")
        self.assertEqual(combined["max_price"], 30000)
        self.assertIsNone(combined.get("title"))

    def test_emi_general_all_null_entities(self):
        async def _run():
            clf = Classifier()
            llm_response = json.dumps(
                {
                    "intent": "general",
                    "confidence": 0.9,
                    "entities": {
                        "category": None,
                        "material_type": None,
                        "min_price": None,
                        "max_price": None,
                        "title": None,
                        "occasion": None,
                        "style": None,
                    },
                }
            )
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "EMI available hai?"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=llm_response,
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "general")
            stored = result["llm_extracted_entities"]
            self.assertIsNone(stored.get("category"))
            self.assertIsNone(stored.get("occasion"))

        asyncio.run(_run())


class ExtractEntitiesWithLlmTests(unittest.TestCase):
    def test_anniversary_gift_earrings(self):
        async def _run():
            llm_response = json.dumps(
                {
                    "category": "earring",
                    "material_type": None,
                    "occasion": "anniversary",
                    "min_price": None,
                    "max_price": None,
                    "title": None,
                }
            )
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                return_value=llm_response,
            ):
                result = await extract_entities_with_llm("anniversary gift earrings")
            self.assertEqual(result.get("occasion"), "anniversary")
            self.assertEqual(result.get("category"), "earring")

        asyncio.run(_run())

    def test_white_gold_dikhao(self):
        async def _run():
            llm_response = json.dumps(
                {
                    "category": None,
                    "material_type": "white_gold",
                    "metal_colour": "white",
                    "min_price": None,
                    "max_price": None,
                    "title": None,
                }
            )
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                return_value=llm_response,
            ):
                result = await extract_entities_with_llm("ab white gold dikhao")
            self.assertEqual(result.get("metal_colour"), "white")
            self.assertEqual(result.get("material_type"), "gold")

        asyncio.run(_run())

    def test_white_gold_dikhao_inherits_context_from_history(self):
        async def _run():
            llm_response = json.dumps(
                {
                    "category": "ring",
                    "material_type": "white_gold",
                    "metal_colour": "white",
                    "min_price": None,
                    "max_price": 50000,
                    "title": None,
                }
            )
            mock_complete = AsyncMock(return_value=llm_response)
            history = "User: diamond rings under 50k\nAssistant: Here are some rings"
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                mock_complete,
            ):
                result = await extract_entities_with_llm(
                    "white gold mein dikhao",
                    history_str=history,
                )
            user_msg = mock_complete.call_args.kwargs["messages"][0]["content"]
            self.assertIn("Recent conversation:", user_msg)
            self.assertIn("diamond rings under 50k", user_msg)
            self.assertIn("Current message: white gold mein dikhao", user_msg)
            self.assertEqual(result.get("category"), "ring")
            self.assertEqual(result.get("max_price"), 50000)
            self.assertEqual(result.get("metal_colour"), "white")

        asyncio.run(_run())

    def test_failure_returns_empty_dict(self):
        async def _run():
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM unavailable"),
            ):
                result = await extract_entities_with_llm("some query")
            self.assertEqual(result, {})

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
