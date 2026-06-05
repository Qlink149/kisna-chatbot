"""Unit tests for jewellery_profile mapping and merge helpers."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.utils.jewellery_profile import (
    entities_to_jewellery_profile,
    extract_occasion,
    format_budget_range,
    merge_jewellery_profile,
)


class FormatBudgetRangeTests(unittest.TestCase):
    def test_range(self):
        self.assertEqual(format_budget_range(20000, 50000), "₹20,000 – ₹50,000")

    def test_max_only(self):
        self.assertEqual(format_budget_range(None, 50000), "under ₹50,000")

    def test_min_only(self):
        self.assertEqual(format_budget_range(20000, None), "above ₹20,000")

    def test_none(self):
        self.assertIsNone(format_budget_range(None, None))


class ExtractOccasionTests(unittest.TestCase):
    def test_wedding_hinglish(self):
        self.assertEqual(extract_occasion("shaadi ke liye gold ring"), "wedding")

    def test_daily_wear(self):
        self.assertEqual(extract_occasion("office wear earrings"), "daily wear")

    def test_no_match(self):
        self.assertIsNone(extract_occasion("gold ring under 50k"))


class EntitiesToJewelleryProfileTests(unittest.TestCase):
    def test_full_mapping(self):
        entities = {
            "category": "ring",
            "material_type": "gold",
            "min_price": None,
            "max_price": 50000,
            "title": None,
            "city": None,
            "pincode": None,
        }
        profile = entities_to_jewellery_profile(
            entities,
            source_text="gold rings under 50k for wedding",
        )
        self.assertEqual(profile["material_preference"], "gold")
        self.assertEqual(profile["category_preference"], "ring")
        self.assertEqual(profile["budget_range"], "under ₹50,000")
        self.assertEqual(profile["occasion"], "wedding")

    def test_material_button_skips_occasion(self):
        entities = {"material_type": "gold", "category": None, "min_price": None, "max_price": None}
        profile = entities_to_jewellery_profile(entities, source_text="gold")
        self.assertEqual(profile, {"material_preference": "gold"})

    def test_similar_search_skips_occasion(self):
        entities = {
            "category": "ring",
            "material_type": "gold",
            "min_price": None,
            "max_price": None,
        }
        profile = entities_to_jewellery_profile(
            entities,
            source_text="similar:Gold Ring",
        )
        self.assertNotIn("occasion", profile)
        self.assertEqual(profile["material_preference"], "gold")
        self.assertEqual(profile["category_preference"], "ring")


class MergeJewelleryProfileTests(unittest.TestCase):
    def test_partial_update_preserves_existing(self):
        existing = {
            "material_preference": "gold",
            "occasion": "wedding",
        }
        updates = {"category_preference": "ring", "budget_range": "under ₹50,000"}
        merged = merge_jewellery_profile(existing, updates)
        self.assertEqual(merged["material_preference"], "gold")
        self.assertEqual(merged["occasion"], "wedding")
        self.assertEqual(merged["category_preference"], "ring")
        self.assertEqual(merged["budget_range"], "under ₹50,000")

    def test_overwrites_when_new_value_present(self):
        existing = {"material_preference": "gold", "occasion": "wedding"}
        updates = {"material_preference": "diamond"}
        merged = merge_jewellery_profile(existing, updates)
        self.assertEqual(merged["material_preference"], "diamond")
        self.assertEqual(merged["occasion"], "wedding")


if __name__ == "__main__":
    unittest.main()
