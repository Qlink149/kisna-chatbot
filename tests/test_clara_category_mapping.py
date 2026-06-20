"""Tests for internal → Clara category string normalization."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    CATEGORY_NORMALIZATION_MAP,
    entities_to_api_params,
    extract_entities,
    finalize_search_entities,
    has_clara_search_scope,
    normalize_entities_for_clara,
)


class ClaraCategoryMappingTests(unittest.TestCase):
    def test_map_entries_with_clara_strings(self):
        for internal, clara in CATEGORY_NORMALIZATION_MAP.items():
            if clara is None:
                continue
            params = entities_to_api_params({"category": internal})
            self.assertEqual(
                params.get("category"),
                clara,
                msg=f"{internal!r} should map to {clara!r}",
            )

    def test_maang_tikka_maps_to_space_form(self):
        params = entities_to_api_params({"category": "maang_tikka"})
        self.assertEqual(params["category"], "maang tikka")

    def test_maang_tikka_diamond_above_50k_not_blocked(self):
        entities = finalize_search_entities(
            extract_entities("Show me Maang Tikka above 50k in diamond")
        )
        params = entities_to_api_params(entities)
        self.assertEqual(params.get("category"), "maang tikka")
        self.assertEqual(params.get("material_type"), "diamond")
        self.assertEqual(params.get("min_price"), 50000)
        self.assertTrue(has_clara_search_scope(params, entities))

    def test_bangle_bracelet_sets_multi_categories(self):
        normalized = normalize_entities_for_clara(
            {"category": "bangle_bracelet", "multi_category": True}
        )
        self.assertEqual(
            normalized.get("clara_multi_categories"), ["bangle", "bracelet"]
        )
        params = entities_to_api_params({"category": "bangle_bracelet"})
        self.assertNotIn("category", params)
        self.assertTrue(
            has_clara_search_scope(params, {"category": "bangle_bracelet"})
        )

    def test_bangle_bracelet_makes_two_clara_calls(self):
        async def _run():
            agent = ProductSearchAgentV3()
            product_bangle = {
                "_id": "p1",
                "title": "Gold Bangle",
                "price": {"variantPrice": 30000},
                "materialType": "gold",
                "productType": {"category": {"name": "Bangles"}},
                "shipping": {"edd": 5},
                "mediaUrl": [{"image": "https://ex.com/b.jpg", "type": "image"}],
            }
            product_bracelet = {
                "_id": "p2",
                "title": "Gold Bracelet",
                "price": {"variantPrice": 28000},
                "materialType": "gold",
                "productType": {"category": {"name": "Bracelets"}},
                "shipping": {"edd": 5},
                "mediaUrl": [{"image": "https://ex.com/br.jpg", "type": "image"}],
            }
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "browse"}},
                "user_profile": {"service_selected": "product_search"},
                "client_config": type("C", (), {"client_id": "kisna"})(),
            }
            entities = {
                "category": "bangle_bracelet",
                "material_type": "gold",
                "min_price": None,
                "max_price": 50000,
                "title": None,
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                search_mock.side_effect = [
                    {
                        "products": [product_bangle],
                        "total_count": 1,
                        "page": 1,
                    },
                    {
                        "products": [product_bracelet],
                        "total_count": 1,
                        "page": 1,
                    },
                ]
                await agent._execute_search(
                    data,
                    "919999999999",
                    entities,
                    query_label="pref:gold:bangle_bracelet",
                )
            self.assertEqual(search_mock.await_count, 2)
            categories = {
                call.kwargs.get("category") for call in search_mock.await_args_list
            }
            self.assertEqual(categories, {"bangle", "bracelet"})
            self.assertTrue(data.get("bot_response"))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
