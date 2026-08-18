"""Single-price snapping to the website's price bands."""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

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
        self.assertEqual(_snap_single_price_to_band(50000), (50000, 60000))

    def test_snap_25000(self):
        self.assertEqual(_snap_single_price_to_band(25000), (20000, 30000))

    def test_every_website_band_edge(self):
        # The buckets offered on kisna.com. An amount sitting exactly on an edge
        # belongs to the bucket that STARTS there (20000 → 20k-30k).
        cases = [
            (500, (0, 10000)),
            (9999, (0, 10000)),
            (10000, (10000, 20000)),
            (19999, (10000, 20000)),
            (20000, (20000, 30000)),
            (35000, (30000, 40000)),
            (45000, (40000, 50000)),
            (65000, (60000, 70000)),
            (79999, (70000, 80000)),
            (80000, (80000, 100000)),  # 80k-1L is one wide bucket on the site
            (99999, (80000, 100000)),
            (100000, (100000, 150000)),
            (149999, (100000, 150000)),
            (150000, (150000, 200000)),
            (199999, (150000, 200000)),
        ]
        for price, expected in cases:
            self.assertEqual(_snap_single_price_to_band(price), expected, msg=price)

    def test_two_lakh_and_up_is_open_ended(self):
        # "Above 2L", "Above 3L", … — floored to the whole lakh, no ceiling.
        for price, expected_min in (
            (200000, 200000),
            (250000, 200000),
            (300000, 300000),
            (400000, 400000),
            (999999, 900000),
        ):
            lo, hi = _snap_single_price_to_band(price)
            self.assertEqual(lo, expected_min, msg=price)
            self.assertIsNone(hi, msg=price)

    def test_asymmetric_llm_band_recomputed_around_single_amount(self):
        # Transcript bug: "25 hazaar ka mangalsutra" → LLM emitted 22500–25000
        # (a lopsided band, no range word). The stated amount rules: 20k-30k.
        out = normalize_price_entities(
            "25 hazaar ka mangalsutra",
            {"min_price": 22500, "max_price": 25000},
        )
        self.assertEqual(out["min_price"], 20000)
        self.assertEqual(out["max_price"], 30000)

    def test_snapped_band_is_stable(self):
        # A band that already matches the site must not be widened again.
        for lo, hi in ((20000, 30000), (50000, 60000), (80000, 100000)):
            self.assertEqual(_snap_single_price_to_band(lo), (lo, hi))

    def test_price_followup_recaps_shown_products(self):
        # Regression: "iska price kya hai?" after a list re-ran a search instead
        # of answering about the shown pieces.
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _handle_product_info_followup,
        )

        data = {
            "classified_category": "product_search",
            "user_profile": {
                "last_search_products": [
                    {"title": "Clara Ring", "price": {"finalPrice": 42000}},
                    {"title": "Nitara Ring", "price": {"finalPrice": 38000}},
                ]
            },
        }
        result = _handle_product_info_followup(data, "iska price kya hai?")
        self.assertIsNotNone(result)
        text = result["bot_response"][0]["text"]
        self.assertIn("Clara Ring", text)
        self.assertIn("42,000", text)
        self.assertIn("Nitara Ring", text)

    def test_price_followup_recaps_all_not_one_card(self):
        # After seeing a LIST (no single product opened), "iska price?" must
        # recap ALL shown pieces with prices — never answer about one arbitrary
        # item. (Root fix: a multi-result search no longer stamps last_viewed.)
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _handle_product_info_followup,
        )

        data = {
            "classified_category": "product_search",
            "user_profile": {
                "last_search_products": [
                    {"_id": "1", "title": "Estaa Necklace", "price": {"finalPrice": 29504}},
                    {"_id": "2", "title": "Harini Necklace", "price": {"finalPrice": 32100}},
                ]
            },
        }
        result = _handle_product_info_followup(data, "iska price kya hai?")
        self.assertIsNotNone(result)
        text = result["bot_response"][0]["text"]
        self.assertIn("Estaa Necklace", text)
        self.assertIn("Harini Necklace", text)  # ALL shown, not one card

    def test_price_followup_does_not_hijack_new_search(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _handle_product_info_followup,
        )

        data = {
            "classified_category": "product_search",
            "user_profile": {
                "last_search_products": [
                    {"title": "X", "price": {"finalPrice": 1000}}
                ]
            },
        }
        # Names a new category → must fall through to a real search.
        self.assertIsNone(
            _handle_product_info_followup(data, "necklaces ka price batao")
        )
        # Plain search with no price-reference → not hijacked.
        self.assertIsNone(
            _handle_product_info_followup(data, "gold rings dikhao")
        )

    def test_category_switch_not_treated_as_pagination(self):
        # Regression: "gold rings dikhao" / "necklaces" during an active necklace
        # search must NOT page the old results (action='more' over-triggered by
        # 'dikhao'). A message naming a category is always a fresh search.
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _is_show_more_request,
            _names_new_search_subject,
        )

        data = {
            "classified_category": "product_search",
            "user_profile": {"last_search_filters": {"category": "necklace"}},
            "llm_extracted_entities": {"action": "more"},
        }
        for q in ("gold rings dikhao", "necklaces dikhao", "necklaces", "earrings"):
            data["messages"] = {"text": {"body": q}}
            self.assertTrue(_names_new_search_subject(q), msg=q)
            self.assertFalse(_is_show_more_request(q, data), msg=q)

    def test_native_category_switch_not_pagination_via_llm(self):
        # Language-agnostic: the LLM's extracted category (not Latin regex) marks
        # a new subject, so a native "नेकलेस दिखाओ" during a ring search is a
        # fresh search, never pagination — even with a stray action='more'.
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _is_show_more_request,
        )

        data = {
            "classified_category": "product_search",
            "user_profile": {"last_search_filters": {"category": "ring"}},
            "llm_extracted_entities": {"category": "necklace", "action": "more"},
            "messages": {"text": {"body": "सोने का नेकलेस दिखाओ"}},
        }
        self.assertFalse(_is_show_more_request("सोने का नेकलेस दिखाओ", data))

    def test_pure_pagination_still_pages(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _is_show_more_request,
        )

        data = {
            "classified_category": "product_search",
            "user_profile": {"last_search_filters": {"category": "necklace"}},
            "llm_extracted_entities": {"action": "more"},
        }
        for q in ("aur dikhao", "show more", "next"):
            data["messages"] = {"text": {"body": q}}
            self.assertTrue(_is_show_more_request(q, data), msg=q)

    def test_plural_necklaces_detected(self):
        # Regression: "necklaces" plural was not recognized as a category.
        ents = extract_entities("necklaces under 30k")
        self.assertEqual(ents.get("category"), "necklace")
        self.assertEqual(ents.get("max_price"), 30000)

    def test_range_suffix_distributes_to_both_sides(self):
        # "25-30k" means 25k-30k — the bare side must not read as ₹25.
        for text, lo, hi in (
            ("25-30k ring", 25000, 30000),
            ("25 to 30k ring", 25000, 30000),
            ("10-20k earrings", 10000, 20000),
            ("1-2 lakh necklace", 100000, 200000),
        ):
            ents = extract_entities(text)
            self.assertEqual(ents.get("min_price"), lo, msg=text)
            self.assertEqual(ents.get("max_price"), hi, msg=text)

    def test_both_sided_range_still_works(self):
        # Regression guard: explicit both-suffix ranges unchanged.
        for text, lo, hi in (
            ("20k-50k ring", 20000, 50000),
            ("25000-30000 ring", 25000, 30000),
        ):
            ents = extract_entities(text)
            self.assertEqual(ents.get("min_price"), lo, msg=text)
            self.assertEqual(ents.get("max_price"), hi, msg=text)

    def test_genuine_range_left_unchanged(self):
        # A real range carries a range word — never recompute it.
        out = normalize_price_entities(
            "20000 se 25000 tak",
            {"min_price": 20000, "max_price": 25000},
        )
        self.assertEqual(out["min_price"], 20000)
        self.assertEqual(out["max_price"], 25000)

    def test_custom_budget_bare_digits(self):
        self.assertEqual(_parse_custom_budget_text("25000"), (20000, 30000))
        self.assertEqual(_parse_custom_budget_text("50000"), (50000, 60000))

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
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertEqual(ents.get("max_price"), 60000)

    def test_50k_ka_ring_is_band(self):
        ents = extract_entities("50k ka ring")
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertEqual(ents.get("max_price"), 60000)
        self.assertEqual(ents.get("category"), "ring")

    def test_of_price_50000_is_band(self):
        ents = extract_entities("Show me gold rings of price 50000")
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertEqual(ents.get("max_price"), 60000)
        self.assertEqual(ents.get("category"), "ring")
        self.assertEqual(ents.get("material_type"), "gold")
        self.assertIsNone(ents.get("metal_colour"))

    def test_price_50000_is_band(self):
        ents = extract_entities("price 50000")
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertEqual(ents.get("max_price"), 60000)

    def test_around_50000_is_website_band(self):
        ents = extract_entities("around 50000")
        self.assertEqual(ents.get("min_price"), 50000)
        self.assertEqual(ents.get("max_price"), 60000)

    def test_around_one_lakh_is_website_band(self):
        ents = extract_entities("around 1 lakh")
        self.assertEqual(ents.get("min_price"), 100000)
        self.assertEqual(ents.get("max_price"), 150000)

    def test_normalize_snaps_llm_exact_min_eq_max(self):
        out = normalize_price_entities(
            "Show me gold rings of price 50000",
            {"min_price": 50000, "max_price": 50000},
        )
        self.assertEqual(out["min_price"], 50000)
        self.assertEqual(out["max_price"], 60000)

    def test_normalize_snaps_single_amount_above_two_lakh(self):
        out = normalize_price_entities(
            "budget 250000",
            {"min_price": 250000, "max_price": 250000},
        )
        self.assertEqual(out["min_price"], 200000)
        self.assertIsNone(out["max_price"])

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
        self.assertEqual(params.get("min_price"), 50000)
        self.assertEqual(params.get("max_price"), 60000)


