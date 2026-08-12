"""Material must not bleed across a new product category."""

import os
import unittest

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GROQ_API_KEY": "test",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_TOKEN": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "JWT_SECRET_KEY": "test",
    "SYSTEM_API_KEY": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_OFFERS_API": "http://localhost/offers",
    "KISNA_STORE_API": "http://localhost/stores",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "KB_ENABLED": "false",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    _NEVER_INHERIT_FIELDS,
    merge_search_entities,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    filter_wizard_carryover,
    get_next_step,
    seed_wizard_from_entities,
    should_start_wizard,
)


def _empty() -> dict:
    return {
        "category": None,
        "material_type": None,
        "min_price": None,
        "max_price": None,
        "title": None,
        "city": None,
        "pincode": None,
        "karat": None,
        "metal_colour": None,
        "size": None,
        "collection": None,
        "gender": None,
        "occasion": None,
        "style": None,
        "action": None,
        "fulfillment": None,
    }


def _also_entities(last_filters: dict, secondary: str) -> dict:
    """Mirror search$also$ inherit rules in product_search_agent_v3."""
    also_drop = frozenset({"material_type", "min_price", "max_price"})
    inherited = {
        k: v
        for k, v in last_filters.items()
        if k not in _NEVER_INHERIT_FIELDS and k not in also_drop and v is not None
    }
    return {
        **_empty(),
        **inherited,
        "category": secondary,
        "categories": [secondary],
        "multi_category": False,
        "secondary_category": None,
    }


class AlsoButtonMaterialBleedTests(unittest.TestCase):
    def test_also_excludes_prior_material_and_budget(self):
        last = {
            "category": "ring",
            "material_type": "gold",
            "gender": "women",
            "fulfillment": "ready",
            "min_price": 0,
            "max_price": 50000,
        }
        ents = _also_entities(last, "earring")
        self.assertEqual(ents["category"], "earring")
        self.assertIsNone(ents["material_type"])
        self.assertIsNone(ents["min_price"])
        self.assertIsNone(ents["max_price"])
        self.assertEqual(ents["gender"], "women")
        self.assertEqual(ents["fulfillment"], "ready")

    def test_also_starts_wizard_for_material(self):
        last = {
            "category": "ring",
            "material_type": "gold",
            "gender": "women",
            "fulfillment": "ready",
            "max_price": 40000,
        }
        ents = _also_entities(last, "necklace")
        self.assertTrue(should_start_wizard(ents))
        seeded = seed_wizard_from_entities(ents)
        self.assertEqual(get_next_step(seeded), "material")


class CarryoverMaterialGateTests(unittest.TestCase):
    def test_drops_material_on_category_change(self):
        carryover = {
            "gender": "women",
            "material_type": "gold",
            "fulfillment": "ready",
        }
        entities = {"category": "necklace"}
        prior = {"category": "ring", "material_type": "gold"}
        gated = filter_wizard_carryover(carryover, entities, prior)
        self.assertNotIn("material_type", gated)
        self.assertNotIn("gender", gated)
        self.assertEqual(gated["fulfillment"], "ready")

    def test_keeps_material_same_funnel_no_prior_category(self):
        carryover = {"gender": "women", "material_type": "gold"}
        entities = {"category": "ring"}
        gated = filter_wizard_carryover(carryover, entities, {})
        self.assertEqual(gated["material_type"], "gold")
        self.assertEqual(gated["gender"], "women")
        gated_none = filter_wizard_carryover(carryover, entities, None)
        self.assertEqual(gated_none["material_type"], "gold")

    def test_keeps_material_same_category(self):
        carryover = {"material_type": "diamond", "gender": "women"}
        entities = {"category": "ring"}
        prior = {"category": "ring", "material_type": "gold"}
        gated = filter_wizard_carryover(carryover, entities, prior)
        self.assertEqual(gated["material_type"], "diamond")
        self.assertEqual(gated["gender"], "women")

    def test_drops_gender_carryover_for_parents_same_category(self):
        carryover = {"gender": "women", "material_type": "gold"}
        entities = {"category": "ring"}
        prior = {"category": "ring", "gender": "women"}
        gated = filter_wizard_carryover(
            carryover,
            entities,
            prior,
            query="I need a ring for my parents",
        )
        self.assertNotIn("gender", gated)
        # Prior search + unevidenced material also cleared on bare ask.
        self.assertNotIn("material_type", gated)

    def test_bare_rings_ask_drops_prior_gender_and_material(self):
        query = "can you show me rings"
        carryover = {"gender": "men", "material_type": "gold", "fulfillment": "ready"}
        gated = filter_wizard_carryover(
            carryover,
            {"category": "ring"},
            {"category": "ring", "gender": "men", "material_type": "gold"},
            query=query,
        )
        self.assertNotIn("gender", gated)
        self.assertNotIn("material_type", gated)
        self.assertEqual(gated.get("fulfillment"), "ready")
        seeded = seed_wizard_from_entities(
            {"category": "ring", **gated},
            query=query,
        )
        self.assertEqual(get_next_step(seeded), "gender")

    def test_merge_still_drops_material_on_new_category(self):
        prior = {"category": "ring", "material_type": "gold", "max_price": 50000}
        new = {
            "category": "necklace",
            "material_type": None,
            "min_price": None,
            "max_price": None,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "show me necklaces")
        self.assertIsNone(merged["material_type"])


if __name__ == "__main__":
    unittest.main()
