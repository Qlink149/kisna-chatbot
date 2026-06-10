"""Tests for KISNA catalogue deep-link URL builder."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")

from kisna_chatbot.utils.product_formatter import build_catalogue_url


class CatalogueUrlTests(unittest.TestCase):
    def test_diamond_ring_budget_band(self):
        url = build_catalogue_url(
            {
                "category": "ring",
                "material_type": "diamond",
                "min_price": 30000,
                "max_price": 40000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/rings+30k-to-40k+diamond",
        )

    def test_gold_earrings_material_only(self):
        url = build_catalogue_url(
            {"category": "earring", "material_type": "gold"}
        )
        self.assertEqual(url, "https://www.kisna.com/jewellery/earrings+gold")

    def test_empty_entities_base_url(self):
        self.assertEqual(
            build_catalogue_url({}),
            "https://www.kisna.com/jewellery",
        )

    def test_rose_gold_ring_under_50k(self):
        url = build_catalogue_url(
            {
                "category": "ring",
                "material_type": "gold",
                "karat": "18KT",
                "metal_colour": "rose",
                "max_price": 50000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/rings+40k-to-50k+gold+18kt+rose",
        )

    def test_diamond_rings_under_30k(self):
        url = build_catalogue_url(
            {
                "category": "ring",
                "material_type": "diamond",
                "max_price": 30000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/rings+20k-to-30k+diamond",
        )

    def test_evil_eye_bracelet_collection(self):
        url = build_catalogue_url(
            {"category": "bracelet", "collection": "Evil Eye"}
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/bracelets+evil-eye",
        )


if __name__ == "__main__":
    unittest.main()
