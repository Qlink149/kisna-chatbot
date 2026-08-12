"""Material switch: 'I want in gold' must replace diamond and keep sticky filters."""

import os
import unittest

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GROQ_API_KEY": "test",
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

from kisna_chatbot.processors.entity_extractor import merge_search_entities  # noqa: E402
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    advance_wizard,
    start_wizard,
)


class MaterialOnlyMergeTests(unittest.TestCase):
    def test_want_in_gold_keeps_category_gender_budget(self):
        prior = {
            "category": "ring",
            "material_type": "diamond",
            "gender": "women",
            "min_price": 15000,
            "max_price": 30000,
            "fulfillment": None,
        }
        new = {
            "category": None,
            "material_type": "gold",
            "gender": None,
            "min_price": None,
            "max_price": None,
            "title": None,
            "fulfillment": None,
        }
        merged = merge_search_entities(prior, new, "I want in gold")
        self.assertEqual(merged["material_type"], "gold")
        self.assertEqual(merged["category"], "ring")
        self.assertEqual(merged["gender"], "women")
        self.assertEqual(merged["min_price"], 15000)
        self.assertEqual(merged["max_price"], 30000)

    def test_category_change_still_drops_old_material(self):
        prior = {
            "category": "ring",
            "material_type": "diamond",
            "gender": "women",
            "max_price": 30000,
        }
        new = {
            "category": "necklace",
            "material_type": None,
            "gender": None,
            "min_price": None,
            "max_price": None,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "show me necklaces")
        self.assertEqual(merged["category"], "necklace")
        self.assertIsNone(merged["material_type"])
        self.assertIsNone(merged["max_price"])


class WizardMaterialRestateTests(unittest.TestCase):
    def test_want_in_gold_overwrites_diamond_at_fulfillment(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "min_price": 15000,
                "max_price": 30000,
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        self.assertEqual(
            profile["shopping_wizard_data"]["material_type"], "diamond"
        )

        status, _ = advance_wizard(profile, {}, text="I want in gold")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["material_type"], "gold")
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        self.assertEqual(profile["shopping_wizard_data"]["category"], "ring")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "women")

    def test_in_gold_same_funnel_still_sets_material(self):
        profile = {}
        start_wizard(
            profile,
            entities={"category": "ring", "gender": "women"},
        )
        self.assertEqual(profile["shopping_wizard_step"], "material")
        status, _ = advance_wizard(profile, {}, text="in gold")
        self.assertIn(status, ("prompt", "complete"))
        self.assertEqual(profile["shopping_wizard_data"]["material_type"], "gold")


if __name__ == "__main__":
    unittest.main()
