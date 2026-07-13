"""±10% single-price band tests."""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from kisna_chatbot.processors.entity_extractor import (
    apply_llm_evidence_gate,
    entities_to_api_params,
    extract_entities,
    finalize_search_entities,
    normalize_price_entities,
)
from kisna_chatbot.processors.product_search_agent_v3 import (
    _fallback_prefix_note,
    _parse_custom_budget_text,
    _snap_single_price_to_band,
)


class TestPriceBand(unittest.TestCase):
    def test_snap_50000(self):
        self.assertEqual(_snap_single_price_to_band(50000), (45000, 55000))

    def test_snap_25000(self):
        self.assertEqual(_snap_single_price_to_band(25000), (22500, 27500))

    def test_custom_budget_bare_digits(self):
        self.assertEqual(_parse_custom_budget_text("25000"), (22500, 27500))
        self.assertEqual(_parse_custom_budget_text("50000"), (45000, 55000))

    def test_under_unchanged(self):
        self.assertEqual(_parse_custom_budget_text("under 50000"), (0, 50000))
        ents = extract_entities("under 50000")
        self.assertIsNone(ents.get("min_price"))
        self.assertEqual(ents.get("max_price"), 50000)

    def test_above_unchanged(self):
        ents = extract_entities("above 50000")
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertIsNone(ents.get("max_price"))

    def test_range_unchanged(self):
        self.assertEqual(_parse_custom_budget_text("40000-60000"), (40000, 60000))

    def test_tak_unchanged(self):
        ents = extract_entities("50k tak")
        self.assertIsNone(ents.get("min_price"))
        self.assertEqual(ents.get("max_price"), 50000)

    def test_budget_without_direction_is_band(self):
        ents = extract_entities("budget 50000 hai")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)

    def test_50k_ka_ring_is_band(self):
        ents = extract_entities("50k ka ring")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)
        self.assertEqual(ents.get("category"), "ring")

    def test_of_price_50000_is_band(self):
        ents = extract_entities("Show me gold rings of price 50000")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)
        self.assertEqual(ents.get("category"), "ring")
        self.assertEqual(ents.get("material_type"), "gold")
        self.assertIsNone(ents.get("metal_colour"))

    def test_price_50000_is_band(self):
        ents = extract_entities("price 50000")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)

    def test_around_50000_is_pm10_band(self):
        ents = extract_entities("around 50000")
        self.assertEqual(ents.get("min_price"), 45000)
        self.assertEqual(ents.get("max_price"), 55000)

    def test_normalize_snaps_llm_exact_min_eq_max(self):
        out = normalize_price_entities(
            "Show me gold rings of price 50000",
            {"min_price": 50000, "max_price": 50000},
        )
        self.assertEqual(out["min_price"], 45000)
        self.assertEqual(out["max_price"], 55000)

    def test_normalize_keeps_under(self):
        out = normalize_price_entities(
            "under 50000",
            {"min_price": None, "max_price": 50000},
        )
        self.assertIsNone(out["min_price"])
        self.assertEqual(out["max_price"], 50000)

    def test_normalize_keeps_above(self):
        out = normalize_price_entities(
            "above 50000",
            {"min_price": 50000, "max_price": None},
        )
        self.assertEqual(out["min_price"], 50000)
        self.assertIsNone(out["max_price"])

    def test_finalize_of_price_api_params(self):
        ents = finalize_search_entities(
            {
                "category": "ring",
                "material_type": "gold",
                "min_price": 50000,
                "max_price": 50000,
            },
            query="Show me gold rings of price 50000",
        )
        params = entities_to_api_params(ents)
        self.assertEqual(params.get("min_price"), 45000)
        self.assertEqual(params.get("max_price"), 55000)


