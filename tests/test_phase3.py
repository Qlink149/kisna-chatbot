"""Unit tests for Phase 3: offers formatting, store menu keys, cache TTL."""

import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.processors.ad_flow_agent import (
    _build_store_responses,
    _build_store_text,
    _zero_results_message,
)
from kisna_chatbot.processors.offers_agent import (
    _build_offers_text,
    _format_promo_line,
    _is_labour_promo,
)
from kisna_chatbot.processors.service_list import _normalize_menu_key
from kisna_chatbot.utils.clara_cache import (
    PROMOTIONS_TTL_SECONDS,
    STORES_TTL_SECONDS,
    _is_stale,
    get_cached_promotions,
)


class OffersFormatTests(unittest.TestCase):
    def test_promo_line_strips_space_before_percent(self):
        line = _format_promo_line(
            {
                "discountLable": "20 % off on Making Charges",
                "fromAmt": 0,
                "toAmt": 49999,
                "discOn": "Labour",
            }
        )
        self.assertIn("20% off on Making Charges", line)
        self.assertNotIn("20 %", line)

    def test_promo_line_uses_discount_lable(self):
        line = _format_promo_line(
            {
                "discountLable": "10% off on Making Charges",
                "fromAmt": 100000,
                "toAmt": 199999,
                "discOn": "Labour",
                "category": "Gold",
            }
        )
        self.assertIn("Making Charges", line)
        self.assertNotIn("₹", line)
        self.assertNotIn("up to", line)

    def test_build_offers_text_sections(self):
        promos = [
            {
                "discountLable": "10% off on Making Charges",
                "fromAmt": 100000,
                "toAmt": 199999,
                "discOn": "Labour",
                "category": "Gold",
                "active": True,
                "status": "active",
            },
            {
                "discountLable": "15% off on Making Charges",
                "fromAmt": 50000,
                "toAmt": 99999,
                "discOn": "Labour",
                "category": "Diamond",
                "active": True,
                "status": "active",
            },
            {
                "discountLable": "21 % off on Diamond Prices",
                "fromAmt": 0,
                "toAmt": 9999999,
                "discOn": "Diamond",
                "category": "Diamond",
                "active": True,
                "status": "active",
            },
        ]
        text = _build_offers_text(promos)
        self.assertIn("*Current KISNA Offers*", text)
        self.assertIn("*Gold Jewellery*", text)
        self.assertIn("*Diamond Jewellery*", text)
        self.assertIn("21% off on Diamond Prices", text)
        diamond_pos = text.index("*Diamond Jewellery*")
        gold_pos = text.index("*Gold Jewellery*")
        self.assertLess(diamond_pos, gold_pos)
        self.assertIn("_Making charges are", text)

    def test_build_offers_text_is_text_only_no_browse_ctas(self):
        from kisna_chatbot.processors.offers_agent import _build_bot_response

        text = _build_offers_text(
            [
                {
                    "discountLable": "21% off on Making Charges",
                    "fromAmt": 0,
                    "toAmt": 999999,
                    "discOn": "Labour",
                    "category": "Gold",
                    "active": True,
                }
            ]
        )
        resp = _build_bot_response(text)
        self.assertEqual(len(resp), 1)
        self.assertEqual(resp[0]["type"], "text")
        self.assertNotIn("Browse Gold", str(resp))
        self.assertNotIn("Browse Diamond", str(resp))

    def test_promo_line_omits_amount_range(self):
        line = _format_promo_line(
            {
                "discountLable": "20% off on Making Charges",
                "fromAmt": 0,
                "toAmt": 49999,
                "discOn": "Labour",
            }
        )
        self.assertEqual(line, "• 20% off on Making Charges")
        self.assertNotIn("up to", line)

    def test_making_charges_disc_on_is_labour_promo(self):
        self.assertTrue(_is_labour_promo({"discOn": "Making Charges"}))

    def test_promo_line_uses_discount_field(self):
        line = _format_promo_line(
            {
                "discount": 15,
                "fromAmt": 0,
                "toAmt": 99999,
                "discOn": "Making Charges",
            }
        )
        self.assertIn("15% off on Making Charges", line)


class StoreFormatTests(unittest.TestCase):
    def test_build_store_text(self):
        stores = [
            {
                "name": "KISNA Andheri",
                "address": "Mumbai, 400053",
                "phone": "9876543210",
            }
        ]
        text = _build_store_text(stores[0])
        self.assertIn("*KISNA Andheri*", text)
        self.assertIn("📍", text)
        self.assertIn("📞 9876543210", text)

    def test_build_store_responses_with_map_cta(self):
        stores = [
            {
                "name": "Mriza Ismail Rd - Jaipur - Rajasthan",
                "phone": "9587868500",
                "address": {
                    "line1": "Ground Floor, 137, Mirza Ismail Rd",
                    "city": {"_id": "x", "name": "Jaipur"},
                    "state": {"_id": "y", "name": "Rajasthan"},
                    "pincode": "302001",
                    "mapLink": "https://www.google.com/maps/example",
                },
            }
        ]
        responses = _build_store_responses(stores)
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["type"], "cta_url")
        self.assertIn("Jaipur", responses[0]["text"])
        self.assertIn("302001", responses[0]["text"])
        self.assertEqual(responses[0]["display_text"], "View on Map")
        self.assertEqual(responses[0]["url"], "https://www.google.com/maps/example")

    def test_build_store_responses_shows_all_stores(self):
        stores = [
            {"name": f"Store {i}", "address": f"City {i}", "phone": f"900000000{i}"}
            for i in range(8)
        ]
        responses = _build_store_responses(stores)
        self.assertEqual(len(responses), 8)
        self.assertTrue(all(r["type"] == "text" for r in responses))

    def test_zero_results_includes_locator(self):
        os.environ["KISNA_STORE_LOCATOR_URL"] = "https://www.kisna.com/store"
        text = _zero_results_message()
        self.assertIn("No KISNA stores found", text)
        self.assertIn("https://www.kisna.com/store", text)


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
