"""Parametrized entity extraction matrix from the audit plan."""

import os

import pytest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    entities_to_api_params,
    extract_entities,
    normalize_entities_for_clara,
)

MATRIX = [
    # Category — English
    ("ring", {"category": "ring"}),
    ("rings", {"category": "ring"}),
    ("earring", {"category": "earring"}),
    ("earrings", {"category": "earring"}),
    ("necklace", {"category": "necklace"}),
    ("bracelet", {"category": "bracelet"}),
    ("bangle", {"category": "bangle"}),
    ("pendant", {"category": "pendant"}),
    ("mangalsutra", {"category": "mangalsutra"}),
    ("nose pin", {"category": "nosewear"}),
    ("watch charm", {"category": "watchwear"}),
    # Category — Hindi / Hinglish
    ("anguthi", {"category": "ring"}),
    ("angoothi dikhao", {"category": "ring"}),
    ("jhumka", {"category": "earring"}),
    ("jhumki", {"category": "earring"}),
    ("kaan ki bali", {"category": "earring"}),
    ("ear cuff", {"category": "earring"}),
    ("earcuff", {"category": "earring"}),
    ("haar", {"category": "necklace"}),
    ("choker", {"category": "necklace"}),
    ("latkan", {"category": "pendant"}),
    ("kara", {"category": "bangle"}),
    ("kadi", {"category": "bracelet"}),
    ("tanmaniya", {"category": "mangalsutra"}),
    ("nosepin", {"category": "nosewear"}),
    # Unsupported categories (extract + flag)
    ("anklet", {"category": "anklet", "unsupported_category": True}),
    ("payal", {"category": "anklet", "unsupported_category": True}),
    ("pajeb", {"category": "anklet", "unsupported_category": True}),
    ("tikka", {"category": "maang_tikka", "unsupported_category": True}),
    ("maang tikka", {"category": "maang_tikka", "unsupported_category": True}),
    # Material — English
    ("gold ring", {"category": "ring", "material_type": "gold"}),
    ("diamond earrings", {"category": "earring", "material_type": "diamond"}),
    ("ruby pendant", {"category": "pendant", "material_type": "gemstone"}),
    ("silver chain", {"material_type": "silver", "unsupported_material": True}),
    ("platinum band", {"material_type": "platinum", "unsupported_material": True}),
    ("pearl necklace", {"category": "necklace", "material_type": "pearl", "unsupported_material": True}),
    # Material — Hindi / Hinglish
    ("sone ki anguthi", {"category": "ring", "material_type": "gold"}),
    ("heere ki bali", {"category": "earring", "material_type": "diamond"}),
    ("heere ki jhumki", {"category": "earring", "material_type": "diamond"}),
    ("chandi ka chain", {"category": "necklace", "material_type": "silver", "unsupported_material": True}),
    ("22 karat gold ring", {"category": "ring", "material_type": "gold"}),
    ("18KT necklace", {"category": "necklace", "material_type": "gold"}),
    ("white gold ring", {"category": "ring", "material_type": "white_gold", "metal_colour": "white"}),
    ("rose gold earrings", {"category": "earring", "material_type": "rose_gold", "metal_colour": "rose"}),
    ("rose gold rings", {"category": "ring", "material_type": "rose_gold", "metal_colour": "rose"}),
    # Price — English
    ("earrings under 30k", {"category": "earring", "max_price": 30000}),
    ("rings below 10000", {"category": "ring", "max_price": 10000}),
    ("show me rings between 0-10,000", {"category": "ring", "max_price": 10000}),
    ("rings between 0 and 10000", {"category": "ring", "max_price": 10000}),
    ("gold necklace 20k to 50k", {"category": "necklace", "material_type": "gold", "min_price": 20000, "max_price": 50000}),
    ("50k budget", {"max_price": 50000}),
    ("budget 50k", {"max_price": 50000}),
    ("₹50,000", {"max_price": 50000}),
    ("50,000/-", {"max_price": 50000}),
    ("1.5 lakh", {"max_price": 150000}),
    ("around 50000", {"min_price": 40000, "max_price": 60000}),
    ("approximately 1 lakh", {"min_price": 80000, "max_price": 120000}),
    # Price — Hindi
    ("ek lakh tak", {"max_price": 100000}),
    ("das hazaar tak rings", {"category": "ring", "max_price": 10000}),
    ("dedh lakh budget", {"max_price": 150000}),
    ("2.5 lakh se kam", {"max_price": 250000}),
    ("above 5 lakh", {"min_price": 500000}),
    ("above 50k", {"min_price": 50000}),
    ("30k se upar", {"min_price": 30000}),
    ("30k se zyada", {"min_price": 30000}),
    ("minimum 20000", {"min_price": 20000}),
    ("at least 25k", {"min_price": 25000}),
    ("50 hazaar se upar", {"min_price": 50000}),
    ("show me something above 5 lac", {"min_price": 500000}),
    ("gold rings above 50k", {"category": "ring", "material_type": "gold", "min_price": 50000}),
    ("minimum 20000 ka ring", {"category": "ring", "min_price": 20000}),
    # Price guards
    ("budget 50", {"max_price": None}),
    ("1234567890", {"max_price": None, "category": None}),
    # Combined
    ("diamond ring dikhao", {"category": "ring", "material_type": "diamond"}),
    ("sone ki payal 10000 tak", {"category": "anklet", "material_type": "gold", "max_price": 10000, "unsupported_category": True}),
    ("Evil Eye bracelet", {"category": "bracelet", "title": "evil eye"}),
    ("gold rings under 50k", {"category": "ring", "material_type": "gold", "max_price": 50000}),
    # Title / collections
    ("show rivaah collection", {"title": "rivaah"}),
    ("Bloom earrings", {"category": "earring", "title": "bloom"}),
    ("show me Rosette", {"title": "rosette"}),
    ("elysia ring", {"category": "ring", "title": "elysia"}),
    ("maggio pendant", {"category": "pendant", "title": "maggio"}),
    # Multi-category
    (
        "rings aur earrings",
        {
            "category": "ring",
            "categories": ["ring", "earring"],
            "multi_category": True,
            "secondary_category": "earring",
        },
    ),
    (
        "gold ring and diamond earrings",
        {
            "category": "ring",
            "categories": ["ring", "earring"],
            "multi_category": True,
            "material_type": "diamond",
        },
    ),
    # Ambiguous sets
    ("kundan set", {"category": None}),
    ("wedding set", {"category": None}),
    ("temple jewellery", {"category": None}),
    ("ring set", {"category": "ring"}),
    # Edge — substring bug regression
    ("I want all the rings below 10,000", {"category": "ring", "max_price": 10000}),
    ("engagement ring", {"category": "ring"}),
    ("cocktail ring", {"category": "ring"}),
    ("solitaire ring", {"category": "ring", "material_type": "diamond"}),
    (
        "Send me diamond rings between 20000-50000",
        {
            "category": "ring",
            "material_type": "diamond",
            "min_price": 20000,
            "max_price": 50000,
            "title": None,
        },
    ),
]


