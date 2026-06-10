"""Tests for variant.title parsing and client-side extra filters."""

import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.processors.entity_extractor import (
    entities_to_api_params,
    filter_products_by_extracted_extras,
    has_client_side_filters,
    resolve_api_page_size,
)
from kisna_chatbot.integrations.clara_api import (
    CLIENT_SIDE_FILTER_PAGE_SIZE,
    DEFAULT_API_PAGE_SIZE,
)
from kisna_chatbot.utils.product_formatter import parse_variant_details

_FIXTURES = Path(__file__).resolve().parent.parent / "json" / "api" / "v1" / "clara"


def _load_products() -> list[dict]:
    path = _FIXTURES / "products.json"
    with open(path, encoding="utf-8") as f:
        body = json.load(f)
    return body["data"]["data"]


def _peace_hamsa_bracelet() -> dict:
    for product in _load_products():
        if "Peace Hamsa" in (product.get("title") or ""):
            return product
    raise AssertionError("Peace Hamsa bracelet not found in fixture")


def _nitara_ring() -> dict:
    for product in _load_products():
        if product.get("title") == "Nitara Ring":
            return product
    raise AssertionError("Nitara Ring not found in fixture")


class ParseVariantDetailsTests(unittest.TestCase):
    def test_gold_14kt_yellow_7(self):
        parsed = parse_variant_details({"variant": {"title": "Gold 14KT Yellow 7"}})
        self.assertEqual(parsed["karat"], "14KT")
        self.assertEqual(parsed["metal_colour"], "yellow")
        self.assertEqual(parsed["size"], 7)

    def test_gold_14kt_rose_8(self):
        parsed = parse_variant_details({"variant": {"title": "Gold 14KT Rose 8"}})
        self.assertEqual(parsed["karat"], "14KT")
        self.assertEqual(parsed["metal_colour"], "rose")
        self.assertEqual(parsed["size"], 8)

    def test_fixture_peace_hamsa_variant(self):
        product = _peace_hamsa_bracelet()
        parsed = parse_variant_details(product)
        self.assertEqual(parsed["karat"], "14KT")
        self.assertEqual(parsed["metal_colour"], "yellow")
        self.assertEqual(parsed["size"], 7)


class ClientFilterTests(unittest.TestCase):
    def test_page_size_with_client_filters(self):
        entities = {"category": "ring", "metal_colour": "rose", "material_type": "gold"}
        self.assertTrue(has_client_side_filters(entities))
        self.assertEqual(resolve_api_page_size(entities), CLIENT_SIDE_FILTER_PAGE_SIZE)

    def test_page_size_without_client_filters(self):
        entities = {"category": "ring", "material_type": "diamond", "max_price": 30000}
        self.assertFalse(has_client_side_filters(entities))
        self.assertEqual(resolve_api_page_size(entities), DEFAULT_API_PAGE_SIZE)

    def test_rose_gold_triggers_larger_page_size(self):
        entities = {"category": "ring", "material_type": "rose_gold"}
        self.assertTrue(has_client_side_filters(entities))
        self.assertEqual(resolve_api_page_size(entities), CLIENT_SIDE_FILTER_PAGE_SIZE)

    def test_api_params_int_prices(self):
        params = entities_to_api_params(
            {"category": "ring", "material_type": "diamond", "max_price": 50000.0}
        )
        self.assertEqual(params["max_price"], 50000)
        self.assertIsInstance(params["max_price"], int)
        self.assertNotIn("metal_colour", params)

    def test_collection_maps_to_title_only(self):
        params = entities_to_api_params(
            {"category": "bracelet", "collection": "Evil Eye", "metal_colour": "yellow"}
        )
        self.assertEqual(params["title"], "Evil Eye")
        self.assertNotIn("collection", params)
        self.assertNotIn("metal_colour", params)

    def test_filter_evil_eye_collection_fixture(self):
        product_id = _peace_hamsa_bracelet()["_id"]
        filtered, note = filter_products_by_extracted_extras(
            _load_products(),
            {"collection": "Evil Eye"},
        )
        filtered_ids = {p["_id"] for p in filtered}
        self.assertIn(product_id, filtered_ids)

    def test_filter_karat_14kt_fixture(self):
        ring_id = _nitara_ring()["_id"]
        filtered, _note = filter_products_by_extracted_extras(
            _load_products(),
            {"karat": "14KT"},
        )
        filtered_ids = {p["_id"] for p in filtered}
        self.assertIn(ring_id, filtered_ids)

    def test_relaxation_returns_note_when_strict_filter_thin(self):
        products = _load_products()[:2]
        filtered, note = filter_products_by_extracted_extras(
            products,
            {"karat": "24KT", "size": 7},
        )
        self.assertEqual(filtered, products)
        self.assertIsNotNone(note)


if __name__ == "__main__":
    unittest.main()
