"""±10% single-price band tests."""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from kisna_chatbot.processors.entity_extractor import extract_entities
from kisna_chatbot.processors.product_search_agent_v3 import (
    _parse_custom_budget_text,
    _snap_single_price_to_band,
)


class TestPriceBand(unittest.TestCase):
    def test_snap_50000(self):
        self.assertEqual(_snap_single_price_to_band(50000), (45000, 55000))

    def test_snap_25000(self):
        self.assertEqual(_snap_single_price_to_band(25000), (22500, 27500))

    def test_custom_budget_bare_digits(self):
        self.assertEqual(_parse_custom_budget_text("25000"), (22500, 27500))
        self.assertEqual(_parse_custom_budget_text("50000"), (45000, 55000))

    def test_under_unchanged(self):
        self.assertEqual(_parse_custom_budget_text("under 50000"), (0, 50000))
        ents = extract_entities("under 50000")
        self.assertIsNone(ents.get("min_price"))
        self.assertEqual(ents.get("max_price"), 50000)

    def test_above_unchanged(self):
        ents = extract_entities("above 50000")
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertIsNone(ents.get("max_price"))

    def test_range_unchanged(self):
        self.assertEqual(_parse_custom_budget_text("40000-60000"), (40000, 60000))

    def test_tak_unchanged(self):
        ents = extract_entities("50k tak")
        self.assertIsNone(ents.get("min_price"))
        self.assertEqual(ents.get("max_price"), 50000)

    def test_budget_without_direction_is_band(self):
        ents = extract_entities("budget 50000 hai")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)

    def test_50k_ka_ring_is_band(self):
        ents = extract_entities("50k ka ring")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)
        self.assertEqual(ents.get("category"), "ring")


if __name__ == "__main__":
    unittest.main()
