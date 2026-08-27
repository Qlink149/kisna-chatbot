"""Tests for KISNA catalogue deep-link URL builder."""

import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("KISNA_UTM_ENABLED", "false")

from kisna_chatbot.utils.catalogue_facets import CATEGORY_SLUGS
from kisna_chatbot.utils.product_formatter import build_catalogue_url

_CATALOGUE = "https://www.kisna.com/jewellery"


def _segments(entities: dict) -> list[str]:
    """Filter tokens of the built URL, [] for the bare catalogue page."""
    tail = build_catalogue_url(entities)[len(_CATALOGUE) :].lstrip("/")
    return tail.split("+") if tail else []


class CatalogueUrlTests(unittest.TestCase):
    def test_diamond_ring_budget_band(self):
        url = build_catalogue_url(
            {
                "category": "ring",
                "material_type": "diamond",
                "min_price": 30000,
                "max_price": 40000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/rings+30k-to-40k+diamond",
        )

    def test_gold_earrings_material_only(self):
        url = build_catalogue_url(
            {"category": "earring", "material_type": "gold"}
        )
        self.assertEqual(url, "https://www.kisna.com/jewellery/earrings+gold")

    def test_empty_entities_base_url(self):
        self.assertEqual(
            build_catalogue_url({}),
            "https://www.kisna.com/jewellery",
        )

    def test_rose_gold_ring_under_50k(self):
        url = build_catalogue_url(
            {
                "category": "ring",
                "material_type": "gold",
                "karat": "18KT",
                "metal_colour": "rose",
                "max_price": 50000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/rings+40k-to-50k+gold+18kt+rose",
        )

    def test_diamond_rings_under_30k(self):
        url = build_catalogue_url(
            {
                "category": "ring",
                "material_type": "diamond",
                "max_price": 30000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/rings+20k-to-30k+diamond",
        )

    def test_evil_eye_bracelet_collection(self):
        # Live-confirmed real URL bug fix: the site expects "-collection"
        # APPENDED (e.g. "Sparkle" -> sparkle-collection), not stripped.
        url = build_catalogue_url(
            {"category": "bracelet", "collection": "Evil Eye"}
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/bracelets+evil-eye-collection",
        )

    def test_collection_already_carrying_the_word_is_not_doubled(self):
        url = build_catalogue_url(
            {"category": "bracelet", "collection": "Evil Eye Collection"}
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/bracelets+evil-eye-collection",
        )

    def test_gender_men_uses_the_asymmetric_mens_token(self):
        # Live-confirmed against the real site: "mens" (with trailing s).
        url = build_catalogue_url({"category": "earring", "gender": "men"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/earrings+mens")

    def test_gender_women_uses_the_bare_women_token(self):
        # Live-confirmed against the real site: "women" (no trailing s) --
        # asymmetric with "mens", not a typo.
        url = build_catalogue_url({"category": "earring", "gender": "women"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/earrings+women")

    def test_gender_kids(self):
        url = build_catalogue_url({"category": "ring", "gender": "kids"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/rings+kids")

    def test_no_gender_produces_no_gender_segment(self):
        url = build_catalogue_url({"category": "ring", "material_type": "gold"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/rings+gold")

    def test_live_reported_case_mens_earrings_price_band(self):
        # Reproduces the exact live case that surfaced this bug
        # (+917977104875): "men's earrings 10k-20k" -- the CTA URL had no
        # gender at all before this fix.
        url = build_catalogue_url(
            {
                "category": "earring",
                "gender": "men",
                "min_price": 10000,
                "max_price": 20000,
            }
        )
        self.assertEqual(
            url,
            "https://www.kisna.com/jewellery/earrings+mens+10k-to-20k",
        )

    def test_fulfillment_ready_to_ship(self):
        url = build_catalogue_url({"category": "ring", "fulfillment": "ready"})
        self.assertEqual(
            url, "https://www.kisna.com/jewellery/rings+ready-to-ship"
        )

    def test_fulfillment_made_to_order(self):
        url = build_catalogue_url({"category": "ring", "fulfillment": "mto"})
        self.assertEqual(
            url, "https://www.kisna.com/jewellery/rings+made-to-order"
        )

    def test_no_fulfillment_produces_no_fulfillment_segment(self):
        url = build_catalogue_url({"category": "ring"})
        self.assertEqual(url, "https://www.kisna.com/jewellery/rings")

    def test_full_confirmed_real_world_combo(self):
        # Every segment from the client's live-confirmed real example URL
        # except the earring-style facet (Jhumkas/Hoops & Huggies/...),
        # deliberately out of scope for this round.
        url = build_catalogue_url(
            {
                "category": "earring",
                "gender": "men",
                "collection": "Sparkle",
                "material_type": "diamond",
                "min_price": 30000,
                "max_price": 40000,
                "fulfillment": "ready",
                "karat": "14KT",
                "metal_colour": "white",
            }
        )
        for token in (
            "earrings", "mens", "sparkle-collection", "diamond",
            "30k-to-40k", "ready-to-ship", "14kt", "white",
        ):
            self.assertIn(token, url, url)


class CategorySlugTests(unittest.TestCase):
    """The site does not pluralise: "Necklace" is `necklace`, "Rings" is `rings`."""

    def test_live_reported_necklace_case(self):
        # +919892451561, 2026-08-27: "Necklace for wife" / 35000 built
        # .../necklaces+women+30k-to-40k -- "necklaces" matches no filter.
        url = build_catalogue_url(
            {
                "category": "necklace",
                "gender": "women",
                "min_price": 30000,
                "max_price": 40000,
            }
        )
        self.assertEqual(url, f"{_CATALOGUE}/necklace+women+30k-to-40k")

    def test_every_category_maps_to_its_site_slug(self):
        expected = {
            "ring": ["rings"],
            "solitaire": ["solitaire"],
            "earring": ["earrings"],
            "necklace": ["necklace"],
            "necklace_set": ["necklace-sets"],
            "pendant": ["pendants"],
            "pendant_set": ["pendant-sets"],
            "bangle": ["bangles"],
            "bracelet": ["bracelets"],
            "mangalsutra": ["mangalsutra"],
            "mangalsutra_bracelet": ["mangalsutra-bracelets"],
            "maang_tikka": ["maang-tikka"],
            "nosewear": ["nose-wear"],
            "watchwear": ["watch-wear"],
            "chain": ["chain"],
            "souvenir": ["souvenir"],
        }
        for category, segments in expected.items():
            with self.subTest(category=category):
                self.assertEqual(_segments({"category": category}), segments)

    def test_union_category_emits_both_real_filters(self):
        self.assertEqual(
            _segments({"category": "bangle_bracelet"}), ["bangles", "bracelets"]
        )

    def test_categories_without_a_site_filter_drop_the_segment(self):
        # Anklet/hathphool/kamarband have no filter (and no Clara category);
        # "any" is the absence of one. Never guess "anklets".
        for category in ("anklet", "hathphool", "kamarband", "any", "sherwani"):
            with self.subTest(category=category):
                self.assertEqual(_segments({"category": category}), [])

    def test_spelling_variants_reaching_the_builder_still_resolve(self):
        # Different paths spell the same category differently: postback keys
        # ("nose_wear"), Clara labels ("nose wear"), plurals ("rings").
        for value, expected in (
            ("rings", ["rings"]),
            ("chains", ["chain"]),
            ("Necklaces", ["necklace"]),
            ("nose wear", ["nose-wear"]),
            ("nose_wear", ["nose-wear"]),
            ("pendant sets", ["pendant-sets"]),
            ("mangalsutra bracelets", ["mangalsutra-bracelets"]),
        ):
            with self.subTest(category=value):
                self.assertEqual(_segments({"category": value}), expected)

    def test_category_slugs_match_the_clara_filters_snapshot(self):
        """Drift guard: a catalogue rename must fail here, not in production."""
        snapshot = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "kisna_chatbot"
                / "integrations"
                / "data"
                / "clara_filters_snapshot.json"
            ).read_text(encoding="utf-8")
        )
        live = {
            option["slug"]
            for option in snapshot["global"]["payload"]["categories"]
        }
        for internal, slugs in CATEGORY_SLUGS.items():
            for slug in slugs:
                with self.subTest(internal=internal, slug=slug):
                    self.assertIn(slug, live)


class PriceBandTests(unittest.TestCase):
    """One token only -- the site applies the first price segment, drops the rest."""

    def test_every_ladder_band_has_its_site_slug(self):
        expected = [
            ((None, 10000), "under-10k"),
            ((10000, 20000), "10k-to-20k"),
            ((20000, 30000), "20k-to-30k"),
            ((30000, 40000), "30k-to-40k"),
            ((40000, 50000), "40k-to-50k"),
            ((50000, 60000), "50k-to-60k"),
            ((60000, 70000), "60k-to-70k"),
            ((70000, 80000), "70k-to-80k"),
            ((80000, 100000), "80k-to-1l"),
            ((100000, 150000), "1l-to-1.5l"),
            ((150000, 200000), "1.5l-to-2l"),
        ]
        for (low, high), slug in expected:
            with self.subTest(band=(low, high)):
                self.assertEqual(
                    _segments({"min_price": low, "max_price": high}), [slug]
                )

    def test_above_two_lakh_is_the_open_band(self):
        self.assertEqual(_segments({"min_price": 200000}), ["above-2l"])
        self.assertEqual(_segments({"min_price": 250000}), ["above-2l"])

    def test_open_ended_floor_takes_the_band_it_sits_in(self):
        self.assertEqual(_segments({"min_price": 50000}), ["50k-to-60k"])

    def test_range_spanning_bands_takes_the_largest_overlap(self):
        self.assertEqual(
            _segments({"min_price": 15000, "max_price": 35000}), ["20k-to-30k"]
        )

    def test_ties_break_upward_so_the_top_of_budget_shows(self):
        # "under 30000" covers three bands equally; 20k-to-30k is the one the
        # customer actually asked to see.
        self.assertEqual(_segments({"max_price": 30000}), ["20k-to-30k"])
        self.assertEqual(
            _segments({"min_price": 18000, "max_price": 22000}), ["20k-to-30k"]
        )

    def test_single_amount_resolves_to_its_band(self):
        self.assertEqual(
            _segments({"min_price": 50000, "max_price": 50000}), ["50k-to-60k"]
        )

    def test_no_budget_produces_no_price_segment(self):
        self.assertEqual(_segments({}), [])


class FacetWhitelistTests(unittest.TestCase):
    def test_karat_normalises_every_written_form(self):
        for value in ("18KT", "18kt", "18k", "18 karat"):
            with self.subTest(karat=value):
                self.assertEqual(_segments({"karat": value}), ["18kt"])

    def test_karat_without_a_site_filter_drops(self):
        # 22KT is real KISNA stock but the site filters 9/14/18/24 only.
        self.assertEqual(_segments({"karat": "22KT"}), [])

    def test_metal_colour_whitelist(self):
        self.assertEqual(_segments({"metal_colour": "rose"}), ["rose"])
        self.assertEqual(_segments({"metal_colour": "black"}), [])

    def test_material_whitelist(self):
        self.assertEqual(_segments({"material_type": "gemstone"}), ["gemstone"])
        self.assertEqual(_segments({"material_type": "white_gold"}), ["gold"])
        self.assertEqual(_segments({"material_type": "silver"}), [])

    def test_occasion_keeps_only_real_filters(self):
        self.assertEqual(_segments({"occasion": "engagement"}), ["engagement"])
        self.assertEqual(_segments({"occasion": "daily_wear"}), ["daily-wear"])
        for occasion in ("wedding", "anniversary", "birthday", "gift"):
            with self.subTest(occasion=occasion):
                self.assertEqual(_segments({"occasion": occasion}), [])


class CollectionSlugTests(unittest.TestCase):
    def test_bare_slug_collections_keep_no_suffix(self):
        # Six collections slug bare in Clara's own filters payload.
        self.assertEqual(_segments({"collection": "Echo"}), ["echo"])
        self.assertEqual(_segments({"collection": "Esme"}), ["esme"])
        self.assertEqual(_segments({"collection": "Tiny Tales"}), ["tiny-tales"])

    def test_unknown_text_is_not_turned_into_a_collection(self):
        # A product title riding along in entities used to emit
        # "twin-line-diamond-collection".
        self.assertEqual(_segments({"title": "Twin Line Diamond"}), [])
        self.assertEqual(_segments({"title": "bridal"}), [])

    def test_title_resolves_only_on_an_exact_collection_name(self):
        # "Sparkle" names a collection outright and still filters...
        self.assertEqual(_segments({"title": "Sparkle"}), ["sparkle-collection"])
        self.assertEqual(
            _segments({"title": "Sparkle Collection"}), ["sparkle-collection"]
        )
        # ...but a free-text near-miss must not narrow the catalogue to
        # Charms Collection on its own.
        self.assertEqual(_segments({"title": "charm"}), [])

    def test_named_collection_still_matches_loosely(self):
        # The collection entity is a deliberate choice, so it keeps fuzzy
        # matching (and its casing/spacing freedom).
        self.assertEqual(_segments({"collection": "evil eye"}), ["evil-eye-collection"])
        self.assertEqual(_segments({"collection": "charm"}), ["charms-collection"])

    def test_collection_wins_over_a_title_riding_along(self):
        self.assertEqual(
            _segments({"collection": "Sparkle", "title": "Twin Line Diamond"}),
            ["sparkle-collection"],
        )


if __name__ == "__main__":
    unittest.main()
