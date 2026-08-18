"""Seasonal rakhi title-search overlay — on-path plus flag-off regressions."""

import os
import unittest
from unittest.mock import patch

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

from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    apply_occasion_style_hints,
    entities_to_api_params,
    extract_entities,
    extract_structured_fields,
    merge_search_entities,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    advance_wizard,
    should_start_wizard,
    start_wizard,
)
from kisna_chatbot.prompts.classifier_kisna import (  # noqa: E402
    kisna_classifier_intent,
    kisna_entity_extractor,
)
from kisna_chatbot.utils.rakhi_season import (  # noqa: E402
    apply_rakhi_title_hint,
    is_rakhi_query,
)

_RAKHI_DEVANAGARI = "\u0930\u093e\u0916\u0940"


class RakhiSeasonOnTests(unittest.TestCase):
    def test_typos_and_scripts_set_title_rakhi(self):
        for query in (
            "rakhni",
            "rakhi dikhao",
            "rakhee",
            "rakkhi",
            "raksha bandhan",
            _RAKHI_DEVANAGARI,
        ):
            with self.subTest(query=query):
                out = apply_rakhi_title_hint({}, query=query)
                self.assertEqual(out.get("title"), "rakhi")
                self.assertIsNone(out.get("category"))

    def test_gold_rakhi_keeps_material(self):
        out = apply_rakhi_title_hint(
            {"material_type": "gold"}, query="gold rakhi"
        )
        self.assertEqual(out.get("title"), "rakhi")
        self.assertEqual(out.get("material_type"), "gold")
        self.assertIsNone(out.get("category"))

    def test_rakhi_pendant_keeps_category(self):
        out = apply_rakhi_title_hint(
            {"category": "pendant"}, query="rakhi pendant"
        )
        self.assertEqual(out.get("title"), "rakhi")
        self.assertEqual(out.get("category"), "pendant")

    def test_canonicalizes_extracted_typo_title(self):
        out = apply_rakhi_title_hint({"title": "rakhni"})
        self.assertEqual(out.get("title"), "rakhi")

    def test_non_rakhi_queries_are_noop(self):
        for query, ents in (
            ("gold rings", {"category": "ring", "material_type": "gold"}),
            ("shaadi ke liye", {"occasion": "wedding"}),
            ("rivaah collection", {"title": "rivaah"}),
            ("gift for mom", {"occasion": "gift", "gender": "women"}),
        ):
            with self.subTest(query=query):
                out = apply_rakhi_title_hint(ents, query=query)
                self.assertEqual(out, ents)

    def test_gold_rings_regex_still_ring_no_rakhi_title(self):
        ents = extract_entities("gold rings")
        self.assertEqual(ents.get("category"), "ring")
        hinted = apply_rakhi_title_hint(ents, query="gold rings")
        self.assertNotEqual(hinted.get("title"), "rakhi")

    def test_wizard_skipped_for_rakhi_title_only(self):
        self.assertFalse(should_start_wizard({"title": "rakhi"}))

    def test_wizard_still_starts_for_ring_and_other_titles(self):
        self.assertTrue(should_start_wizard({"category": "ring"}))
        self.assertTrue(should_start_wizard({"title": "bridal"}))
        self.assertTrue(should_start_wizard({"title": "rivaah"}))

    def test_api_params_title_only(self):
        params = entities_to_api_params({"title": "rakhi"})
        self.assertEqual(params.get("title"), "rakhi")
        self.assertNotIn("category", params)

    def test_merge_does_not_inherit_prior_ring(self):
        extracted = apply_rakhi_title_hint({}, query="rakhi")
        merged = merge_search_entities(
            {"category": "ring", "material_type": "gold"},
            extracted,
            "rakhi",
        )
        self.assertEqual(merged.get("title"), "rakhi")
        self.assertIsNone(merged.get("category"))

    def test_category_step_escape_on_rakhni(self):
        profile = {}
        start_wizard(profile, entities={})
        self.assertEqual(profile.get("shopping_wizard_step"), "category")
        status, _ = advance_wizard(profile, {}, text="rakhni")
        self.assertEqual(status, "escape")
        self.assertFalse(profile.get("shopping_wizard_active"))

    def test_prompts_append_override_and_keep_gift_line(self):
        self.assertIn("RAKHI SEASON", kisna_classifier_intent)
        self.assertIn("rakhni", kisna_classifier_intent)
        self.assertIn("happy rakhi", kisna_classifier_intent)
        self.assertIn("RAKHI SEASON OVERRIDE", kisna_entity_extractor)
        self.assertIn('"title":"rakhi"', kisna_entity_extractor)
        self.assertIn(
            "gift/tuhfa/present/valentine/diwali gift/rakhi/festive \u2192 gift",
            kisna_entity_extractor,
        )


