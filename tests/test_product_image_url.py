"""Tests for Clara product image URL extraction."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("KISNA_PHONE_NUMBER_ID", "850788844795304")

from kisna_chatbot.main import app  # noqa: F401 — initializes app env before formatter import
from kisna_chatbot.utils.product_formatter import (
    format_price_line,
    format_product_image_caption,
    get_product_display_price,
    get_product_image_url,
    get_product_image_url_for_whatsapp,
    get_product_price_bundle,
    get_whatsapp_safe_image_url,
)

_CLARA_CDN_WEBP = (
    "https://kisna-assets.blr1.cdn.digitaloceanspaces.com/compressed/assets/"
    "1738215770247-87-WG70009-Y1.webp"
)


def _clara_product_full() -> dict:
    return {
        "_id": "prod-clara-1",
        "title": "Sample Ring",
        "mediaUrl": [
            {
                "isDefault": True,
                "image": _CLARA_CDN_WEBP,
                "color": "Yellow",
                "sort": "plp",
                "type": "image",
            }
        ],
    }


class ProductImageUrlTests(unittest.TestCase):
    def test_clara_mediaUrl_image_isDefault(self):
        url = get_product_image_url(_clara_product_full())
        self.assertEqual(url, _CLARA_CDN_WEBP)

    def test_legacy_mediaUrl_url_fallback(self):
        legacy_url = "https://img.example/legacy.jpg"
        product = {
            "mediaUrl": [{"isDefault": True, "url": legacy_url}],
        }
        self.assertEqual(get_product_image_url(product), legacy_url)

    def test_partial_media_optional_sort_color(self):
        product = {
            "title": "Ananya Mangalsutra",
            "mediaUrl": [
                {
                    "isDefault": True,
                    "image": "https://kisna-assets.example/item.webp",
                    "type": "image",
                }
            ],
        }
        self.assertEqual(
            get_product_image_url(product),
            "https://kisna-assets.example/item.webp",
        )

    def test_no_default_uses_first_valid_image(self):
        first = "https://kisna-assets.example/first.webp"
        second = "https://kisna-assets.example/second.webp"
        product = {
            "mediaUrl": [
                {"isDefault": False, "type": "video", "image": "https://example.com/v.mp4"},
                {"isDefault": False, "image": first},
                {"isDefault": True, "image": second},
            ],
        }
        self.assertEqual(get_product_image_url(product), second)

    def test_skips_non_image_type_when_other_entries_exist(self):
        product = {
            "mediaUrl": [
                {"type": "video", "image": "https://example.com/video.mp4"},
                {"image": "https://kisna-assets.example/photo.webp"},
            ],
        }
        self.assertEqual(
            get_product_image_url(product),
            "https://kisna-assets.example/photo.webp",
        )

    def test_top_level_image_fallback(self):
        product = {"image": "https://kisna-assets.example/top.webp"}
        self.assertEqual(
            get_product_image_url(product),
            "https://kisna-assets.example/top.webp",
        )

    def test_empty_media_returns_none(self):
        self.assertIsNone(get_product_image_url({"mediaUrl": []}))
        self.assertIsNone(get_product_image_url({}))

    def test_missing_type_still_returns_image(self):
        product = {
            "mediaUrl": [{"image": "https://kisna-assets.example/no-type.webp"}],
        }
        self.assertEqual(
            get_product_image_url(product),
            "https://kisna-assets.example/no-type.webp",
        )

    def test_plp_sort_preferred_over_other_media(self):
        product = {
            "mediaUrl": [
                {"image": "https://ex.com/other.jpg", "type": "image"},
                {
                    "image": "https://ex.com/plp.jpg",
                    "type": "image",
                    "sort": "plp",
                },
            ]
        }
        self.assertEqual(get_product_image_url(product), "https://ex.com/plp.jpg")

    def test_relative_compressed_path_resolves(self):
        product = {
            "mediaUrl": [
                {"image": "compressed/assets/ring.webp", "type": "image"},
            ]
        }
        url = get_product_image_url(product)
        self.assertIsNotNone(url)
        self.assertTrue(url.startswith("https://"))
        self.assertIn("compressed/assets/ring.webp", url)

    def test_whatsapp_url_returns_raw_webp_from_formatter(self):
        product = {
            "mediaUrl": [
                {
                    "image": "https://kisna-assets.example/item.webp",
                    "type": "image",
                }
            ],
        }
        self.assertEqual(
            get_product_image_url_for_whatsapp(product),
            "https://kisna-assets.example/item.webp",
        )

    def test_whatsapp_safe_image_url_wraps_webp_with_cloudinary(self):
        webp = "https://kisna-assets.example/item.webp"
        with patch.dict(os.environ, {"CLOUDINARY_CLOUD_NAME": "test-cloud"}):
            result = get_whatsapp_safe_image_url(webp)
        self.assertEqual(
            result,
            "https://res.cloudinary.com/test-cloud"
            "/image/fetch/f_jpg,q_85,fl_progressive/"
            f"{webp}",
        )

    def test_whatsapp_safe_image_url_wraps_jpg_with_cloudinary(self):
        jpg = "https://kisna-assets.example/item.jpg"
        with patch.dict(os.environ, {"CLOUDINARY_CLOUD_NAME": "test-cloud"}):
            result = get_whatsapp_safe_image_url(jpg)
        self.assertEqual(
            result,
            "https://res.cloudinary.com/test-cloud"
            "/image/fetch/f_jpg,q_85,fl_progressive/"
            f"{jpg}",
        )

    def test_whatsapp_safe_image_url_empty_returns_none(self):
        self.assertIsNone(get_whatsapp_safe_image_url(""))

    def test_whatsapp_safe_image_url_fallback_without_cloud_name(self):
        webp = "https://kisna-assets.example/item.webp"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLOUDINARY_CLOUD_NAME", None)
            self.assertEqual(get_whatsapp_safe_image_url(webp), webp)

    def test_variant_only_image_fallback(self):
        product = {
            "variant": {
                "mediaUrl": [
                    {"image": "https://ex.com/variant.jpg", "type": "image"},
                ]
            }
        }
        self.assertEqual(
            get_product_image_url(product),
            "https://ex.com/variant.jpg",
        )

    def test_display_price_prefers_final_price(self):
        product = {"price": {"variantPrice": 100000, "finalPrice": 95000}}
        self.assertEqual(get_product_display_price(product), 95000)

    def test_price_bundle_api_mrp_only_when_above_display(self):
        product = {
            "price": {"variantPrice": 50000},
            "variant": {"salePrice": 48000, "mrpPrice": 55000, "title": "Gold 14KT Yellow 7"},
            "materialType": ["diamond"],
            "promotions": [],
        }
        bundle = get_product_price_bundle(product)
        self.assertEqual(bundle["display_price"], 48000)
        self.assertEqual(bundle["mrp_price"], 55000)
        line = format_price_line(product)
        self.assertIn("~₹55,000~", line)

    def test_stale_mrp_no_strikethrough(self):
        product = {
            "price": {"variantPrice": 64892, "dynamicPricing": True},
            "variant": {"salePrice": 64892, "mrpPrice": 64892},
            "materialType": ["diamond"],
            "promotions": [
                {
                    "discOn": "Labour",
                    "fromAmt": 50000,
                    "toAmt": 99999,
                    "disc": 30,
                    "category": "Diamond",
                }
            ],
        }
        bundle = get_product_price_bundle(product)
        self.assertIsNone(bundle["mrp_price"])
        self.assertNotIn("~₹", format_price_line(product))

    def test_product_image_caption_disclaimer_and_shipping(self):
        product = {
            "title": "Gold Ring",
            "price": {"variantPrice": 45000},
            "materialType": "gold",
            "shipping": {"edd": 9},
            "seos": {"slug": "products_gold-ring"},
        }
        caption = format_product_image_caption(product)
        self.assertIn("*Gold Ring*", caption)
        self.assertIn("Price may vary as per current gold rate", caption)
        self.assertIn("For exact price click button below", caption)
        self.assertIn("🚚 Shipping in 9 days", caption)
        self.assertNotIn("Delivery in", caption)
        self.assertNotIn("kisna.com", caption)
        self.assertNotIn("🔗", caption)


if __name__ == "__main__":
    unittest.main()