def _check_row(query: str, expected: dict) -> tuple[bool, dict]:
    actual = extract_entities(query)
    ok = True
    for key, value in expected.items():
        if actual.get(key) != value:
            ok = False
            break
    return ok, actual


@pytest.mark.parametrize("query,expected", MATRIX)
def test_entity_matrix_row(query: str, expected: dict) -> None:
    ok, actual = _check_row(query, expected)
    assert ok, f"query={query!r} expected={expected} actual={actual}"


class TestClaraNormalization:
    def test_payal_omits_category_from_api(self):
        entities = extract_entities("payal under 10000")
        params = entities_to_api_params(entities)
        assert "category" not in params
        assert params.get("max_price") == 10000
        assert params.get("min_price") == 0

    def test_nosewear_maps_to_clara_category(self):
        entities = extract_entities("nose pin gold")
        norm = normalize_entities_for_clara(entities)
        assert norm["clara_category"] == "nose wear"
        params = entities_to_api_params(entities)
        assert params["category"] == "nose wear"

    def test_white_gold_maps_to_gold(self):
        entities = extract_entities("white gold ring")
        params = entities_to_api_params(entities)
        assert params["material_type"] == "gold"
        assert params["category"] == "ring"

    def test_silver_omits_material_from_api(self):
        entities = extract_entities("chandi chain")
        params = entities_to_api_params(entities)
        assert "material_type" not in params
        assert entities["unsupported_material"] is True

    def test_unsupported_category_note(self):
        entities = extract_entities("payal")
        norm = normalize_entities_for_clara(entities)
        assert norm.get("_clara_search_note")

    def test_zero_lower_bound_range_sends_min_price_zero(self):
        entities = extract_entities("show me rings between 0-10,000")
        params = entities_to_api_params(entities)
        assert params.get("category") == "ring"
        assert params.get("max_price") == 10000
        assert params.get("min_price") == 0

    def test_max_price_only_sends_min_price_zero(self):
        from kisna_chatbot.integrations.clara_api import build_products_query_params

        params = entities_to_api_params({"max_price": 10000, "min_price": None})
        assert params["min_price"] == 0
        assert params["max_price"] == 10000
        query = build_products_query_params(**params)
        assert query["minPrice"] == 0
        assert query["maxPrice"] == 10000

    def test_gold_chains_no_spurious_title(self):
        entities = extract_entities("Show me gold Chains")
        assert entities.get("title") is None
        assert entities.get("material_type") == "gold"

    def test_gold_chains_plural_extracts_necklace_category(self):
        entities = extract_entities("gold chains")
        assert entities.get("category") == "necklace"
        assert entities.get("material_type") == "gold"
        assert entities.get("title") is None

    def test_capitalized_product_name_not_regex_title(self):
        entities = extract_entities("Show me Nitara ring")
        assert entities.get("title") is None
        assert entities.get("category") == "ring"
