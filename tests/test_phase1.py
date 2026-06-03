"""Unit tests for Phase 1: entity extractor and Clara discount helper."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.integrations.clara_api import get_discount_for_product
from kisna_chatbot.processors.entity_extractor import (
    build_search_context,
    entities_to_api_params,
    extract_entities,
)


class EntityExtractorTests(unittest.TestCase):
    def test_category_ring_hinglish(self):
        entities = extract_entities("diamond ring dikhao")
        self.assertEqual(entities["category"], "ring")
        self.assertEqual(entities["material_type"], "diamond")

    def test_price_range(self):
        entities = extract_entities("gold necklace 20k to 50k")
        self.assertEqual(entities["category"], "necklace")
        self.assertEqual(entities["material_type"], "gold")
        self.assertEqual(entities["min_price"], 20000)
        self.assertEqual(entities["max_price"], 50000)

    def test_max_price_under(self):
        entities = extract_entities("earrings under 30k")
        self.assertEqual(entities["category"], "earring")
        self.assertIsNone(entities["min_price"])
        self.assertEqual(entities["max_price"], 30000)

    def test_collection_title(self):
        entities = extract_entities("show rivaah collection")
        self.assertEqual(entities["title"], "rivaah")

    def test_pincode(self):
        entities = extract_entities("store in 400001")
        self.assertEqual(entities["pincode"], "400001")

    def test_entities_to_api_params(self):
        entities = {
            "category": "ring",
            "material_type": "gold",
            "min_price": None,
            "max_price": 50000.0,
            "title": None,
            "city": "Mumbai",
            "pincode": "400001",
        }
        params = entities_to_api_params(entities)
        self.assertEqual(params["category"], "ring")
        self.assertEqual(params["max_price"], 50000.0)
        self.assertNotIn("city", params)
        self.assertNotIn("pincode", params)

    def test_build_search_context(self):
        entities = extract_entities("gold rings under 50k")
        ctx = build_search_context(entities)
        self.assertIn("gold", ctx.lower())
        self.assertIn("50", ctx)


class DiscountHelperTests(unittest.TestCase):
    def test_labour_discount_in_range(self):
        product = {
            "price": {"variantPrice": 75000},
            "promotions": [
                {
                    "discOn": "Labour",
                    "fromAmt": 50000,
                    "toAmt": 100000,
                    "disc": 10,
                }
            ],
        }
        self.assertEqual(get_discount_for_product(product), "10% off making charges")

    def test_non_labour_ignored(self):
        product = {
            "price": {"variantPrice": 75000},
            "promotions": [{"discOn": "Gold", "fromAmt": 0, "toAmt": 999999, "disc": 20}],
        }
        self.assertIsNone(get_discount_for_product(product))

    def test_out_of_range(self):
        product = {
            "price": {"variantPrice": 10000},
            "promotions": [
                {"discOn": "Labour", "fromAmt": 50000, "toAmt": 100000, "disc": 10}
            ],
        }
        self.assertIsNone(get_discount_for_product(product))


if __name__ == "__main__":
    unittest.main()
