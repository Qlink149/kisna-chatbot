"""Phase 5 — impossible filter value validation."""

from __future__ import annotations

import os
import time
import unittest

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_SOURCE": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "OPENAI_API_KEY": "sk-test",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.integrations import clara_filters as cf
from kisna_chatbot.processors.filter_validation import build_impossible_value_prompt
from kisna_chatbot.processors.shopping_wizard import should_start_wizard


class FilterValidationTests(unittest.TestCase):
    def setUp(self):
        cf.reset_filters_cache_for_tests()
        self.assertIsNotNone(cf._seed_from_snapshot(None))
        cf._CACHE[None].fetched_at = time.time()
        for cid in (cf._load_snapshot() or {}).get("by_category") or {}:
            cf._seed_from_snapshot(cid)
            if cid in cf._CACHE:
                cf._CACHE[cid].fetched_at = time.time()

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    def test_22kt_chain_blocked_with_suggestions(self):
        prompt = build_impossible_value_prompt(
            {"category": "chain", "karat": "22KT", "material_type": "gold"}
        )
        self.assertIsNotNone(prompt)
        text = prompt[0]["text"].lower()
        self.assertIn("22kt", text)
        self.assertIn("chain", text)
        self.assertEqual(prompt[1]["type"], "quickreply")
        self.assertLessEqual(len(prompt[1]["options"]), 3)

    def test_valid_18kt_passes(self):
        self.assertIsNone(
            build_impossible_value_prompt(
                {"category": "chain", "karat": "18KT", "material_type": "gold"}
            )
        )

    def test_cold_cache_skips_validation(self):
        cf.reset_filters_cache_for_tests()
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        self.assertIsNone(
            build_impossible_value_prompt(
                {"category": "chain", "karat": "22KT"}
            )
        )

    def test_wizard_still_skips_when_slots_known_with_explicit_meta(self):
        # Phase 2+5: full wizard slots + explicit karat must not force wizard.
        ents = {
            "category": "ring",
            "gender": "women",
            "material_type": "gold",
            "min_price": 0,
            "max_price": 50000,
            "fulfillment": "ready",
            "karat": "18KT",
            "metal_colour": "rose",
        }
        self.assertFalse(should_start_wizard(ents))


if __name__ == "__main__":
    unittest.main()
