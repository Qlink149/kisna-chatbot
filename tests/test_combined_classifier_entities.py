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
    extract_entities_with_llm,
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
            {"occasion": "anniversary", "max_price": None},
            {"max_price": 50000, "category": "ring"},
        )
        self.assertEqual(merged["occasion"], "anniversary")
        self.assertEqual(merged["max_price"], 50000)
        self.assertEqual(merged["category"], "ring")


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
            with (
                patch(
                    "kisna_chatbot.processors.classifier._programmatic_intent_override",
                    return_value=None,
                ),
                patch(
                    "kisna_chatbot.processors.classifier.complete_chat",
                    new_callable=AsyncMock,
                    return_value=llm_response,
                ),
            ):
                result = await clf.process(data)
            self.assertEqual(
                result["llm_extracted_entities"]["category"],
                "ring",
            )
            self.assertEqual(result["llm_extracted_entities"]["max_price"], 50000)

        asyncio.run(_run())

    def test_programmatic_returns_empty_entities(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "wapas karna hai"}},
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "rings"}],
                },
                "client_id": "kisna",
            }
            result = await clf.process(data)
            self.assertEqual(result.get("llm_extracted_entities"), {})

        asyncio.run(_run())

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