class TestEvidenceGate(unittest.TestCase):
    def test_strips_invented_yellow_on_gold_rings(self):
        gated = apply_llm_evidence_gate(
            "Show me gold rings of price 50000",
            {
                "category": "ring",
                "material_type": "gold",
                "metal_colour": "yellow",
                "min_price": 45000,
                "max_price": 55000,
            },
        )
        self.assertEqual(gated["material_type"], "gold")
        self.assertIsNone(gated["metal_colour"])

    def test_keeps_yellow_when_user_said_yellow_gold(self):
        gated = apply_llm_evidence_gate(
            "yellow gold rings",
            {
                "category": "ring",
                "material_type": "gold",
                "metal_colour": "yellow",
            },
        )
        self.assertEqual(gated["metal_colour"], "yellow")

    def test_strips_material_without_evidence(self):
        gated = apply_llm_evidence_gate(
            "show me rings under 10k",
            {"category": "ring", "material_type": "gold", "metal_colour": None},
        )
        self.assertIsNone(gated["material_type"])

    def test_strips_invented_wedding_on_gold_rings(self):
        gated = apply_llm_evidence_gate(
            "gold rings",
            {"category": "ring", "material_type": "gold", "occasion": "wedding"},
        )
        self.assertIsNone(gated["occasion"])

    def test_keeps_wedding_when_user_said_shaadi(self):
        gated = apply_llm_evidence_gate(
            "shaadi ke liye gold ring",
            {"category": "ring", "material_type": "gold", "occasion": "wedding"},
        )
        self.assertEqual(gated["occasion"], "wedding")

    def test_strips_invented_minimal_style(self):
        gated = apply_llm_evidence_gate(
            "gold earrings",
            {"category": "earring", "material_type": "gold", "style": "minimal"},
        )
        self.assertIsNone(gated["style"])

    def test_keeps_minimal_when_said(self):
        gated = apply_llm_evidence_gate(
            "minimal gold earrings",
            {"category": "earring", "material_type": "gold", "style": "minimal"},
        )
        self.assertEqual(gated["style"], "minimal")

    def test_strips_invented_gender(self):
        gated = apply_llm_evidence_gate(
            "gold rings",
            {"category": "ring", "material_type": "gold", "gender": "women"},
        )
        self.assertIsNone(gated["gender"])

    def test_keeps_gender_for_her(self):
        gated = apply_llm_evidence_gate(
            "for her gold rings",
            {"category": "ring", "material_type": "gold", "gender": "women"},
        )
        self.assertEqual(gated["gender"], "women")

    def test_strips_invented_collection(self):
        gated = apply_llm_evidence_gate(
            "gold bracelet",
            {"category": "bracelet", "collection": "Evil Eye"},
        )
        self.assertIsNone(gated["collection"])

    def test_keeps_collection_when_named(self):
        gated = apply_llm_evidence_gate(
            "Evil Eye bracelet",
            {"category": "bracelet", "collection": "Evil Eye"},
        )
        self.assertEqual(gated["collection"], "Evil Eye")


class TestOccasionStyleHintsGated(unittest.TestCase):
    def test_invented_wedding_with_query_does_not_set_bridal(self):
        from kisna_chatbot.processors.entity_extractor import apply_occasion_style_hints

        enhanced, _ = apply_occasion_style_hints(
            {"occasion": "wedding", "category": "ring"},
            query="gold rings",
        )
        self.assertIsNone(enhanced.get("occasion"))
        self.assertNotEqual(enhanced.get("title"), "bridal")

    def test_shaadi_query_still_sets_bridal(self):
        from kisna_chatbot.processors.entity_extractor import apply_occasion_style_hints

        gated = apply_llm_evidence_gate(
            "shaadi ke liye gold ring",
            {"occasion": "wedding", "category": "ring", "material_type": "gold"},
        )
        enhanced, _ = apply_occasion_style_hints(gated, query="shaadi ke liye gold ring")
        self.assertEqual(enhanced.get("occasion"), "wedding")
        self.assertEqual(enhanced.get("title"), "bridal")

    def test_minimal_style_sets_title_when_evidenced(self):
        from kisna_chatbot.processors.entity_extractor import apply_occasion_style_hints

        enhanced, _ = apply_occasion_style_hints(
            {"style": "minimal", "category": "earring"},
            query="minimal gold earrings",
        )
        self.assertEqual(enhanced.get("title"), "minimal")


class TestExploreClearsPrefTitle(unittest.TestCase):
    def test_explore_clear_drops_pref_title_and_budget_flags(self):
        from kisna_chatbot.processors.service_list import _clear_explore_browse_session

        profile = {
            "pref_title": "solitaire",
            "pref_material": "gold",
            "pref_category": "ring",
            "preference_step": 2,
            "awaiting_custom_budget": True,
            "custom_budget_attempts": 1,
            "last_search_filters": {"category": "ring"},
        }
        _clear_explore_browse_session(profile)
        self.assertNotIn("pref_title", profile)
        self.assertNotIn("preference_step", profile)
        self.assertNotIn("awaiting_custom_budget", profile)
        self.assertNotIn("custom_budget_attempts", profile)
        self.assertIsNone(profile.get("pref_material"))
        self.assertEqual(profile.get("last_search_filters"), {})


class TestFallbackCopy(unittest.TestCase):
    def test_band_note_says_around_not_under(self):
        note = _fallback_prefix_note(
            "budget",
            [],
            {"min_price": 45000, "max_price": 55000},
            {},
        )
        self.assertIsNotNone(note)
        self.assertIn("around ₹50,000", note)
        self.assertIn("₹45,000–₹55,000", note)
        self.assertNotIn("under ₹", note)

    def test_max_only_still_says_under(self):
        note = _fallback_prefix_note(
            "budget", [], {"max_price": 10000.0}, {}
        )
        self.assertIn("No pieces found under ₹10,000", note)

    def test_min_only_says_above(self):
        note = _fallback_prefix_note(
            "budget", [], {"min_price": 500000}, {}
        )
        self.assertIn("No pieces found above ₹500,000", note)


if __name__ == "__main__":
    unittest.main()
