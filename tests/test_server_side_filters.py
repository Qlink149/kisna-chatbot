"""Phase 3 — server-side Clara ID params and one-meta choice."""

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
from kisna_chatbot.integrations.clara_api import build_products_query_params
from kisna_chatbot.processors.entity_extractor import (
    _choose_server_meta_key,
    entities_for_client_filter,
    entities_to_api_params,
)
from kisna_chatbot.processors.product_search_agent_v3 import _build_fallback_strategies


class ServerSideIdParamsTests(unittest.TestCase):
    def setUp(self):
        cf.reset_filters_cache_for_tests()
        # Seed a warm cache from the committed snapshot so accessors resolve.
        payload = cf._seed_from_snapshot(None)
        self.assertIsNotNone(payload)
        cf._CACHE[None].fetched_at = time.time()
        for cid in (cf._load_snapshot() or {}).get("by_category") or {}:
            cf._seed_from_snapshot(cid)
            if cid in cf._CACHE:
                cf._CACHE[cid].fetched_at = time.time()

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    def test_category_id_preferred_over_slug(self):
        ents = {"category": "ring", "material_type": "gold"}
        params = entities_to_api_params(ents)
        self.assertIn("category_id", params)
        self.assertNotIn("category", params)
        q = build_products_query_params(**params)
        self.assertIn("categoryId", q)
        self.assertNotIn("category", q)

    def test_cold_cache_falls_back_to_slug(self):
        cf.reset_filters_cache_for_tests()
        # Force no snapshot/cache
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        params = entities_to_api_params({"category": "ring"})
        self.assertEqual(params.get("category"), "ring")
        self.assertNotIn("category_id", params)

    def test_collection_uses_collection_id(self):
        params = entities_to_api_params(
            {"category": "bracelet", "collection": "evil eye"}
        )
        self.assertIn("collection_id", params)
        self.assertNotEqual(params.get("title"), "evil eye")

    def test_gender_tag_from_filters(self):
        params = entities_to_api_params({"category": "ring", "gender": "women"})
        self.assertTrue(params.get("tag_manager_id"))

    def test_one_meta_colour_when_both_present_rings(self):
        # Rings: 4 karat options, 3 colour → colour wins (fewer options).
        ring_id = cf.get_category_id("ring")
        self.assertIsNotNone(ring_id)
        choice = _choose_server_meta_key(ring_id, "18KT", "rose")
        self.assertEqual(choice, "metal_colour")
        ents = {
            "category": "ring",
            "karat": "18KT",
            "metal_colour": "rose",
        }
        params = entities_to_api_params(ents)
        self.assertTrue(params.get("meta_sub_attribute_value"))
        self.assertEqual(ents.get("_server_meta_key"), "metal_colour")
        client = entities_for_client_filter(ents)
        self.assertIsNone(client.get("metal_colour"))
        self.assertEqual(client.get("karat"), "18KT")

    def test_karat_only_goes_server_side(self):
        ents = {"category": "chain", "karat": "18KT"}
        params = entities_to_api_params(ents)
        self.assertTrue(params.get("meta_sub_attribute_value"))
        self.assertEqual(ents.get("_server_meta_key"), "karat")

    def test_ladder_drops_meta_before_price(self):
        ents = {
            "category": "ring",
            "karat": "18KT",
            "metal_colour": "rose",
            "min_price": 0,
            "max_price": 50000,
            "material_type": "gold",
        }
        labels = [label for _e, _n, label in _build_fallback_strategies(ents)]
        self.assertIn("drop_meta", labels)
        self.assertIn("drop_price", labels)
        self.assertLess(labels.index("drop_meta"), labels.index("drop_price"))

    def test_collection_only_drop_gets_its_own_note_kind(self):
        # A genuinely-real collection with zero inventory for this
        # gender/category (most named collections skew heavily toward one
        # gender) needs a different message from an actual karat/colour
        # mismatch -- "Evil Eye Collection doesn't have men's rings" is
        # honest; the old generic "couldn't match karat/colour/collection"
        # line read like a fuzzy-matching failure instead.
        ents = {"category": "ring", "gender": "men", "collection": "evil eye"}
        kinds = {
            label: note_kind
            for _e, note_kind, label in _build_fallback_strategies(ents)
        }
        self.assertEqual(kinds.get("drop_meta"), "collection")

    def test_karat_and_collection_together_keep_generic_meta_note(self):
        ents = {"category": "ring", "karat": "18KT", "collection": "evil eye"}
        kinds = {
            label: note_kind
            for _e, note_kind, label in _build_fallback_strategies(ents)
        }
        self.assertEqual(kinds.get("drop_meta"), "meta")

    def test_collection_fallback_message_names_the_collection(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _fallback_prefix_note,
        )

        ents = {"category": "ring", "gender": "men", "collection": "evil eye"}
        dropped = {**ents, "collection": None}
        msg = _fallback_prefix_note("collection", [], ents, dropped)
        self.assertIn("Evil Eye Collection", msg)
        self.assertIn("men's rings", msg)

    def test_build_params_category_id_and_meta_and(self):
        q = build_products_query_params(
            category_id="66ec04e2bd0b630008623a89",
            meta_sub_attribute_value="66ec108f8da1370008d5ba85",
            tag_manager_id="6710b86de3421b6a92589b39",
            min_price=10000,
            max_price=50000,
        )
        self.assertEqual(q["categoryId"], "66ec04e2bd0b630008623a89")
        self.assertEqual(q["metaSubAttributeValue"], "66ec108f8da1370008d5ba85")
        self.assertEqual(q["tagManagerId"], "6710b86de3421b6a92589b39")
        self.assertEqual(q["minPrice"], 10000)
        # ObjectId-only must omit searchUrl (Clara 400 otherwise).
        self.assertNotIn("searchUrl", q)

    def test_category_id_with_title_keeps_search_url(self):
        q = build_products_query_params(
            category_id="66ec04e2bd0b630008623a89",
            title="solitaire",
        )
        self.assertEqual(q["categoryId"], "66ec04e2bd0b630008623a89")
        self.assertEqual(q["searchUrl"], "true")


if __name__ == "__main__":
    unittest.main()
