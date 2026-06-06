"""Tests for API-only price resolution from Clara list fields."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.utils.price_calculator import (
    find_matching_labour_promo,
    resolve_product_prices,
)


def _nitara_stale_mrp() -> dict:
    return {
        "title": "Nitara Ring",
        "materialType": ["diamond", "gemstone"],
        "price": {"variantPrice": 64892, "dynamicPricing": True},
        "variant": {
            "title": "Gold 14KT Yellow 7 SI-HI Gemstone",
            "salePrice": 64892,
            "mrpPrice": 64892,
        },
        "promotions": [
            {
                "discount": 30,
                "discOn": "Labour",
                "fromAmt": 50000,
                "toAmt": 99999,
                "category": "Diamond",
            }
        ],
    }


class PriceCalculatorTests(unittest.TestCase):
    def test_stale_mrp_no_strikethrough_only_api_price(self):
        resolved = resolve_product_prices(_nitara_stale_mrp())
        self.assertEqual(resolved["display_price"], 64892)
        self.assertIsNone(resolved["mrp_price"])
        self.assertIn("30% off", resolved["promo_label"] or "")
        self.assertTrue(resolved["has_dynamic_pricing"])

    def test_api_mrp_shown_when_above_display(self):
        product = {
            "materialType": ["diamond"],
            "price": {"variantPrice": 50000},
            "variant": {"salePrice": 48000, "mrpPrice": 55000},
            "promotions": [],
        }
        resolved = resolve_product_prices(product)
        self.assertEqual(resolved["display_price"], 48000)
        self.assertEqual(resolved["mrp_price"], 55000)

    def test_no_promo_no_mrp_single_price(self):
        product = {
            "materialType": ["gold"],
            "price": {"variantPrice": 30496},
            "variant": {"salePrice": 30496, "mrpPrice": 30496},
            "promotions": [],
        }
        resolved = resolve_product_prices(product)
        self.assertEqual(resolved["display_price"], 30496)
        self.assertIsNone(resolved["mrp_price"])
        self.assertIsNone(resolved["promo_label"])

    def test_final_price_from_api_when_present(self):
        product = {
            "materialType": ["diamond"],
            "price": {
                "variantPrice": 64892,
                "finalPrice": 64937,
                "dynamicPricing": True,
            },
            "variant": {"salePrice": 64892, "mrpPrice": 67254},
            "promotions": [],
        }
        resolved = resolve_product_prices(product)
        self.assertEqual(resolved["display_price"], 64937)
        self.assertEqual(resolved["mrp_price"], 67254)

    def test_find_matching_labour_promo_tier(self):
        promo = find_matching_labour_promo(_nitara_stale_mrp(), 64892.0)
        self.assertIsNotNone(promo)
        self.assertEqual(promo.get("discount"), 30)


if __name__ == "__main__":
    unittest.main()
