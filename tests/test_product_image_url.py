"""Tests for Clara product image URL extraction."""

import os
import unittest

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
from kisna_chatbot.utils.product_formatter import get_product_image_url

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


if __name__ == "__main__":
    unittest.main()
