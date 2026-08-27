"""Tests grounded in real Clara API JSON fixtures."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.integrations.clara_api import get_discount_for_product
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import Classifier
from kisna_chatbot.processors.entity_extractor import (
    entities_to_api_params,
    extract_category_from_product,
    extract_entities,
    filter_products_by_entities,
    finalize_search_entities,
    merge_search_entities,
    normalize_entities_for_clara,
    sanitize_search_entities,
    title_redundant_with_category,
)
from kisna_chatbot.processors.product_search_agent_v3 import (
    _SHOW_MORE_PAGE_RETRIES,
    _build_fallback_strategies,
    _compute_show_more_retries,
    _fallback_prefix_note,
)
from kisna_chatbot.utils.product_formatter import (
    format_price_line,
    get_product_price_bundle,
)
from tests.clara_local_fixtures import CLARA_FIXTURE_DIR, skip_without_clara

_FIXTURES = CLARA_FIXTURE_DIR


def _load_products() -> list[dict]:
    path = _FIXTURES / "products.json"
    with open(path, encoding="utf-8") as f:
        body = json.load(f)
    return body["data"]["data"]


def _nitara_ring() -> dict:
    for product in _load_products():
        if product.get("title") == "Nitara Ring":
            return product
    raise AssertionError("Nitara Ring not found in fixture")


class ClaraFixtureTests(unittest.TestCase):
    @skip_without_clara("products.json")
    def test_nitara_category_from_product_type(self):
        product = _nitara_ring()
        self.assertEqual(extract_category_from_product(product), "ring")

    @skip_without_clara("products.json")
    def test_filter_rings_below_10k_fixture_returns_zero(self):
        rings = [
            p for p in _load_products() if extract_category_from_product(p) == "ring"
        ]
        self.assertGreater(len(rings), 0)
        filtered = filter_products_by_entities(
            rings,
            {"category": "ring", "max_price": 10000.0},
        )
        self.assertEqual(filtered, [])

    @skip_without_clara("products.json")
    def test_filter_drops_non_ring_when_category_ring(self):
        bracelet = next(
            p
            for p in _load_products()
            if extract_category_from_product(p) == "bracelet"
        )
        ring = _nitara_ring()
        filtered = filter_products_by_entities(
            [bracelet, ring],
            {"category": "ring"},
        )
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["title"], "Nitara Ring")

    @skip_without_clara("products.json")
    def test_filter_drops_wrong_material(self):
        ring = _nitara_ring()
        filtered = filter_products_by_entities(
            [ring],
            {"category": "ring", "material_type": "gold"},
        )
        self.assertEqual(filtered, [])

    @skip_without_clara("products.json")
    def test_nitara_price_bundle_api_only_no_estimated_mrp(self):
        product = _nitara_ring()
        bundle = get_product_price_bundle(product)
        self.assertEqual(bundle["display_price"], 64892)
        self.assertIsNone(bundle["mrp_price"])
        self.assertEqual(bundle["sku"], "KFLR10009G")
        self.assertIn("30% off", bundle["promo_label"] or "")

    @skip_without_clara("products.json")
    def test_nitara_price_line_single_api_price(self):
        line = format_price_line(_nitara_ring())
        self.assertIn("64,892", line)
        self.assertNotIn("~₹", line)

    def test_merge_search_entities_keeps_category_on_budget_refinement(self):
        prior = {"category": "earring", "material_type": None, "max_price": None}
        new = {
            "category": None,
            "material_type": None,
            "min_price": None,
            "max_price": 10000.0,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "I want them under 10,000")
        self.assertEqual(merged["category"], "earring")
        self.assertEqual(merged["max_price"], 10000.0)

    def test_entities_to_api_params_from_merged(self):
        prior = {"category": "earring"}
        new = {"max_price": 10000.0}
        merged = merge_search_entities(prior, new, "under 10,000")
        params = entities_to_api_params(merged)
        self.assertNotIn("category", params)
        self.assertEqual(params["max_price"], 10000.0)

    def test_merge_price_only_new_search_clears_prior_category(self):
        prior = {"category": "pendant", "title": "set", "material_type": None}
        new = {"min_price": 500000.0, "max_price": None}
        merged = merge_search_entities(prior, new, "above 5 lakh")
        self.assertIsNone(merged["category"])
        self.assertIsNone(merged["title"])
        self.assertEqual(merged["min_price"], 500000.0)

    def test_drop_material_retains_max_price(self):
        entities = {
            "category": "ring",
            "material_type": "diamond",
            "max_price": 50000,
        }
        strategies = _build_fallback_strategies(entities)
        drop_material = next(s for s in strategies if s[2] == "drop_material")
        self.assertIsNone(drop_material[0]["material_type"])
        self.assertEqual(drop_material[0]["max_price"], 50000)

    def test_drop_fulfillment_before_material_and_price(self):
        """Ready-to-ship is softer than gold/budget — drop it first."""
        entities = {
            "category": "ring",
            "material_type": "gold",
            "gender": "men",
            "min_price": 40000,
            "max_price": 50000,
            "fulfillment": "ready",
        }
        labels = [label for _ent, _note, label in _build_fallback_strategies(entities)]
        self.assertEqual(labels[0], "full")
        self.assertEqual(labels[1], "drop_fulfillment")
        self.assertLess(labels.index("drop_fulfillment"), labels.index("drop_price"))
        self.assertLess(labels.index("drop_price"), labels.index("drop_material"))
        drop_f = next(
            s for s in _build_fallback_strategies(entities) if s[2] == "drop_fulfillment"
        )
        self.assertIsNone(drop_f[0]["fulfillment"])
        self.assertEqual(drop_f[0]["material_type"], "gold")
        self.assertEqual(drop_f[0]["max_price"], 50000)
        self.assertEqual(drop_f[0]["gender"], "men")

    def test_fulfillment_fallback_note(self):
        note = _fallback_prefix_note(
            "fulfillment",
            [],
            {"fulfillment": "ready", "material_type": "gold", "category": "ring"},
            {"material_type": "gold", "category": "ring"},
        )
        self.assertIn("ready-to-ship", note.lower())
        self.assertIn("matching options", note.lower())

    def test_category_only_appended_when_material_and_price(self):
        entities = {
            "category": "maang_tikka",
            "material_type": "gold",
            "min_price": 40000,
            "max_price": 50000,
        }
        strategies = _build_fallback_strategies(entities)
        labels = [label for _ent, _note, label in strategies]
        self.assertIn("category_only", labels)
        cat_only = next(s for s in strategies if s[2] == "category_only")
        self.assertEqual(cat_only[0]["category"], "maang_tikka")
        self.assertIsNone(cat_only[0]["material_type"])
        self.assertIsNone(cat_only[0]["min_price"])
        self.assertIsNone(cat_only[0]["max_price"])
        self.assertEqual(cat_only[1], "category")

    def test_category_only_deduped_when_same_as_drop_material(self):
        entities = {"category": "ring", "material_type": "gold"}
        labels = [label for _ent, _note, label in _build_fallback_strategies(entities)]
        self.assertIn("drop_material", labels)
        self.assertNotIn("category_only", labels)

    def test_category_only_keeps_gender(self):
        # Client-reported: the last fallback rung was silently dropping
        # gender along with everything else -- a woman's ring search could
        # widen all the way down to men's rings. Gender is jewellery-
        # essential, same as category; only material/price/etc. should be
        # relaxed away, not gender.
        entities = {
            "category": "maang_tikka",
            "material_type": "gold",
            "gender": "women",
            "min_price": 40000,
            "max_price": 50000,
        }
        strategies = _build_fallback_strategies(entities)
        cat_only = next(s for s in strategies if s[2] == "category_only")
        self.assertEqual(cat_only[0]["gender"], "women")
        self.assertEqual(cat_only[0]["category"], "maang_tikka")

    def test_category_only_no_gender_stays_none(self):
        # Must not fabricate a gender that was never in the original request.
        entities = {"category": "ring", "material_type": "gold", "min_price": 40000}
        strategies = _build_fallback_strategies(entities)
        cat_only = next(s for s in strategies if s[2] == "category_only")
        self.assertIsNone(cat_only[0]["gender"])

    def test_title_only_keeps_gender(self):
        entities = {
            "title": "Shree Pendant",
            "gender": "kids",
            "category": None,
            "material_type": "gold",
            "max_price": 50000,
        }
        strategies = _build_fallback_strategies(entities)
        title_only = next(s for s in strategies if s[2] == "title_only")
        self.assertEqual(title_only[0]["gender"], "kids")
        self.assertEqual(title_only[0]["title"], "Shree Pendant")

    def test_category_fallback_note_mentions_gender(self):
        note = _fallback_prefix_note(
            "category",
            [],
            {
                "category": "ring",
                "material_type": "diamond",
                "gender": "women",
                "max_price": 30000,
            },
            {"category": "ring", "gender": "women"},
        )
        self.assertIn("women's", note)

    def test_category_fallback_note_omits_gender_when_unset(self):
        note = _fallback_prefix_note(
            "category",
            [],
            {"category": "ring", "material_type": "diamond"},
            {"category": "ring"},
        )
        self.assertNotIn("women's", note)
        self.assertNotIn("men's", note)
        self.assertNotIn("kids'", note)

    def test_sanitize_search_entities_clears_redundant_chain_title(self):
        entities = {
            "category": "chain",
            "material_type": "gold",
            "title": "chains",
        }
        sanitized = sanitize_search_entities(entities)
        self.assertIsNone(sanitized["title"])
        self.assertEqual(sanitized["category"], "chain")

    def test_title_not_inherited_on_price_refinement(self):
        """title from a previous search must never bleed into a price-only follow-up."""
        prior = {"category": "pendant", "material_type": "gold", "title": "bridal"}
        new = {"category": None, "material_type": None, "title": None, "max_price": 50000.0}
        merged = merge_search_entities(prior, new, "under 50k")
        self.assertIsNone(merged["title"])

    def test_collection_not_inherited_on_refinement(self):
        """collection from a previous search must not carry into a context refinement."""
        prior = {"category": "ring", "collection": "tanishta", "title": None}
        new = {"category": None, "material_type": None, "collection": None, "title": None}
        merged = merge_search_entities(prior, new, "show me them in gold")
        self.assertIsNone(merged["collection"])

    def test_collection_anchored_browse_survives_price_refinement(self):
        # "show me something in evil eye" has NO category -- collection IS
        # the search's anchor here, the same role category normally plays,
        # so a price refinement must not silently drop back to the whole
        # catalogue the way the category-anchored case above correctly does.
        # (A BARE "under 20k" with no refinement framing takes a separate
        # fast path in product_search_agent_v3.py -- _is_price_only_refinement
        # -- fixed and live-verified separately; this covers the phrasing
        # that reaches merge_search_entities's own refinement_only branch,
        # matching the sibling karat/title tests' style above.)
        prior = {"collection": "evil eye"}
        new = {"category": None, "material_type": None, "collection": None,
               "title": None, "max_price": 20000.0}
        merged = merge_search_entities(prior, new, "I want them under 20k")
        self.assertEqual(merged["collection"], "evil eye")
        self.assertEqual(merged["max_price"], 20000.0)

    def test_collection_anchored_browse_survives_category_narrowing(self):
        # "rings" as a follow-up to a collection-only browse narrows INSIDE
        # the collection, not a fresh unrelated ring search -- the
        # category-change guard doesn't protect this (there's no prior
        # category to compare against), so this needs its own carve-out.
        prior = {"collection": "evil eye"}
        new = {"category": "ring", "material_type": None, "collection": None,
               "title": None}
        merged = merge_search_entities(prior, new, "rings")
        self.assertEqual(merged["collection"], "evil eye")
        self.assertEqual(merged["category"], "ring")

    def test_collection_anchored_browse_drops_on_different_collection(self):
        # Restating a DIFFERENT collection must win, not merge oddly.
        prior = {"collection": "evil eye"}
        new = {"category": None, "material_type": None, "collection": "noor",
               "title": None}
        merged = merge_search_entities(prior, new, "show me noor collection instead")
        self.assertEqual(merged["collection"], "noor")

    def test_karat_not_inherited_on_refinement(self):
        """karat from a previous search must not carry into a new category query."""
        prior = {"category": "earring", "karat": "14KT", "material_type": "gold"}
        new = {"category": None, "material_type": None, "karat": None, "title": None,
               "max_price": 30000.0}
        merged = merge_search_entities(prior, new, "I want them under 30k")
        self.assertIsNone(merged["karat"])
        self.assertEqual(merged["category"], "earring")

    def test_compute_show_more_retries_default_when_unfiltered(self):
        """ratio=1.0 (no client filtering) returns the baseline attempt count."""
        retries = _compute_show_more_retries(1.0, 15)
        self.assertEqual(retries, 1 + _SHOW_MORE_PAGE_RETRIES)

    def test_compute_show_more_retries_adaptive_for_low_ratio(self):
        """ratio=0.01, page_size=50 (0.5 matches/page) yields more attempts than baseline."""
        retries = _compute_show_more_retries(0.01, 50)
        self.assertGreater(retries, 1 + _SHOW_MORE_PAGE_RETRIES)

    def test_compute_show_more_retries_capped_at_15(self):
        """Extremely sparse ratio is capped at 15 pages."""
        retries = _compute_show_more_retries(0.001, 50)
        self.assertEqual(retries, 15)

    def test_fallback_budget_note_preserves_price_substring(self):
        """Budget fallback note always contains the price for test and display."""
        note = _fallback_prefix_note("budget", [], {"max_price": 10000.0}, {})
        self.assertIn("No pieces found under ₹10,000", note)

    def test_fallback_budget_note_band_names_the_range(self):
        note = _fallback_prefix_note(
            "budget", [], {"min_price": 40000, "max_price": 50000}, {}
        )
        self.assertIn("₹40,000–₹50,000", note)
        self.assertNotIn("under ₹", note)

    def test_pendant_set_maps_to_category_not_title(self):
        """'pendant set' must produce category scope, not category=pendant&title=set."""
        entities = extract_entities("pendant sets in gold")
        params = entities_to_api_params(entities)
        self.assertTrue(params.get("category_id") or params.get("category") == "pendant set")
        self.assertIsNone(params.get("title"))

    def test_necklace_set_maps_to_category_not_title(self):
        """'necklace set' must produce category scope, not title=set."""
        entities = extract_entities("necklace set")
        params = entities_to_api_params(entities)
        self.assertTrue(params.get("category_id") or params.get("category") == "necklace set")
        self.assertIsNone(params.get("title"))

    def test_title_set_redundant_for_pendant_set_category(self):
        """title='set' is redundant when category is pendant_set (compound word)."""
        self.assertTrue(
            title_redundant_with_category({"title": "set", "category": "pendant_set"})
        )

    def test_filter_chain_category_passes_necklace_product(self):
        chain_product = {
            "title": "Gold Rope Chain",
            "materialType": "gold",
            "productType": {"category": {"name": "Necklaces"}},
        }
        filtered = filter_products_by_entities(
            [chain_product],
            {"category": "chain", "material_type": "gold", "title": None},
        )
        self.assertEqual(len(filtered), 1)

    def test_entities_to_api_params_sends_chain_for_chain_intent(self):
        entities = finalize_search_entities(
            {"category": "chain", "material_type": "gold"},
        )
        params = entities_to_api_params(entities)
        self.assertTrue(params.get("category_id") or params.get("category") == "chain")
        self.assertEqual(entities["category"], "necklace")

    def test_fallback_strategies_skip_title_only_for_redundant_chain_title(self):
        entities = {
            "category": "chain",
            "material_type": "gold",
            "title": "chains",
        }
        labels = [label for _ent, _note, label in _build_fallback_strategies(entities)]
        self.assertIn("drop_title", labels)
        self.assertNotIn("title_only", labels)
        drop_material = next(s for s in _build_fallback_strategies(entities) if s[2] == "drop_material")
        self.assertIsNone(drop_material[0]["title"])

    def test_clara_normalization_maps_nosewear(self):
        entities = extract_entities("gold nose pin")
        params = entities_to_api_params(entities)
        self.assertTrue(params.get("category_id") or params.get("category") == "nose wear")
        self.assertEqual(params["material_type"], "gold")

    def test_clara_normalization_omits_unsupported_anklet(self):
        entities = extract_entities("payal")
        params = entities_to_api_params(entities)
        self.assertNotIn("category", params)
        norm = normalize_entities_for_clara(entities)
        self.assertTrue(norm["unsupported_category"])

    def test_classifier_runs_for_offers_followup(self):
        # LLM-default policy: sticky offers session no longer suppresses the classifier.
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "go ahead"}},
            "user_profile": {
                "service_selected": SL.OFFERS.value,
                "chat_history": [{"role": "user", "content": "offers"}],
            },
        }
        self.assertTrue(clf.should_run(data))

    @skip_without_clara("promotions.json")
    def test_promotions_fixture_loads(self):
        path = _FIXTURES / "promotions.json"
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
        promos = body.get("data")
        self.assertIsInstance(promos, list)
        self.assertTrue(len(promos) > 0)

    @skip_without_clara("stores.json")
    def test_stores_fixture_loads(self):
        path = _FIXTURES / "stores.json"
        with open(path, encoding="utf-8") as f:
            body = json.load(f)
        stores = body["data"]["data"]
        self.assertTrue(len(stores) > 0)


class CollectionOnlyBrowseTests(unittest.TestCase):
    """"show me something in evil eye" should search directly, not funnel
    through "what are you looking for" -- the API happily returns a mixed-
    category spread for collectionId alone (live-confirmed: 34 products,
    rings/pendants/bracelets mixed, for Evil Eye Collection)."""

    def test_skips_wizard_when_collection_resolves_and_no_category(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _collection_browse_skips_wizard,
        )

        with patch(
            "kisna_chatbot.integrations.clara_filters.get_collection_id",
            return_value="fake-collection-id",
        ):
            self.assertTrue(
                _collection_browse_skips_wizard({"collection": "evil eye"})
            )

    def test_does_not_skip_when_category_already_known(self):
        # A collection AND a category together is a normal, fully-specified
        # search -- the funnel logic for missing gender/material/budget
        # still applies exactly as before.
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _collection_browse_skips_wizard,
        )

        with patch(
            "kisna_chatbot.integrations.clara_filters.get_collection_id",
            return_value="fake-collection-id",
        ):
            self.assertFalse(
                _collection_browse_skips_wizard(
                    {"collection": "evil eye", "category": "ring"}
                )
            )

    def test_does_not_skip_when_collection_unresolvable(self):
        # A guessed name that isn't a real Clara collection must still ask
        # -- never skip the funnel on an unvalidated string.
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _collection_browse_skips_wizard,
        )

        with patch(
            "kisna_chatbot.integrations.clara_filters.get_collection_id",
            return_value=None,
        ):
            self.assertFalse(
                _collection_browse_skips_wizard({"collection": "not a real name"})
            )

    def test_does_not_skip_when_no_collection_at_all(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _collection_browse_skips_wizard,
        )

        self.assertFalse(_collection_browse_skips_wizard({}))


class TypedProductTitleWizardPriorityTests(unittest.TestCase):
    """A shown product's title can collide with a short, valid wizard slot
    answer as a plain substring ("gold" inside "Emine Evil Eye Gold Ring").
    Live-confirmed: this silently opened the product card and cleared an
    in-progress wizard instead of accepting "gold" as the material answer
    it was currently asking for. An active wizard step must own the turn."""

    def test_shown_product_title_still_matches_when_wizard_inactive(self):
        # Confirms the collision is real and the matcher itself is
        # unchanged: without an active wizard, typing "gold" against a
        # shown "...Gold Ring" title correctly opens that product -- this
        # is the case _handle_typed_product_title exists for.
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _handle_typed_product_title,
        )

        data = {
            "user_profile": {
                "last_search_products": [
                    {"title": "Emine Evil Eye Gold Ring", "id": "p1"}
                ],
            }
        }
        result = _handle_typed_product_title(data, "gold")
        self.assertIsNotNone(result)
        self.assertEqual(result.get("classified_category"), "product_info")

    def test_process_keeps_wizard_owning_gold_despite_matching_shown_title(self):
        # The actual regression: process() used to run
        # _handle_typed_product_title BEFORE checking wizard state at all,
        # so "gold" at the material step matched the shown product's title
        # substring, opened that product, and cleared the wizard --
        # confirmed live. The is_wizard_active guard in process() must keep
        # an active wizard step owning this turn.
        import asyncio

        from kisna_chatbot.processors.product_search_agent_v3 import (
            ProductSearchAgentV3,
        )

        user_profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "material",
            "shopping_wizard_data": {"category": "ring", "gender": "men"},
            "last_search_products": [
                {"title": "Emine Evil Eye Gold Ring", "id": "p1"}
            ],
        }
        data = {
            "phone_number": "919999999996",
            "client_id": "kisna",
            "user_profile": user_profile,
            "messages": {"text": {"body": "gold"}},
        }

        async def _run():
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3._current_message_entities",
                new_callable=AsyncMock,
                return_value={"material_type": "gold"},
            ):
                return await ProductSearchAgentV3().process(data)

        asyncio.run(_run())

        self.assertNotEqual(data.get("classified_category"), "product_info")
        self.assertEqual(
            user_profile.get("shopping_wizard_data", {}).get("material_type"),
            "gold",
        )
        self.assertTrue(user_profile.get("shopping_wizard_active"))


if __name__ == "__main__":
    unittest.main()
