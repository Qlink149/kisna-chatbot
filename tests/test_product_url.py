"""Tests for KISNA product URL building."""

import unittest

from kisna_chatbot.utils.product_formatter import build_product_url


class BuildProductUrlTests(unittest.TestCase):
    def test_products_prefix_slug(self):
        product = {"seos": {"slug": "products_elysia-ring"}}
        self.assertEqual(
            build_product_url(product),
            "https://www.kisna.com/products/elysia-ring",
        )

    def test_products_maggio_ring(self):
        product = {"seos": {"slug": "products_maggio-ring"}}
        self.assertEqual(
            build_product_url(product),
            "https://www.kisna.com/products/maggio-ring",
        )

    def test_empty_slug_returns_base(self):
        self.assertEqual(build_product_url({}), "https://www.kisna.com")


if __name__ == "__main__":
    unittest.main()
