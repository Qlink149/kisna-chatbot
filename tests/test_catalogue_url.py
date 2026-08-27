"""Tests for KISNA catalogue deep-link URL builder."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("KISNA_UTM_ENABLED", "false")

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
        # Live-confirmed real URL bug fix: the site expects "-collection"
        # APPENDED (e.g. "Sparkle" -> sparkle-collection), not stripped.
        url = build_catalogue_url(
            {"category": "bracelet", "collection": "Evil Eye"}
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/bracelets+evil-eye-collection",
        )

    def test_collection_already_carrying_the_word_is_not_doubled(self):
        url = build_catalogue_url(
            {"category": "bracelet", "collection": "Evil Eye Collection"}
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/bracelets+evil-eye-collection",
        )

    def test_gender_men_uses_the_asymmetric_mens_token(self):
        # Live-confirmed against the real site: "mens" (with trailing s).
        url = build_catalogue_url({"category": "earring", "gender": "men"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/earrings+mens")

    def test_gender_women_uses_the_bare_women_token(self):
        # Live-confirmed against the real site: "women" (no trailing s) --
        # asymmetric with "mens", not a typo.
        url = build_catalogue_url({"category": "earring", "gender": "women"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/earrings+women")

    def test_gender_kids(self):
        url = build_catalogue_url({"category": "ring", "gender": "kids"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/rings+kids")

    def test_no_gender_produces_no_gender_segment(self):
        url = build_catalogue_url({"category": "ring", "material_type": "gold"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/rings+gold")

    def test_live_reported_case_mens_earrings_price_band(self):
        # Reproduces the exact live case that surfaced this bug
        # (+917977104875): "men's earrings 10k-20k" -- the CTA URL had no
        # gender at all before this fix.
        url = build_catalogue_url(
            {
                "category": "earring",
                "gender": "men",
                "min_price": 10000,
                "max_price": 20000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/earrings+mens+10k-to-20k",
        )

    def test_fulfillment_ready_to_ship(self):
        url = build_catalogue_url({"category": "ring", "fulfillment": "ready"})
        self.assertEqual(
            url, "https://www.kisna.com/jewellery/rings+ready-to-ship"
        )

    def test_fulfillment_made_to_order(self):
        url = build_catalogue_url({"category": "ring", "fulfillment": "mto"})
        self.assertEqual(
            url, "https://www.kisna.com/jewellery/rings+made-to-order"
        )

    def test_no_fulfillment_produces_no_fulfillment_segment(self):
        url = build_catalogue_url({"category": "ring"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/rings")

    def test_full_confirmed_real_world_combo(self):
        # Every segment from the client's live-confirmed real example URL
        # except the earring-style facet (Jhumkas/Hoops & Huggies/...),
        # deliberately out of scope for this round.
        url = build_catalogue_url(
            {
                "category": "earring",
                "gender": "men",
                "collection": "Sparkle",
                "material_type": "diamond",
                "min_price": 30000,
                "max_price": 40000,
                "fulfillment": "ready",
                "karat": "14KT",
                "metal_colour": "white",
            }
        )
        for token in (
            "earrings", "mens", "sparkle-collection", "diamond",
            "30k-to-40k", "ready-to-ship", "14kt", "white",
        ):
            self.assertIn(token, url, url)


if __name__ == "__main__":
    unittest.main()