class RakhiSeasonOffTests(unittest.TestCase):
    def test_flag_off_hint_is_noop(self):
        with patch(
            "kisna_chatbot.utils.rakhi_season.RAKHI_TITLE_SEARCH_ENABLED",
            False,
        ):
            out = apply_rakhi_title_hint({}, query="rakhni")
            self.assertIsNone(out.get("title"))
            self.assertFalse(is_rakhi_query("rakhi"))

    def test_flag_off_wizard_asks_again(self):
        with patch(
            "kisna_chatbot.utils.rakhi_season.RAKHI_TITLE_SEARCH_ENABLED",
            False,
        ):
            self.assertTrue(should_start_wizard({"title": "rakhi"}))
            self.assertTrue(should_start_wizard({"category": "ring"}))

    def test_flag_off_does_not_escape_wizard(self):
        profile = {}
        start_wizard(profile, entities={})
        with patch(
            "kisna_chatbot.utils.rakhi_season.RAKHI_TITLE_SEARCH_ENABLED",
            False,
        ):
            status, responses = advance_wizard(profile, {}, text="rakhni")
        self.assertNotEqual(status, "escape")
        self.assertTrue(profile.get("shopping_wizard_active"))

    def test_wedding_bridal_title_untouched(self):
        enhanced, _ = apply_occasion_style_hints({"occasion": "wedding"})
        self.assertEqual(enhanced.get("title"), "bridal")

    def test_structured_fields_still_have_no_title(self):
        fields = extract_structured_fields("rakhni dikhao")
        self.assertNotIn("title", fields)
        self.assertNotIn("category", fields)



class RakhiFollowupInheritTests(unittest.TestCase):
    def test_price_followup_keeps_rakhi_title(self):
        from kisna_chatbot.utils.rakhi_season import inherit_rakhi_title

        out = inherit_rakhi_title(
            {"min_price": 15000},
            {"title": "rakhi"},
        )
        self.assertEqual(out.get("title"), "rakhi")
        self.assertEqual(out.get("min_price"), 15000)
        self.assertIsNone(out.get("category"))

    def test_new_category_drops_rakhi_title(self):
        from kisna_chatbot.utils.rakhi_season import inherit_rakhi_title

        out = inherit_rakhi_title(
            {"category": "ring"},
            {"title": "rakhi"},
        )
        self.assertIsNone(out.get("title"))
        self.assertEqual(out.get("category"), "ring")

    def test_bridal_title_is_not_inherited(self):
        from kisna_chatbot.utils.rakhi_season import inherit_rakhi_title

        out = inherit_rakhi_title({"min_price": 15000}, {"title": "bridal"})
        self.assertIsNone(out.get("title"))

    def test_rivaah_title_is_not_inherited(self):
        from kisna_chatbot.utils.rakhi_season import inherit_rakhi_title

        out = inherit_rakhi_title({"max_price": 10000}, {"title": "rivaah"})
        self.assertIsNone(out.get("title"))

    def test_flag_off_does_not_inherit(self):
        from kisna_chatbot.utils.rakhi_season import inherit_rakhi_title

        with patch(
            "kisna_chatbot.utils.rakhi_season.RAKHI_TITLE_SEARCH_ENABLED",
            False,
        ):
            out = inherit_rakhi_title({"min_price": 15000}, {"title": "rakhi"})
        self.assertIsNone(out.get("title"))

    def test_price_only_refinement_sees_rakhi_prior(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _is_price_only_refinement,
        )

        profile = {
            "last_search_filters": {"title": "rakhi"},
            "service_selected": "product_search",
        }
        self.assertTrue(_is_price_only_refinement("above 15000", profile))
        self.assertFalse(
            _is_price_only_refinement(
                "above 15000",
                {"last_search_filters": {"title": "rivaah"}},
            )
        )

    def test_ring_price_refinement_still_true(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _is_price_only_refinement,
        )

        profile = {
            "last_search_filters": {"category": "ring", "material_type": "gold"},
            "service_selected": "product_search",
        }
        self.assertTrue(_is_price_only_refinement("under 10k", profile))

    def test_recap_says_rakhi_not_jewellery(self):
        from kisna_chatbot.processors.search_confirmation import build_search_recap

        recap = build_search_recap({"title": "rakhi", "min_price": 15000})
        self.assertIn("rakhi", recap.lower())
        self.assertNotIn("jewellery", recap.lower())

    def test_recap_ring_unchanged(self):
        from kisna_chatbot.processors.search_confirmation import build_search_recap

        recap = build_search_recap({"category": "ring", "max_price": 50000})
        self.assertIn("ring", recap.lower())
        self.assertNotIn("rakhi", recap.lower())

    def test_inherited_rakhi_skips_wizard(self):
        from kisna_chatbot.utils.rakhi_season import inherit_rakhi_title

        out = inherit_rakhi_title({"min_price": 15000}, {"title": "rakhi"})
        self.assertFalse(should_start_wizard(out))


if __name__ == "__main__":
    unittest.main()
