"""Tests for internal → Clara category string normalization."""

import asyncio
import os
import unittest

import pytest
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
    def _assert_clara_category(self, params: dict, clara_slug: str) -> None:
        """Warm filters → categoryId; cold → slug. Either is correct."""
        if params.get("category_id"):
            self.assertNotIn("category", params)
            from kisna_chatbot.integrations.clara_filters import get_category_id

            expected_id = get_category_id(clara_slug)
            if expected_id:
                self.assertEqual(params["category_id"], expected_id)
        else:
            self.assertEqual(params.get("category"), clara_slug)

    def test_map_entries_with_clara_strings(self):
        for internal, clara in CATEGORY_NORMALIZATION_MAP.items():
            if clara is None:
                continue
            params = entities_to_api_params({"category": internal})
            self._assert_clara_category(params, clara)

    def test_maang_tikka_maps_to_space_form(self):
        params = entities_to_api_params({"category": "maang_tikka"})
        self._assert_clara_category(params, "maang tikka")

    def test_maang_tikka_diamond_above_50k_not_blocked(self):
        entities = finalize_search_entities(
            extract_entities("Show me Maang Tikka above 50k in diamond")
        )
        params = entities_to_api_params(entities)
        self._assert_clara_category(params, "maang tikka")
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

    @pytest.mark.no_search_recap
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

class CategorySlugRoundTripTests(unittest.TestCase):
    """Guard the outbound slug against the inbound client-side matcher.

    The bot sends Clara a category slug from CATEGORY_NORMALIZATION_MAP, then
    re-checks every returned product client-side by normalising Clara's own
    ``productType.category.name`` back through _CATEGORY_SYNONYMS. If a slug
    does not normalise back to the category that produced it, every product is
    silently dropped and the search returns "0 matched".

    That is exactly how nosewear broke: it was sent as "nose wear" while its
    synonym list only listed "nose pin"/"nath"/etc, so "Nose Wear" normalised
    to None and no nose pin could ever be matched.
    """

    def test_every_searchable_category_slug_round_trips(self):
        from kisna_chatbot.processors.entity_extractor import (
            _CATEGORY_SYNONYMS,
            _categories_match,
            normalize_category_for_api,
        )

        failures = []
        for category in _CATEGORY_SYNONYMS:
            slug = CATEGORY_NORMALIZATION_MAP.get(category)
            if not slug:
                continue  # not searchable on Clara (e.g. anklet)
            back = normalize_category_for_api(slug)
            if not _categories_match(category, back):
                failures.append(f"{category!r} sent as {slug!r} normalises back to {back!r}")

        self.assertEqual(
            [], failures,
            "Clara category slug does not survive the client-side matcher, so "
            "every returned product would be dropped:\n  " + "\n  ".join(failures),
        )

    def test_clara_category_name_matches_nosewear(self):
        """Regression: Clara returns "Nose Wear"; it must match a nosewear search."""
        from kisna_chatbot.processors.entity_extractor import (
            _categories_match,
            extract_category_from_product,
            filter_products_by_entities,
        )

        product = {
            "title": "Driti Diamond Nose Screw",
            "productType": {"category": {"name": "Nose Wear"}},
        }
        self.assertEqual("nosewear", extract_category_from_product(product))
        self.assertTrue(_categories_match("nosewear", extract_category_from_product(product)))

        # The end-to-end symptom: the client filter must not drop it.
        kept = filter_products_by_entities([product], {"category": "nosewear"})
        self.assertEqual(1, len(kept), "nosewear product was dropped by the client filter")
