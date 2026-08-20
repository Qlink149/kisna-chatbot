"""Phase 7 guardrails — snapshot ⊆ prompts, degradation contract, behaviour checks."""

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
from kisna_chatbot.processors.classifier import _LLM_ENTITY_COLOURS, _LLM_ENTITY_KARATS
from kisna_chatbot.processors.entity_extractor import (
    CATEGORY_NORMALIZATION_MAP,
    entities_to_api_params,
    extract_entities,
    finalize_search_entities,
)
from kisna_chatbot.processors.filter_validation import build_impossible_value_prompt
from kisna_chatbot.processors.shopping_wizard import (
    entities_from_wizard,
    get_next_step,
    seed_wizard_from_entities,
    should_start_wizard,
)


def _warm_snapshot_cache() -> None:
    cf.reset_filters_cache_for_tests()
    assert cf._seed_from_snapshot(None) is not None
    cf._CACHE[None].fetched_at = time.time()
    for cid in (cf._load_snapshot() or {}).get("by_category") or {}:
        cf._seed_from_snapshot(cid)
        if cid in cf._CACHE:
            cf._CACHE[cid].fetched_at = time.time()


class SnapshotConsistencyTests(unittest.TestCase):
    def setUp(self):
        _warm_snapshot_cache()

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    def test_taught_karats_subset_of_snapshot(self):
        labels = {
            str(o.get("label") or "").upper().replace(" ", "")
            for o in cf.get_available_options(None, cf.FACET_KARAT)
        }
        for karat in _LLM_ENTITY_KARATS:
            self.assertIn(
                karat.upper().replace(" ", ""),
                labels,
                msg=f"taught karat {karat} missing from filters snapshot",
            )

    def test_taught_colours_subset_of_snapshot(self):
        labels = {
            str(o.get("label") or "").lower()
            for o in cf.get_available_options(None, cf.FACET_COLOR)
        }
        for colour in _LLM_ENTITY_COLOURS:
            self.assertIn(colour.lower(), labels)

    def test_mapped_categories_resolve_to_ids(self):
        for internal, clara in CATEGORY_NORMALIZATION_MAP.items():
            if clara is None:
                continue
            self.assertIsNotNone(
                cf.get_category_id(clara),
                msg=f"{internal} → {clara} has no categoryId in snapshot",
            )


class DegradationContractTests(unittest.TestCase):
    """Filters forced off ⇒ slug/title path identical to pre-Phase-0 shape."""

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    def test_cold_uses_slug_not_category_id(self):
        cf.reset_filters_cache_for_tests()
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        params = entities_to_api_params(
            {"category": "ring", "material_type": "gold", "max_price": 50000}
        )
        self.assertEqual(params.get("category"), "ring")
        self.assertNotIn("category_id", params)
        self.assertNotIn("meta_sub_attribute_value", params)

    def test_cold_collection_falls_back_to_title(self):
        cf.reset_filters_cache_for_tests()
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        params = entities_to_api_params(
            {"category": "bracelet", "collection": "evil eye"}
        )
        self.assertEqual(params.get("title"), "evil eye")
        self.assertNotIn("collection_id", params)

    def test_cold_skips_impossible_validation(self):
        cf.reset_filters_cache_for_tests()
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        self.assertIsNone(
            build_impossible_value_prompt({"category": "chain", "karat": "22KT"})
        )

    def test_cold_wizard_asks_legacy_gender(self):
        cf.reset_filters_cache_for_tests()
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        seeded = seed_wizard_from_entities({"category": "chain"})
        self.assertEqual(get_next_step(seeded), "gender")


class BehaviourGuardrailTests(unittest.TestCase):
    def setUp(self):
        _warm_snapshot_cache()

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    def test_gender_skip_for_chain(self):
        seeded = seed_wizard_from_entities({"category": "chain"})
        self.assertEqual(get_next_step(seeded), "material")
        self.assertEqual(seeded.get("gender"), "women")

    def test_impossible_22kt_blocked(self):
        prompt = build_impossible_value_prompt(
            {"category": "chain", "karat": "22KT"}
        )
        self.assertIsNotNone(prompt)
        self.assertIn("22kt", prompt[0]["text"].lower())

    def test_explicit_survives_wizard_completion_shape(self):
        collected = {
            "category": "chain",
            "gender": "women",
            "material_type": "gold",
            "min_price": 0,
            "max_price": 50000,
            "fulfillment": "ready",
        }
        explicit = {"karat": "18KT", "metal_colour": "rose"}
        ents = entities_from_wizard(collected, explicit)
        self.assertEqual(ents["karat"], "18KT")
        self.assertEqual(ents["metal_colour"], "rose")
        self.assertFalse(should_start_wizard({**ents, **collected}))

    def test_category_id_preferred_when_warm(self):
        ents = finalize_search_entities(extract_entities("gold rings under 50k"))
        params = entities_to_api_params(dict(ents))
        self.assertIn("category_id", params)
        self.assertNotIn("category", params)


if __name__ == "__main__":
    unittest.main()
