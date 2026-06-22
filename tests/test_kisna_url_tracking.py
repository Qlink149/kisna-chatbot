"""Tests for KISNA outbound URL UTM tagging."""

import os
import unittest

from kisna_chatbot.utils.kisna_url_tracking import (
    append_kisna_utm,
    is_kisna_website_url,
    kisna_home_url,
)
from kisna_chatbot.utils.product_formatter import build_catalogue_url, build_product_url


class KisnaUrlTrackingTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = {
            key: os.environ.get(key)
            for key in (
                "KISNA_UTM_ENABLED",
                "KISNA_UTM_SOURCE",
                "KISNA_UTM_MEDIUM",
            )
        }
        os.environ["KISNA_UTM_ENABLED"] = "true"
        os.environ["KISNA_UTM_SOURCE"] = "whatsapp"
        os.environ["KISNA_UTM_MEDIUM"] = "kia_bot"

    def tearDown(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_is_kisna_website_url(self):
        self.assertTrue(is_kisna_website_url("https://www.kisna.com/products/ring"))
        self.assertTrue(is_kisna_website_url("https://kisna.com/store"))
        self.assertFalse(is_kisna_website_url("https://google.com/maps"))

    def test_append_kisna_utm_adds_source_and_medium_only(self):
        url = append_kisna_utm("https://www.kisna.com/products/gold-ring")
        self.assertIn("utm_source=whatsapp", url)
        self.assertIn("utm_medium=kia_bot", url)
        self.assertNotIn("utm_campaign", url)
        self.assertNotIn("utm_content", url)

    def test_append_kisna_utm_skips_non_kisna_urls(self):
        url = append_kisna_utm("https://maps.google.com/?q=store")
        self.assertEqual(url, "https://maps.google.com/?q=store")

    def test_append_kisna_utm_does_not_overwrite_existing(self):
        url = append_kisna_utm(
            "https://www.kisna.com/store?utm_source=newsletter",
        )
        self.assertIn("utm_source=newsletter", url)
        self.assertNotIn("utm_source=whatsapp", url)
        self.assertIn("utm_medium=kia_bot", url)

    def test_build_product_url_includes_utms_when_enabled(self):
        product = {"seos": {"slug": "products_elysia-ring"}}
        url = build_product_url(product)
        self.assertIn("https://www.kisna.com/products/elysia-ring", url)
        self.assertIn("utm_source=whatsapp", url)
        self.assertIn("utm_medium=kia_bot", url)

    def test_build_catalogue_url_includes_utms_when_enabled(self):
        url = build_catalogue_url({"category": "ring", "material_type": "gold"})
        self.assertIn("https://www.kisna.com/jewellery/rings+gold", url)
        self.assertIn("utm_source=whatsapp", url)
        self.assertIn("utm_medium=kia_bot", url)

    def test_kisna_home_url(self):
        url = kisna_home_url()
        self.assertTrue(url.startswith("https://www.kisna.com"))
        self.assertIn("utm_source=whatsapp", url)
        self.assertIn("utm_medium=kia_bot", url)


if __name__ == "__main__":
    unittest.main()
