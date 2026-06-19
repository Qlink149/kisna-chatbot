"""Clara API client contract tests against Postman spec and json/api fixtures."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

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
os.environ.setdefault("GUPSHUP_WEBHOOK_SECRET", "test-webhook-secret")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")

from kisna_chatbot.integrations.clara_api import (  # noqa: E402
    build_products_query_params,
    get_stores,
    parse_products_response,
    search_products,
)

_FIXTURES = Path(__file__).resolve().parent.parent / "json" / "api" / "v1" / "clara"


class BuildProductsQueryParamsTests(unittest.TestCase):
    def test_chain_gold_omits_empty_fields(self):
        params = build_products_query_params(
            category="chain",
            material_type="gold",
            page_no=1,
            page_size=10,
        )
        self.assertEqual(params["category"], "chain")
        self.assertEqual(params["materialType"], "gold")
        self.assertEqual(params["searchUrl"], "true")
        self.assertNotIn("minPrice", params)
        self.assertNotIn("maxPrice", params)
        self.assertNotIn("title", params)

    def test_empty_strings_omitted(self):
        params = build_products_query_params(
            category="",
            title="  ",
            material_type="gold",
        )
        self.assertNotIn("category", params)
        self.assertNotIn("title", params)
        self.assertIn("materialType", params)


class ParseProductsResponseTests(unittest.TestCase):
    def test_parses_products_fixture(self):
        path = _FIXTURES / "products.json"
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
        result = parse_products_response(body, page_no=1)
        self.assertGreaterEqual(len(result["products"]), 10)
        self.assertGreater(result["total_count"], 0)
        self.assertEqual(result["page"], 1)
        first = result["products"][0]
        self.assertIn("title", first)
        self.assertIn("productType", first)


class SearchProductsRoundTripTests(unittest.TestCase):
    def test_search_products_uses_builder_and_parser(self):
        async def _run():
            fixture_path = _FIXTURES / "products.json"
            with open(fixture_path, encoding="utf-8") as f:
                body = json.load(f)

            with patch(
                "kisna_chatbot.integrations.clara_api._request",
                new_callable=AsyncMock,
                return_value=body,
            ) as request_mock:
                result = await search_products(
                    category="ring",
                    material_type="gold",
                    page_no=1,
                    page_size=5,
                )

            request_mock.assert_awaited_once()
            params = request_mock.await_args.kwargs.get("params") or request_mock.await_args[1].get("params")
            self.assertEqual(params["category"], "ring")
            self.assertEqual(params["materialType"], "gold")
            self.assertGreater(len(result["products"]), 0)

        import asyncio

        asyncio.run(_run())


class GetStoresQueryParamsTests(unittest.TestCase):
    def _run_get_stores(self, **kwargs):
        async def _run():
            fixture_path = _FIXTURES / "stores.json"
            with open(fixture_path, encoding="utf-8") as f:
                body = json.load(f)

            with patch(
                "kisna_chatbot.integrations.clara_api._request",
                new_callable=AsyncMock,
                return_value=body,
            ) as request_mock:
                result = await get_stores(**kwargs)

            request_mock.assert_awaited_once()
            call_kwargs = request_mock.await_args.kwargs
            params = call_kwargs.get("params") or request_mock.await_args[1].get("params")
            return params, result

        import asyncio

        return asyncio.run(_run())

    def test_city_filter_only(self):
        params, result = self._run_get_stores(city="Delhi")
        self.assertEqual(params, {"name": "Delhi"})
        self.assertNotIn("pageNo", params)
        self.assertNotIn("pageSize", params)
        self.assertGreater(len(result["stores"]), 0)

    def test_pincode_filter_only(self):
        params, _result = self._run_get_stores(pincode="110001")
        self.assertEqual(params, {"pincode": "110001"})
        self.assertNotIn("pageNo", params)
        self.assertNotIn("pageSize", params)

    def test_no_filter_no_pagination(self):
        params, _result = self._run_get_stores()
        self.assertEqual(params, {})

    def test_explicit_pagination_when_passed(self):
        params, _result = self._run_get_stores(city="Delhi", page_no=1, page_size=10)
        self.assertEqual(params, {"pageNo": 1, "pageSize": 10, "name": "Delhi"})


if __name__ == "__main__":
    unittest.main()
