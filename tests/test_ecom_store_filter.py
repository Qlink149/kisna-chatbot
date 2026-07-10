"""Tests for ECOM store exclusion."""

import unittest

from kisna_chatbot.processors.ad_flow_agent import (
    _build_store_responses,
    _exclude_ecom_stores,
    _filter_cached_stores,
)


class TestEcomStoreFilter(unittest.TestCase):
    def test_exclude_ecom_stores(self):
        stores = [
            {"name": "KISNA Mumbai"},
            {"name": "KISNA ECOM Warehouse"},
            {"title": "ecom fulfilment"},
        ]
        filtered = _exclude_ecom_stores(stores)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["name"], "KISNA Mumbai")

    def test_filter_cached_stores_excludes_ecom(self):
        cached = {
            "stores": [
                {"name": "KISNA Delhi", "address": "Delhi 110001"},
                {"name": "KISNA ECOM", "address": "110001"},
            ]
        }
        result = _filter_cached_stores(cached, pincode="110001")
        self.assertEqual(len(result["stores"]), 1)
        self.assertNotIn("ECOM", result["stores"][0]["name"])

    def test_build_store_responses_skips_ecom(self):
        stores = [
            {"name": "KISNA Pune", "address": "Pune"},
            {"name": "ECOM Hub", "address": "Pune"},
        ]
        responses = _build_store_responses(stores)
        self.assertEqual(len(responses), 1)
        self.assertIn("Pune", responses[0]["text"])


if __name__ == "__main__":
    unittest.main()
