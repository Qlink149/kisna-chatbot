"""Tests grounded in real Clara API JSON fixtures."""

import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.integrations.clara_api import get_discount_for_product
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import Classifier
from kisna_chatbot.processors.entity_extractor import (
    entities_to_api_params,
    extract_category_from_product,
    merge_search_entities,
)
from kisna_chatbot.processors.product_search_agent_v3 import _build_fallback_strategies
from kisna_chatbot.utils.product_formatter import (
    format_price_line,
    get_product_price_bundle,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "json" / "api" / "v1" / "clara"


def _load_products() -> list[dict]:
    path = _FIXTURES / "products.json"
    with open(path, encoding="utf-8") as f:
        body = json.load(f)
    return body["data"]["data"]


def _nitara_ring() -> dict:
    for product in _load_products():
        if product.get("title") == "Nitara Ring":
            return product
    raise AssertionError("Nitara Ring not found in fixture")


class ClaraFixtureTests(unittest.TestCase):
    def test_nitara_category_from_product_type(self):
        product = _nitara_ring()
        self.assertEqual(extract_category_from_product(product), "ring")

    def test_nitara_price_bundle_api_only_no_estimated_mrp(self):
        product = _nitara_ring()
        bundle = get_product_price_bundle(product)
        self.assertEqual(bundle["display_price"], 64892)
        self.assertIsNone(bundle["mrp_price"])
        self.assertEqual(bundle["sku"], "KFLR10009G")
        self.assertIn("30% off", bundle["promo_label"] or "")

    def test_nitara_price_line_single_api_price(self):
        line = format_price_line(_nitara_ring())
        self.assertIn("64,892", line)
        self.assertNotIn("~₹", line)

    def test_merge_search_entities_keeps_category_on_budget_refinement(self):
        prior = {"category": "earring", "material_type": None, "max_price": None}
        new = {
            "category": None,
            "material_type": None,
            "min_price": None,
            "max_price": 10000.0,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "I want them under 10,000")
        self.assertEqual(merged["category"], "earring")
        self.assertEqual(merged["max_price"], 10000.0)

    def test_entities_to_api_params_from_merged(self):
        prior = {"category": "earring"}
        new = {"max_price": 10000.0}
        merged = merge_search_entities(prior, new, "under 10,000")
        params = entities_to_api_params(merged)
        self.assertEqual(params["category"], "earring")
        self.assertEqual(params["max_price"], 10000.0)

    def test_drop_material_retains_max_price(self):
        entities = {
            "category": "ring",
            "material_type": "diamond",
            "max_price": 50000,
        }
        strategies = _build_fallback_strategies(entities)
        drop_material = next(s for s in strategies if s[2] == "drop_material")
        self.assertIsNone(drop_material[0]["material_type"])
        self.assertEqual(drop_material[0]["max_price"], 50000)

    def test_classifier_skips_offers_followup(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "go ahead"}},
            "user_profile": {
                "service_selected": SL.OFFERS.value,
                "chat_history": [{"role": "user", "content": "offers"}],
            },
        }
        self.assertFalse(clf.should_run(data))

    def test_promotions_fixture_loads(self):
        path = _FIXTURES / "promotions.json"
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
        promos = body.get("data")
        self.assertIsInstance(promos, list)
        self.assertTrue(len(promos) > 0)

    def test_stores_fixture_loads(self):
        path = _FIXTURES / "stores.json"
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
        stores = body["data"]["data"]
        self.assertTrue(len(stores) > 0)


if __name__ == "__main__":
    unittest.main()
