"""Unit tests for Phase 3: offers formatting, store menu keys, cache TTL."""

import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.processors.ad_flow_agent import _format_stores_message, _zero_results_message
from kisna_chatbot.processors.offers_agent import _build_offers_text, _format_tier_line
from kisna_chatbot.processors.service_list import _normalize_menu_key
from kisna_chatbot.utils.clara_cache import (
    PROMOTIONS_TTL_SECONDS,
    STORES_TTL_SECONDS,
    _is_stale,
    get_cached_promotions,
)


class OffersFormatTests(unittest.TestCase):
    def test_tier_line_includes_making_charges(self):
        line = _format_tier_line({"disc": 10, "toAmt": 50000, "discOn": "Labour"})
        self.assertIn("making charges", line)
        self.assertIn("10%", line)
        self.assertIn("50,000", line)

    def test_build_offers_text_sections(self):
        promos = [
            {
                "disc": 10,
                "toAmt": 100000,
                "discOn": "Labour",
                "materialType": "gold",
            },
            {
                "disc": 15,
                "toAmt": 200000,
                "discOn": "Labour",
                "materialType": "diamond",
            },
        ]
        text = _build_offers_text(promos)
        self.assertIn("*Current KISNA Offers*", text)
        self.assertIn("*Gold Jewellery*", text)
        self.assertIn("*Diamond Jewellery*", text)
        self.assertIn("making charges", text)
        self.assertNotIn("10% off —", text)


class StoreFormatTests(unittest.TestCase):
    def test_format_stores_message(self):
        stores = [
            {
                "name": "KISNA Andheri",
                "address": "Mumbai, 400053",
                "phone": "9876543210",
            }
        ]
        text = _format_stores_message(stores, 1)
        self.assertIn("*KISNA Andheri*", text)
        self.assertIn("📍", text)
        self.assertIn("📞 9876543210", text)

    def test_zero_results_includes_locator(self):
        os.environ["KISNA_STORE_LOCATOR_URL"] = "https://kisna.com/stores"
        text = _zero_results_message()
        self.assertIn("No KISNA stores found", text)
        self.assertIn("https://kisna.com/stores", text)


class MenuKeyTests(unittest.TestCase):
    def test_locate_store_alias_maps_to_find_store(self):
        self.assertEqual(_normalize_menu_key("", "locate_store"), "find_store")

    def test_store_info_postback(self):
        self.assertEqual(_normalize_menu_key("", "store_info"), "store_info")


class CacheTests(unittest.TestCase):
    def test_is_stale(self):
        self.assertTrue(_is_stale(None, PROMOTIONS_TTL_SECONDS))
        old = time.time() - PROMOTIONS_TTL_SECONDS - 1
        self.assertTrue(_is_stale(old, PROMOTIONS_TTL_SECONDS))
        recent = time.time() - 60
        self.assertFalse(_is_stale(recent, PROMOTIONS_TTL_SECONDS))

    def test_stores_ttl_24h(self):
        self.assertEqual(STORES_TTL_SECONDS, 24 * 3600)

    def test_get_cached_promotions_no_app_state(self):
        async def _run():
            with patch(
                "kisna_chatbot.utils.clara_cache.get_promotions",
                new_callable=AsyncMock,
                return_value=[{"disc": 5}],
            ) as mock_get:
                result = await get_cached_promotions(None)
            self.assertEqual(len(result), 1)
            mock_get.assert_awaited_once()

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