class TestEvidenceGate(unittest.TestCase):
    def test_strips_invented_yellow_on_gold_rings(self):
        gated = apply_llm_evidence_gate(
            "Show me gold rings of price 50000",
            {
                "category": "ring",
                "material_type": "gold",
                "metal_colour": "yellow",
                "min_price": 47500,
                "max_price": 52500,
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

    def test_strips_invented_fulfillment(self):
        gated = apply_llm_evidence_gate(
            "gold rings under 20000",
            {"category": "ring", "material_type": "gold", "fulfillment": "ready"},
        )
        self.assertIsNone(gated["fulfillment"])

    def test_keeps_ready_when_user_said_ready_to_ship(self):
        gated = apply_llm_evidence_gate(
            "ready to ship diamond rings",
            {"category": "ring", "material_type": "diamond", "fulfillment": "ready"},
        )
        self.assertEqual(gated["fulfillment"], "ready")

    def test_keeps_mto_when_user_said_made_to_order(self):
        gated = apply_llm_evidence_gate(
            "made to order gold necklace",
            {"category": "necklace", "material_type": "gold", "fulfillment": "mto"},
        )
        self.assertEqual(gated["fulfillment"], "mto")

    def test_strips_wrong_fulfillment_value(self):
        # User said ready; LLM wrongly set mto → strip (regex fill can re-apply).
        gated = apply_llm_evidence_gate(
            "ready to ship rings",
            {"category": "ring", "fulfillment": "mto"},
        )
        self.assertIsNone(gated["fulfillment"])


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
    def test_band_note_names_the_band_not_under(self):
        note = _fallback_prefix_note(
            "budget",
            [],
            {"min_price": 50000, "max_price": 60000},
            {},
        )
        self.assertIsNotNone(note)
        self.assertIn("₹50,000–₹60,000", note)
        self.assertNotIn("under ₹", note)
        # No invented midpoint the user never said.
        self.assertNotIn("55,000", note)

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
