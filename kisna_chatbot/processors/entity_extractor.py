"""
Rule-based entity extraction from Hindi/English/Hinglish product search queries.
"""

import json
import re
from typing import Any

from kisna_chatbot.integrations.clara_api import (
    CLIENT_SIDE_FILTER_PAGE_SIZE,
    DEFAULT_API_PAGE_SIZE,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.price_calculator import resolve_product_prices

_CLIENT_FILTER_KEYS = (
    "metal_colour",
    "karat",
    "size",
    "collection",
    "gender",
    "occasion",
    "style",
)

_MIN_EXTRA_FILTER_RESULTS = 3

_EXTRA_RELAXATION_ORDER = (
    "size",
    "karat",
    "metal_colour",
    "collection",
    "occasion",
    "gender",
    "style",
)

_OCCASION_TAG_TERMS: dict[str, tuple[str, ...]] = {
    "wedding": ("wedding", "shaadi", "bridal"),
    "anniversary": ("anniversary",),
    "birthday": ("birthday",),
    "daily_wear": ("daily wear", "casual", "everyday"),
    "engagement": ("engagement",),
    "gift": ("gift", "uphaar"),
}

_CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "ring": [
        "ring",
        "rings",
        "anguthi",
        "angoothi",
        "angooti",
        "band ring",
        "solitaire ring",
        "cocktail ring",
        "engagement ring",
        "band ring",
    ],
    "earring": [
        "earring",
        "earrings",
        "ear cuff",
        "earcuff",
        "bali",
        "jhumka",
        "jhumki",
        "jhhumka",
        "tops",
        "studs",
        "stud",
        "hoops",
        "hoop",
        "drops",
        "danglers",
        "dangler",
        "sui dhaga",
        "kaan ki bali",
    ],
    "necklace": [
        "necklace",
        "haar",
        "mala",
        "chain",
        "chains",
        "choker",
        "rani haar",
        "layered necklace",
        "long chain",
        "short chain",
    ],
    "bracelet": ["bracelet", "kada", "kadi", "bolo"],
    "bangle": ["bangle", "bangles", "kangan", "chudi", "churi", "kara"],
    "pendant": ["pendant", "locket", "charm", "latkan"],
    "pendant_set": ["pendant set", "pendant sets"],
    "necklace_set": ["necklace set", "necklace sets"],
    "mangalsutra": ["mangalsutra", "mangal sutra", "tanmaniya"],
    "mangalsutra_bracelet": ["mangalsutra bracelet", "mangalsutra bracelets", "tanmaniya bracelet"],
    "nosewear": ["nose pin", "nosepin", "nose stud", "nath", "nose ring"],
    "watchwear": ["watch pin", "watch charm", "watch wear", "watch"],
    "anklet": ["anklet", "payal", "pajeb", "paayal"],
    "maang_tikka": ["maang tikka", "maangtika", "maang_tikka", "tikka", "tika", "bor"],
    "hathphool": ["hathphool", "hath phool"],
    "kamarband": ["kamarband", "kamar band"],
}

_CLARA_UNSUPPORTED_CATEGORIES = frozenset({"anklet", "hathphool", "kamarband"})

# Internal canonical category → exact Clara API query string (from audit_clara_categories.py).
CATEGORY_NORMALIZATION_MAP: dict[str, str | None] = {
    "ring": "ring",
    "solitaire": "solitaire",
    "earring": "earring",
    "necklace": "necklace",
    "necklace_set": "necklace set",
    "pendant": "pendant",
    "pendant_set": "pendant set",
    "bangle": "bangle",
    "bracelet": "bracelet",
    "bangle_bracelet": None,
    "mangalsutra": "mangalsutra",
    "mangalsutra_bracelet": "mangalsutra bracelet",
    "maang_tikka": "maang tikka",
    "nosewear": "nose wear",
    "nose_wear": "nose wear",
    "watchwear": "watch wear",
    "watch_wear": "watch wear",
    "chain": "chain",
    "anklet": None,
    "any": None,
}

# Backward-compatible alias for tests and internal references.
_CLARA_CATEGORY_MAP = CATEGORY_NORMALIZATION_MAP

_AMBIGUOUS_CATEGORY_PHRASES = (
    "kundan set",
    "wedding set",
    "temple jewellery",
    "temple jewelry",
)

_MATERIAL_SYNONYMS: dict[str, list[str]] = {
    "gold": [
        "gold",
        "sona",
        "sone",
        "sone ka",
        "sone ki",
        "soni",
        "18k",
        "14k",
        "22k",
        "18kt",
        "14kt",
        "22kt",
        "18 karat",
        "22 karat",
        "14 karat",
        "hallmark",
        "bis",
        "yellow gold",
    ],
    "white_gold": ["white gold", "safed sona"],
    "rose_gold": ["rose gold", "pink gold"],
    "diamond": [
        "diamond",
        "heera",
        "heere",
        "heere ka",
        "heere ki",
        "heeron ki",
        "solitaire",
        "diamond studded",
        "brilliant cut",
    ],
    "gemstone": [
        "gemstone",
        "ruby",
        "emerald",
        "sapphire",
        "panna",
        "manik",
        "neelam",
        "pukhraj",
    ],
    "silver": ["silver", "chandi", "chandi ka", "sterling", "925"],
    "platinum": ["platinum"],
    "pearl": ["pearl", "moti"],
}

_CLARA_UNSUPPORTED_MATERIALS = frozenset({"silver", "platinum", "pearl"})

_CLARA_MATERIAL_MAP: dict[str, str] = {
    "white_gold": "gold",
    "rose_gold": "gold",
}

_KISNA_COLLECTIONS = [
    "evil eye",
    "rivaah",
    "elysia",
    "maggio",
    "rosette",
    "bloom",
    "solitaire",
    "flora",
    "celestial",
    "iris",
    "aadya",
    "tanishta",
]

_TITLE_STOP_WORDS = frozenset(
    {
        "show",
        "send",
        "dikhao",
        "please",
        "me",
        "want",
        "need",
        "looking",
        "look",
        "for",
        "buy",
        "get",
        "find",
        "give",
        "bring",
        "display",
        "suggest",
        "recommend",
        "search",
        "fetch",
        "share",
        "under",
        "above",
        "between",
        "from",
        "to",
        "the",
        "a",
        "an",
        "collection",
        "our",
        "your",
        "some",
        "any",
        "all",
        "what",
        "how",
        "why",
        "when",
        "where",
        "who",
        "which",
        "is",
        "are",
        "kisna",
        "jewellery",
        "jewelry",
    }
)

_COMMAND_PREFIXES: tuple[str, ...] = (
    "please show",
    "can you show",
    "i'm looking for",
    "im looking for",
    "send me",
    "show me",
    "i want",
    "i need",
    "give me",
    "find me",
    "get me",
    "suggest me",
    "looking for",
    "searching for",
)

_HINDI_NUMBER_PHRASES: list[tuple[str, str]] = [
    ("dedh lakh", "150000"),
    ("dhai lakh", "250000"),
    ("saadhe char lakh", "450000"),
    ("saadhe teen lakh", "350000"),
    ("ek lakh", "100000"),
    ("do lakh", "200000"),
    ("teen lakh", "300000"),
    ("char lakh", "400000"),
    ("paanch lakh", "500000"),
    ("das hazaar", "10000"),
    ("paanch hazaar", "5000"),
    ("ek hazaar", "1000"),
    ("do hazaar", "2000"),
    ("teen hazaar", "3000"),
    ("char hazaar", "4000"),
    ("saat hazaar", "7000"),
    ("aath hazaar", "8000"),
    ("nau hazaar", "9000"),
]

_CITIES = [
    "mumbai",
    "delhi",
    "bangalore",
    "bengaluru",
    "chennai",
    "hyderabad",
    "kolkata",
    "pune",
    "ahmedabad",
    "jaipur",
    "surat",
    "lucknow",
    "nagpur",
    "indore",
    "bhopal",
    "kochi",
    "chandigarh",
]

_MULTI_CAT_SEP_RE = re.compile(
    r"\b(aur|and|or|ya|bhi|also|&|\+)\b",
    re.I,
)

_PINCODE_RE = re.compile(r"\b([1-9]\d{5})\b")
_PINCODE_ONLY_RE = re.compile(r"^\s*([1-9]\d{5})\s*$")
_REPEATED_CHAR_RE = re.compile(r"^(.)\1{3,}$")
_KEYBOARD_MASH_RE = re.compile(
    r"\b(asdf|qwerty|zxcv|qwer|hjkl|jkl)\b|^(asdf|qwerty|zxcv)+$",
    re.I,
)
_PRICE_HINT_RE = re.compile(
    r"\b(under|below|upto|up to|budget|within|above|over|tak|kam|k\b|lakh|lac|₹|rs\.?|rupees?|price|around|approximately|roughly)\b",
    re.I,
)
_STRONG_PRICE_HINT_RE = re.compile(
    r"\b(under|below|upto|up to|less than|maximum|max|minimum|within|tak|se kam|ke andar|ke neeche|"
    r"above|over|more than|min|at\s*least|atleast|se\s*zyada|se\s*upar|ke\s*upar|"
    r"between|from|around|approximately|roughly|hazaar)\b|₹",
    re.I,
)
_SHORT_AFFIRMATION_RE = re.compile(
    r"^(yes|yeah|yep|ok|okay|sure|go ahead|haan|ha|ji|theek|thik)$",
    re.I,
)

# Price patterns — order matters: range first, then around, then max, then min
_RANGE_PATTERNS = [
    re.compile(
        r"(?:between|from)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:and|to|-)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:to|-)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*se\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*tak",
        re.I,
    ),
]

_AROUND_PATTERNS = [
    re.compile(
        r"(?:around|approximately|roughly)\s*₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
]

# Hard ceiling / floor direction words (do NOT apply ±10% single-price band).
_MAX_DIRECTION_RE = re.compile(
    r"\b(under|below|upto|up to|within|tak|se kam|ke andar|ke neeche|less than|max|maximum)\b",
    re.I,
)

_MIN_DIRECTION_RE = re.compile(
    r"\b(above|over|more than|minimum|min|at\s*least|atleast|se\s*zyada|se\s*upar|ke\s*upar)\b",
    re.I,
)

# "of price 50000" / "price 50000" / "price of 50k" → ±10% band (not hard max).
_SINGLE_TARGET_PRICE_PATTERNS = [
    re.compile(
        r"(?:(?:of|at|for)\s+)?price\s*(?:of\s*|is\s*|at\s*|around\s*)?"
        r"₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
]

_SINGLE_TARGET_HINT_RE = re.compile(
    r"\b(price|budget|around|approximately|roughly)\b|"
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:k|lakh|lac|hazaar)?\s*ka\b",
    re.I,
)

_EXPLICIT_MAX_PATTERNS = [
    re.compile(
        r"(?:under|below|upto|up to|max|maximum|within|less than|kam|se kam)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?\s*(?:tak|se kam|ke andar|ke neeche)",
        re.I,
    ),
    re.compile(
        r"within\s*(?:my\s*)?budget\s*(?:of\s*)?₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
    re.compile(
        r"₹\s*([\d,]+(?:\.\d+)?)\s*/?-?\b",
        re.I,
    ),
    re.compile(
        r"([\d,]+(?:\.\d+)?)/-",
        re.I,
    ),
]

# Plain "budget X" / "X budget" → single-price ±10% band (not a hard max).
_SINGLE_BUDGET_PATTERNS = [
    re.compile(
        r"budget\s*(?:of\s*)?₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
    re.compile(
        r"([\d,]+(?:\.\d+)?)\s+budget\b",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)\b\s*budget",
        re.I,
    ),
    re.compile(
        r"budget\s+([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?\s*hai\b",
        re.I,
    ),
]

_GREEDY_MAX_CATCHALL = re.compile(
    r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)\b",
    re.I,
)

_MIN_PATTERNS = [
    re.compile(
        r"(?:above|over|more than|minimum|min|at\s*least|atleast)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?\s*(?:se\s*zyada|se\s*upar|ke\s*upar|\+)",
        re.I,
    ),
    re.compile(
        r"(\d+[\d,]*)\s*(k|hazaar|lakh|lac)\b\s*se\s*upar",
        re.I,
    ),
    re.compile(
        r"(\d+[\d,]*)\s*(k|hazaar|lakh|lac)\b\s*se\s*zyada",
        re.I,
    ),
    re.compile(
        r"minimum\s+(?:₹\s*)?([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
    re.compile(
        r"at\s*least\s+(?:₹\s*)?([\d,]+(?:\.\d+)?)(?:\s*(k|lakh|lac|hazaar)\b)?",
        re.I,
    ),
    re.compile(
        r"(\d+(?:\.\d+)?)\s*hazaar\s*se\s*upar",
        re.I,
    ),
]

_HINDI_COUNT_WORDS: dict[str, int] = {
    "ek": 1,
    "do": 2,
    "teen": 3,
    "char": 4,
    "paanch": 5,
    "chhe": 6,
    "saat": 7,
    "aath": 8,
    "nau": 9,
    "das": 10,
    "bees": 20,
    "tees": 30,
    "chalis": 40,
    "pachaas": 50,
    "sau": 100,
}

_HAZAAR_STANDALONE_RE = re.compile(
    r"\b("
    r"ek|do|teen|char|paanch|chhe|saat|aath|nau|das|"
    r"bees|tees|chalis|pachaas|sau|\d+(?:\.\d+)?"
    r")?\s*hazaar\b",
    re.I,
)

_BUDGET_ONLY_RE = re.compile(
    r"^\s*budget\s+([\d,]+(?:\.\d+)?)\s*$",
    re.I,
)


def _normalize_text(text: str) -> str:
    return text.lower().strip()


def _strip_command_prefix(text: str) -> str:
    """Remove common imperative sentence starters before title extraction."""
    result = (text or "").strip()
    lower = result.lower()
    changed = True
    while changed:
        changed = False
        for prefix in _COMMAND_PREFIXES:
            if lower.startswith(prefix):
                result = result[len(prefix) :].strip()
                lower = result.lower()
                changed = True
                break
    return result


def _singularize_english(token: str) -> str:
    t = (token or "").strip().lower()
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("es") and len(t) > 3:
        return t[:-2]
    if t.endswith("s") and len(t) > 2 and not t.endswith("ss"):
        return t[:-1]
    return t


def _title_echoes_term(title: str, term: str) -> bool:
    title_l = title.strip().lower()
    term_l = term.strip().lower()
    if title_l == term_l:
        return True
    return (
        _singularize_english(title_l) == term_l
        or title_l == _singularize_english(term_l)
        or _singularize_english(title_l) == _singularize_english(term_l)
    )


def _category_synonym_terms(category: str | None) -> set[str]:
    if not category:
        return set()
    terms = {str(category).lower()}
    for syn in _CATEGORY_SYNONYMS.get(category, []):
        terms.add(syn.lower())
    return terms


def title_redundant_with_category(entities: dict[str, Any]) -> bool:
    """True when title repeats category/material words (e.g. title=chains, category=chain)."""
    title = entities.get("title")
    if not isinstance(title, str) or not title.strip():
        return False

    title_l = title.strip().lower()

    category = entities.get("category")
    if category:
        for term in _category_synonym_terms(str(category)):
            if _title_echoes_term(title, term):
                return True
        # For compound categories like pendant_set, also treat any component word
        # as redundant (e.g. title="set" when category="pendant_set").
        cat_words = str(category).replace("_", " ").lower().split()
        if len(cat_words) > 1 and title_l in cat_words:
            return True

    material = entities.get("material_type")
    if material:
        for syn in _MATERIAL_SYNONYMS.get(str(material), [str(material)]):
            if _title_echoes_term(title, syn):
                return True

    return False


def sanitize_search_entities(entities: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with invalid or redundant search titles cleared."""
    out = dict(entities or {})
    title = out.get("title")
    if isinstance(title, str) and title.strip().lower() in _TITLE_STOP_WORDS:
        out["title"] = None
    if title_redundant_with_category(out):
        out["title"] = None
    return out


def sanitize_invalid_title(entities: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with command-verb and redundant titles cleared."""
    return sanitize_search_entities(entities)


_INTERNAL_CATEGORY_ALIASES: dict[str, str] = {
    "chain": "necklace",
    "nose_ring": "nosewear",
    "nose_wear": "nosewear",
    "watch_wear": "watchwear",
}

_CLARA_CATEGORY_OVERRIDE_FROM: dict[str, str] = {
    "chain": "chain",
}

_REGEX_FILL_FIELDS = (
    "min_price",
    "max_price",
    "pincode",
    "city",
)

_LLM_ONLY_FIELDS = (
    "title",
    "collection",
    "occasion",
    "style",
    "gender",
    "karat",
    "size",
    "action",
)

_SEMANTIC_MERGE_FIELDS = (
    "category",
    "material_type",
    "metal_colour",
    "categories",
    "multi_category",
    "secondary_category",
)


def is_spurious_title(title: str | None) -> bool:
    """True when a title token should not drive routing or search (stop words, etc.)."""
    if not title or not isinstance(title, str):
        return False
    if title.strip().lower() in _TITLE_STOP_WORDS:
        return True
    return title_redundant_with_category({"title": title, "category": None})


def normalize_internal_category(entities: dict[str, Any]) -> dict[str, Any]:
    """Map LLM/API category labels to internal canonical values for client filtering."""
    out = dict(entities or {})
    category = out.get("category")
    if not isinstance(category, str) or not category.strip():
        return out

    raw = category.strip().lower()
    if raw in _CLARA_CATEGORY_OVERRIDE_FROM:
        out["clara_category_override"] = _CLARA_CATEGORY_OVERRIDE_FROM[raw]
    if raw in _INTERNAL_CATEGORY_ALIASES:
        out["category"] = _INTERNAL_CATEGORY_ALIASES[raw]
    return out


def _log_entity_merge_conflicts(
    *,
    query: str | None,
    regex_entities: dict[str, Any] | None,
    llm_entities: dict[str, Any] | None,
) -> None:
    if not query or not regex_entities or not llm_entities:
        return
    for field in ("category", "material_type", "title"):
        regex_val = regex_entities.get(field)
        llm_val = llm_entities.get(field)
        if regex_val is None or llm_val is None or regex_val == llm_val:
            continue
        log_fn = logger.info if field == "title" else logger.debug
        log_fn(
            "entity_merge_conflict",
            extra={
                "query": query,
                "field": field,
                "regex_value": regex_val,
                "llm_value": llm_val,
            },
        )


_CHAIN_CATEGORY_RE = re.compile(r"\bchains?\b", re.I)


def supplement_semantic_entities_from_query(
    entities: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    """
    Last-resort fill when LLM missed obvious category/material in the query text.
    Does not set prices (regex + LLM own structured fields).

    Also promotes a base LLM category to its composite form when the regex
    extractor finds a longer composite match (e.g. 'pendant' -> 'pendant_set'
    when the query contains 'pendant set'). This corrects the known LLM blind
    spot where composite nouns are collapsed to their base token because the
    prompt enum previously lacked the composite entries.
    """
    out = dict(entities or {})
    if not (query or "").strip():
        return out

    normalized = _normalize_text(query)

    # Pairs where base category must be promoted to composite when regex confirms it.
    # Key = what LLM might incorrectly output; value = correct composite key.
    _COMPOSITE_UPGRADES: dict[str, str] = {
        "pendant":     "pendant_set",
        "necklace":    "necklace_set",
        "mangalsutra": "mangalsutra_bracelet",
    }

    if not out.get("category"):
        if _CHAIN_CATEGORY_RE.search(normalized):
            out["category"] = "chain"
        else:
            categories = _extract_categories(normalized)
            if len(categories) == 1:
                out["category"] = categories[0]
            elif len(categories) > 1:
                out["categories"] = categories
                out["multi_category"] = True
    else:
        # Safety net: upgrade base category -> composite when regex finds it.
        current = out["category"]
        target_composite = _COMPOSITE_UPGRADES.get(current)
        if target_composite:
            regex_cats = _extract_categories(normalized)
            if regex_cats and regex_cats[0] == target_composite:
                out["category"] = target_composite
                logger.info(
                    "composite_category_upgrade",
                    extra={"query": query, "from": current, "to": target_composite},
                )

    if not out.get("material_type"):
        material = _match_synonym(normalized, _MATERIAL_SYNONYMS)
        if material:
            out["material_type"] = material

    return out


def merge_entity_llm_supplement(existing: dict, extracted: dict) -> dict:
    """Classifier entities win; dedicated entity LLM fills null gaps."""
    out = dict(existing or {})
    for key, val in (extracted or {}).items():
        if val is not None and out.get(key) is None:
            out[key] = val
    return out


def _clara_multi_categories_for_entities(entities: dict[str, Any]) -> list[str] | None:
    """Return Clara category strings when a single API call is insufficient."""
    category = entities.get("category")
    categories = entities.get("categories") or []
    if category == "bangle_bracelet" or (
        entities.get("multi_category")
        and set(categories) >= {"bangle", "bracelet"}
    ):
        bangle = CATEGORY_NORMALIZATION_MAP.get("bangle")
        bracelet = CATEGORY_NORMALIZATION_MAP.get("bracelet")
        if bangle and bracelet:
            return [bangle, bracelet]
    return None


def has_clara_search_scope(
    api_params: dict[str, Any], entities: dict[str, Any] | None = None
) -> bool:
    """Clara product search requires category or title — material/price alone errors."""
    if entities and _clara_multi_categories_for_entities(entities):
        return True
    category = api_params.get("category")
    title = api_params.get("title")
    if category is not None and str(category).strip():
        return True
    if title is not None and str(title).strip():
        return True
    return False


def finalize_search_entities(
    entities: dict[str, Any],
    *,
    query: str | None = None,
    regex_entities: dict[str, Any] | None = None,
    llm_entities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single validation gate: sanitize, normalize categories, optional conflict logging."""
    out = sanitize_search_entities(entities)
    if query:
        before_cat = out.get("category")
        out = supplement_semantic_entities_from_query(out, query)
        if not before_cat and out.get("category"):
            logger.info(
                "Supplemented missing category from query",
                extra={"query": query, "category": out.get("category")},
            )
    out = normalize_internal_category(out)
    out = normalize_price_entities(query, out)
    _log_entity_merge_conflicts(
        query=query,
        regex_entities=regex_entities,
        llm_entities=llm_entities,
    )
    category = out.get("category")
    if category in _CLARA_UNSUPPORTED_CATEGORIES:
        out["unsupported_category"] = True
    material = out.get("material_type")
    if material in _CLARA_UNSUPPORTED_MATERIALS:
        out["unsupported_material"] = True
    return out


def normalize_price_entities(
    query: str | None,
    entities: dict[str, Any],
) -> dict[str, Any]:
    """
    Deterministic price gate: single-target amounts become a ±10% band.

    Keeps hard under/above and explicit unequal ranges unchanged.
    Snaps LLM exact matches (min == max) and undirected max-only targets.
    """
    out = dict(entities or {})
    min_p = out.get("min_price")
    max_p = out.get("max_price")
    if min_p is None and max_p is None:
        return out

    text = _normalize_text(query) if query else ""
    if text and (_MAX_DIRECTION_RE.search(text) or _MIN_DIRECTION_RE.search(text)):
        return out

    try:
        min_f = float(min_p) if min_p is not None else None
        max_f = float(max_p) if max_p is not None else None
    except (TypeError, ValueError):
        return out

    target: float | None = None
    if min_f is not None and max_f is not None:
        if min_f == max_f:
            target = min_f
        elif (
            text
            and not _RANGE_INDICATOR_RE.search(text)
            and max_f > 0
            and 0.85 <= min_f / max_f < 1.0
        ):
            # LLM emitted a narrow asymmetric band for a single stated amount
            # (e.g. 22500–25000 for "25 hazaar ka") — the user gave ONE number,
            # so recompute the symmetric band around it. Genuine ranges always
            # carry a range word (to/se/tak/से/तक/dash) and are left unchanged.
            target = max_f
    elif max_f is not None and min_f is None:
        if text and (
            _SINGLE_TARGET_HINT_RE.search(text) or re.search(r"\d", text)
        ):
            target = max_f
    elif min_f is not None and max_f is None:
        if text and _SINGLE_TARGET_HINT_RE.search(text):
            target = min_f

    if target is not None and target > 0:
        lo, hi = _snap_single_price_to_band(target)
        out["min_price"] = lo
        out["max_price"] = hi
    return out


def _preprocess_hindi_numbers(text: str) -> str:
    result = text
    for phrase, digits in sorted(_HINDI_NUMBER_PHRASES, key=lambda x: len(x[0]), reverse=True):
        result = re.sub(rf"\b{re.escape(phrase)}\b", digits, result)
    return result


def _synonym_pattern(syn: str) -> re.Pattern[str]:
    if " " in syn:
        return re.compile(rf"(?<!\w){re.escape(syn)}(?!\w)", re.I)
    return re.compile(rf"\b{re.escape(syn)}\b", re.I)


def _synonym_in_text(text: str, syn: str) -> bool:
    return bool(_synonym_pattern(syn).search(text))


def _iter_synonym_matches(text: str, synonyms_map: dict[str, list[str]]):
    """Yield (start_pos, synonym_length, api_value) sorted by longest synonym first."""
    matches: list[tuple[int, int, str]] = []
    for api_value, synonyms in synonyms_map.items():
        sorted_syns = sorted(synonyms, key=len, reverse=True)
        for syn in sorted_syns:
            pattern = _synonym_pattern(syn)
            m = pattern.search(text)
            if m:
                matches.append((m.start(), len(syn), api_value))
                break
    matches.sort(key=lambda item: (item[0], -item[1]))
    return matches


def _match_synonym(text: str, synonyms_map: dict[str, list[str]]) -> str | None:
    """Return API value for longest matching synonym (single best match)."""
    best: tuple[int, str] | None = None
    for api_value, synonyms in synonyms_map.items():
        sorted_syns = sorted(synonyms, key=len, reverse=True)
        for syn in sorted_syns:
            if _synonym_in_text(text, syn):
                length = len(syn)
                if best is None or length > best[0]:
                    best = (length, api_value)
                break
    return best[1] if best else None


def _has_ambiguous_category_phrase(text: str) -> bool:
    return any(phrase in text for phrase in _AMBIGUOUS_CATEGORY_PHRASES)


def _extract_categories(text: str) -> list[str]:
    if _has_ambiguous_category_phrase(text):
        return []

    seen: set[str] = set()
    ordered: list[str] = []
    consumed_end: int = -1
    # _iter_synonym_matches yields (start, length, api_value) sorted by (start, -length)
    # so the longest match at each position comes first.
    for start, length, api_value in _iter_synonym_matches(text, _CATEGORY_SYNONYMS):
        if api_value in seen:
            continue
        # Skip a shorter synonym that falls inside an already-consumed span —
        # e.g. "pendant" must not shadow "pendant set" at the same start position.
        if start < consumed_end:
            continue
        seen.add(api_value)
        ordered.append((start, api_value))
        consumed_end = start + length

    ordered.sort(key=lambda item: item[0])
    return [value for _start, value in ordered]


def _parse_amount(num_str: str, suffix: str | None) -> float | None:
    try:
        value = float(num_str.replace(",", ""))
    except ValueError:
        return None
    if suffix:
        s = suffix.lower()
        if s == "k":
            value *= 1000
        elif s == "hazaar":
            value *= 1000
        elif s in ("lakh", "lac"):
            value *= 100000
    return value


def _amount_has_scale(suffix: str | None, amount: float) -> bool:
    if suffix:
        return True
    return amount >= 1000


def _reject_ambiguous_budget(text: str, amount: float, suffix: str | None) -> bool:
    if _BUDGET_ONLY_RE.match(text.strip()):
        return not _amount_has_scale(suffix, amount)
    if suffix:
        return False
    if amount >= 1000:
        return False
    if re.search(r"\bbudget\b", text, re.I) and not re.search(
        r"\b(under|below|upto|up to|within|tak|se kam)\b", text, re.I
    ):
        return True
    return False


def _accept_extracted_price(
    text: str,
    amount: float,
    suffix: str | None,
    *,
    require_strong_hint: bool = False,
) -> bool:
    if amount <= 0:
        return False
    digits = str(int(amount)) if amount == int(amount) else str(amount)
    if digits.replace(".", "").isdigit() and len(digits.replace(".", "")) >= 7:
        return False
    if _reject_ambiguous_budget(text, amount, suffix):
        return False
    if _amount_has_scale(suffix, amount):
        return True
    if "₹" in text:
        return True
    if require_strong_hint:
        return bool(_STRONG_PRICE_HINT_RE.search(text))
    return bool(_PRICE_HINT_RE.search(text))


def _extract_price_range(text: str) -> tuple[float | None, float | None]:
    for pattern in _RANGE_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            low_suffix = groups[1] if len(groups) > 1 else None
            high_suffix = groups[3] if len(groups) > 3 else None
            low = _parse_amount(groups[0], low_suffix)
            high = _parse_amount(groups[2], high_suffix)
            if low is not None and high is not None:
                low_ok = _accept_extracted_price(
                    text, low, low_suffix, require_strong_hint=True
                )
                high_ok = _accept_extracted_price(
                    text, high, high_suffix, require_strong_hint=True
                )
                if low_ok and high_ok:
                    return min(low, high), max(low, high)
                # "between 0-10,000" — zero lower bound means implicit floor (under X)
                if not low_ok and low <= 0 and high_ok:
                    return None, high
    return None, None


def _extract_around_price(text: str) -> tuple[float | None, float | None]:
    for pattern in _AROUND_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(text, val, suffix, require_strong_hint=True):
                return _snap_single_price_to_band(val)
    return None, None


# Single source of truth for the single-price variance. The LLM never computes
# bands (it emits min == max == stated amount); only this code widens them.
_SINGLE_PRICE_BAND_FACTOR = 0.05  # ±5%

# Explicit-range markers (English, Hinglish, Devanagari). A price pair WITHOUT
# one of these came from a single stated amount, not a user-given range.
_RANGE_INDICATOR_RE = re.compile(
    r"\bto\b|\bbetween\b|\bse\b|\btak\b|[-–]|से|तक", re.I
)


def _snap_single_price_to_band(price: float) -> tuple[float, float]:
    """Symmetric ±5% band around a single price.

    One delta mirrored both sides (rounded half-up to nearest 50) so the band
    is always exactly symmetric: 25000 → (23750, 26250), 50000 → (47500,
    52500) — never lopsided like the old (23800, 26200).
    """
    delta = float(int(price * _SINGLE_PRICE_BAND_FACTOR / 50 + 0.5) * 50)
    lo = max(price - delta, 0.0)
    hi = price + delta
    return lo, hi


def _extract_single_target_listed_price(text: str) -> tuple[float | None, float | None]:
    """'of price X' / 'price X' without under/tak → ±10% band."""
    if _MAX_DIRECTION_RE.search(text) or _MIN_DIRECTION_RE.search(text):
        return None, None
    for pattern in _SINGLE_TARGET_PRICE_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(
                text, val, suffix, require_strong_hint=False
            ):
                return _snap_single_price_to_band(val)
    return None, None


def _extract_single_budget_price(text: str) -> tuple[float | None, float | None]:
    """Plain 'budget X' / 'X budget' without under/tak → ±10% band."""
    if _MAX_DIRECTION_RE.search(text):
        return None, None
    for pattern in _SINGLE_BUDGET_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(
                text, val, suffix, require_strong_hint=False
            ):
                return _snap_single_price_to_band(val)
    return None, None


def _extract_explicit_max_price(text: str) -> float | None:
    for pattern in _EXPLICIT_MAX_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(
                text, val, suffix, require_strong_hint=False
            ):
                return val
    return None


def _extract_greedy_max_catchall(
    text: str, *, exclude_amount: float | None = None
) -> float | None:
    for m in _GREEDY_MAX_CATCHALL.finditer(text):
        suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
        val = _parse_amount(m.group(1), suffix)
        if val is None:
            continue
        if exclude_amount is not None and val == exclude_amount:
            continue
        if _accept_extracted_price(text, val, suffix, require_strong_hint=True):
            return val
    return None


def _hazaar_word_to_amount(word: str | None) -> float | None:
    if not word:
        return None
    normalized = word.strip().lower()
    if normalized in _HINDI_COUNT_WORDS:
        return float(_HINDI_COUNT_WORDS[normalized] * 1000)
    try:
        return float(normalized.replace(",", "")) * 1000
    except ValueError:
        return None


def _extract_hazaar_standalone_max(text: str) -> float | None:
    """Bare '50 hazaar' / 'das hazaar' (if not preprocessed) as max budget."""
    if re.search(r"se\s*(upar|zyada)", text, re.I):
        return None
    m = _HAZAAR_STANDALONE_RE.search(text)
    if not m:
        return None
    val = _hazaar_word_to_amount(m.group(1))
    if val is not None and val > 0 and _accept_extracted_price(text, val, "hazaar"):
        return val
    return None


def _extract_min_price(text: str) -> float | None:
    for pattern in _MIN_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            if suffix is None and "hazaar" in m.group(0).lower():
                suffix = "hazaar"
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(text, val, suffix, require_strong_hint=True):
                return val
    return None


def _extract_standalone_hindi_number_max(text: str) -> float | None:
    """Treat bare Hindi number phrases (e.g. 'das hazaar') as max budget."""
    normalized = _normalize_text(text)
    for phrase, digits in _HINDI_NUMBER_PHRASES:
        if normalized == phrase:
            val = _parse_amount(digits, None)
            if val is not None and val > 0:
                return val
    preprocessed = _preprocess_hindi_numbers(normalized).strip()
    if preprocessed == normalized:
        return None
    if not re.fullmatch(r"[\d,]+(?:\.\d+)?", preprocessed):
        return None
    val = _parse_amount(preprocessed, None)
    if val is not None and val > 0:
        return val
    return None


def _extract_prices(text: str) -> tuple[float | None, float | None]:
    preprocessed = _preprocess_hindi_numbers(text)
    min_p, max_p = _extract_price_range(preprocessed)
    if min_p is not None or max_p is not None:
        return min_p, max_p
    min_p, max_p = _extract_around_price(preprocessed)
    if min_p is not None or max_p is not None:
        return min_p, max_p
    min_p = _extract_min_price(preprocessed)
    if min_p is not None:
        return min_p, None
    max_p = _extract_explicit_max_price(preprocessed)
    if max_p is not None:
        return None, max_p
    min_p, max_p = _extract_single_budget_price(preprocessed)
    if min_p is not None or max_p is not None:
        return min_p, max_p
    min_p, max_p = _extract_single_target_listed_price(preprocessed)
    if min_p is not None or max_p is not None:
        return min_p, max_p
    standalone_max = _extract_standalone_hindi_number_max(text)
    if standalone_max is not None:
        if _MAX_DIRECTION_RE.search(preprocessed):
            return None, standalone_max
        return _snap_single_price_to_band(standalone_max)
    hazaar_max = _extract_hazaar_standalone_max(preprocessed)
    if hazaar_max is not None:
        if _MAX_DIRECTION_RE.search(preprocessed):
            return None, hazaar_max
        return _snap_single_price_to_band(hazaar_max)
    max_p = _extract_greedy_max_catchall(preprocessed)
    if max_p is not None:
        # "50k ka ring" / bare "50k" without under/tak → ±10% band
        if _MAX_DIRECTION_RE.search(preprocessed):
            return None, max_p
        return _snap_single_price_to_band(max_p)
    return None, None


def _all_category_material_terms() -> set[str]:
    terms: set[str] = set()
    for synonyms in _CATEGORY_SYNONYMS.values():
        terms.update(synonyms)
    for synonyms in _MATERIAL_SYNONYMS.values():
        terms.update(synonyms)
    return terms


def _is_blocked_title_token(lower: str, blocked: set[str]) -> bool:
    if lower in blocked:
        return True
    singular = _singularize_english(lower)
    if singular in blocked:
        return True
    if f"{lower}s" in blocked or f"{singular}s" in blocked:
        return True
    return False


def _extract_title(text: str, original_text: str) -> str | None:
    for coll in sorted(_KISNA_COLLECTIONS, key=len, reverse=True):
        if _synonym_in_text(text, coll):
            return coll

    tokens = re.findall(r"\b[A-Za-z][A-Za-z'-]+\b", original_text)
    blocked = _all_category_material_terms() | _TITLE_STOP_WORDS
    for token in tokens:
        lower = token.lower()
        if _is_blocked_title_token(lower, blocked):
            continue
        if lower in _KISNA_COLLECTIONS:
            return lower
    return None


def _extract_city(text: str) -> str | None:
    for city in _CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text):
            return city.title() if city != "bengaluru" else "Bengaluru"
    return None


def _extract_pincode(text: str) -> str | None:
    m = _PINCODE_RE.search(text)
    return m.group(1) if m else None


def _extract_material_type(text: str) -> tuple[str | None, bool]:
    material = _match_synonym(text, _MATERIAL_SYNONYMS)
    unsupported = material in _CLARA_UNSUPPORTED_MATERIALS if material else False
    return material, unsupported


def normalize_category_for_api(raw: str | list | None) -> str | None:
    """Map product/category labels to Clara API category values."""
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, str) or not raw.strip():
        return None

    text = raw.strip().lower()
    if text in _CATEGORY_SYNONYMS:
        return text

    for api_value, synonyms in _CATEGORY_SYNONYMS.items():
        if text == api_value or text == f"{api_value}s":
            return api_value
        for syn in synonyms:
            if text == syn or text == f"{syn}s":
                return api_value

    matched = _match_synonym(text, _CATEGORY_SYNONYMS)
    return matched


_SEARCH_RESET_RE = re.compile(
    r"\b(new search|start over|browse all|fresh search|reset search)\b",
    re.I,
)

_REFINEMENT_ONLY_RE = re.compile(
    r"\b(under|below|upto|up to|less than|maximum|max|budget|within|cheaper|affordable|"
    r"above|over|more than|them|those|these|it|ones)\b",
    re.I,
)

_REFINEMENT_RE = re.compile(
    r"\b(cheaper|sasta|aur\s+sasta|aur\s+kam|aur\s+zyada|"
    r"expensive|mehnga|aur\s+mehnga|similar|aise\s+hi|"
    r"isi\s+range|same\s+budget|similar\s+price)\b",
    re.I,
)

_CONTEXT_REFINEMENT_RE = re.compile(r"\b(them|those|these|it|ones)\b", re.I)

_NEVER_INHERIT_FIELDS = frozenset({
    "title",
    "collection",
    "size",
    "karat",
    "metal_colour",
    "occasion",
    "style",
    "gender",
})

_COLOUR_EVIDENCE_RE = re.compile(
    r"\b(yellow|white|rose|pink|rosegold|rose\s*gold|white\s*gold|yellow\s*gold)\b",
    re.I,
)

_KARAT_EVIDENCE_RE = re.compile(
    r"\b(?:9|14|18|22|24)\s*(?:kt|k|carat|karat)\b",
    re.I,
)

_SIZE_EVIDENCE_RE = re.compile(
    r"\b(?:size|sz)\s*[:=]?\s*([7-9]|1[0-9]|2[0-2])\b|"
    r"\b([7-9]|1[0-9]|2[0-2])\s*(?:size|sz)\b",
    re.I,
)

# Synonym evidence for LLM-only fields (must appear in the current user message).
_OCCASION_EVIDENCE: dict[str, tuple[str, ...]] = {
    "wedding": ("wedding", "shaadi", "shadi", "marriage", "reception", "vivah", "bridal"),
    "engagement": ("engagement", "sagai", "roka"),
    "anniversary": ("anniversary",),
    "birthday": ("birthday", "janamdin", "bday"),
    "daily_wear": ("daily wear", "daily", "everyday", "office wear", "casual", "roz pehenna", "roz"),
    "gift": ("gift", "present", "tuhfa"),
}

_STYLE_EVIDENCE: dict[str, tuple[str, ...]] = {
    "traditional": ("traditional", "ethnic"),
    "modern": ("modern",),
    "minimal": ("minimal", "simple", "sada"),
    "heavy": ("heavy", "bold"),
    "fashion": ("fashion",),
    "cocktail": ("cocktail", "party"),
    "couple_bands": ("couple band", "couple bands", "couple"),
    "infinity": ("infinity",),
    "hearts": ("hearts", "heart"),
    "floral": ("floral", "flower"),
    "adjustable": ("adjustable",),
}

_GENDER_EVIDENCE: dict[str, tuple[str, ...]] = {
    "women": ("for her", "wife", "ladies", "women", "woman", "girlfriend"),
    "men": ("for him", "men's", "mens", "husband", "men ", " men"),
    "kids": ("kids", "children", "child", "baby", "for kids"),
}


def _text_has_any_synonym(text: str, synonyms: tuple[str, ...] | list[str]) -> bool:
    normalized = (text or "").lower()
    if not normalized:
        return False
    return any(syn in normalized for syn in synonyms if syn)


def _occasion_evidenced(query: str, occasion: str | None) -> bool:
    if not occasion:
        return False
    key = str(occasion).strip().lower()
    synonyms = _OCCASION_EVIDENCE.get(key, (key.replace("_", " "),))
    return _text_has_any_synonym(query, synonyms)


def _style_evidenced(query: str, style: str | None) -> bool:
    if not style:
        return False
    key = str(style).strip().lower()
    synonyms = _STYLE_EVIDENCE.get(key, (key.replace("_", " "),))
    return _text_has_any_synonym(query, synonyms)


def _gender_evidenced(query: str, gender: str | None) -> bool:
    if not gender:
        return False
    key = str(gender).strip().lower()
    synonyms = _GENDER_EVIDENCE.get(key)
    if not synonyms:
        return False
    normalized = (query or "").lower()
    if key == "men":
        # Avoid matching "women" / "recommendation" via bare "men"
        if re.search(r"\b(for\s+him|men'?s|mens|husband)\b", normalized):
            return True
        if re.search(r"\bmen\b", normalized) and not re.search(r"\bwomen\b", normalized):
            return True
        return False
    return _text_has_any_synonym(query, synonyms)


def _collection_evidenced(query: str, collection: str | None) -> bool:
    if not collection:
        return False
    needle = str(collection).strip().lower()
    normalized = (query or "").lower()
    if not needle or not normalized:
        return False
    if needle in normalized:
        return True
    for coll in _KISNA_COLLECTIONS:
        if coll in normalized and (coll in needle or needle in coll):
            return True
    return False


def apply_llm_evidence_gate(query: str, llm_entities: dict) -> dict:
    """
    Strip LLM-only attributes that lack evidence in the current user text.

    metal_colour requires an explicit colour word (not bare 'gold').
    material_type requires regex material match.
    karat/size require KT/size evidence in the query.
    occasion/style/gender/collection require synonym evidence in the query.
    """
    out = dict(llm_entities or {})
    text = query or ""
    regex_quick = extract_entities(text) if text.strip() else {}

    if out.get("material_type") and not regex_quick.get("material_type"):
        out["material_type"] = None

    if out.get("metal_colour"):
        if not (
            regex_quick.get("metal_colour") or _COLOUR_EVIDENCE_RE.search(text)
        ):
            out["metal_colour"] = None

    if out.get("karat") and not _KARAT_EVIDENCE_RE.search(text):
        out["karat"] = None

    if out.get("size") is not None and not _SIZE_EVIDENCE_RE.search(text):
        out["size"] = None

    if out.get("occasion") and not _occasion_evidenced(text, out.get("occasion")):
        out["occasion"] = None

    if out.get("style") and not _style_evidenced(text, out.get("style")):
        out["style"] = None

    if out.get("gender") and not _gender_evidenced(text, out.get("gender")):
        out["gender"] = None

    if out.get("collection") and not _collection_evidenced(text, out.get("collection")):
        out["collection"] = None

    return out


def extract_category_from_product(product: dict) -> str | None:
    """Read Clara category from productType.category.name or top-level category."""
    if not isinstance(product, dict):
        return None
    top = product.get("category")
    if top:
        return normalize_category_for_api(top)
    product_type = product.get("productType") or {}
    if isinstance(product_type, dict):
        cat_block = product_type.get("category") or {}
        if isinstance(cat_block, dict):
            return normalize_category_for_api(cat_block.get("name"))
    return None


def merge_search_entities(
    prior: dict[str, Any] | None,
    new: dict[str, Any],
    query: str,
) -> dict[str, Any]:
    """
    Merge prior search filters with newly extracted entities for follow-up refinements.

    e.g. after earrings search, "I want them under 10,000" keeps category=earring.
    """
    merged = {
        "category": new.get("category"),
        "categories": new.get("categories"),
        "multi_category": new.get("multi_category", False),
        "secondary_category": new.get("secondary_category"),
        "material_type": new.get("material_type"),
        "unsupported_category": new.get("unsupported_category", False),
        "unsupported_material": new.get("unsupported_material", False),
        "min_price": new.get("min_price"),
        "max_price": new.get("max_price"),
        "title": new.get("title"),
        "city": new.get("city"),
        "pincode": new.get("pincode"),
        "karat": new.get("karat"),
        "metal_colour": new.get("metal_colour"),
        "size": new.get("size"),
        "collection": new.get("collection"),
        "gender": new.get("gender"),
        "occasion": new.get("occasion"),
        "style": new.get("style"),
        "action": new.get("action"),
    }

    if not prior:
        return merged

    normalized_query = _normalize_text(query)
    if _SEARCH_RESET_RE.search(normalized_query):
        return merged

    prior = prior or {}
    new_has_category = merged.get("category") is not None
    new_has_material = merged.get("material_type") is not None
    new_has_title = merged.get("title") is not None
    new_has_price = (
        merged.get("min_price") is not None or merged.get("max_price") is not None
    )
    refinement_query = bool(_REFINEMENT_RE.search(normalized_query))
    price_only_new_search = (
        new_has_price
        and not new_has_category
        and not new_has_material
        and not new_has_title
        and not refinement_query
        and not _CONTEXT_REFINEMENT_RE.search(normalized_query)
    )

    # Fresh category search: do NOT inherit prior price/material unless restated.
    if new_has_category and prior.get("category") and merged.get("category") != prior.get(
        "category"
    ):
        return merged

    refinement_only = (
        not new_has_category
        and not new_has_material
        and not new_has_title
        and not price_only_new_search
        and (
            refinement_query
            or (new_has_price or _REFINEMENT_ONLY_RE.search(normalized_query))
        )
    )

    if refinement_only:
        for key in (
            "category",
            "categories",
            "multi_category",
            "secondary_category",
            "material_type",
            "title",
            "unsupported_category",
            "unsupported_material",
            "karat",
            "metal_colour",
            "size",
            "collection",
            "gender",
            "occasion",
            "style",
        ):
            if key in _NEVER_INHERIT_FIELDS:
                continue
            if merged.get(key) in (None, False) and prior.get(key) not in (None, False):
                merged[key] = prior.get(key)

    elif (
        not price_only_new_search
        and not new_has_category
        and prior.get("category")
        and not _SEARCH_RESET_RE.search(normalized_query)
    ):
        if not new_has_material and not new_has_title and new_has_price and refinement_query:
            merged["category"] = prior.get("category")
            merged["categories"] = prior.get("categories")
            merged["multi_category"] = prior.get("multi_category", False)
            merged["secondary_category"] = prior.get("secondary_category")
            if merged.get("material_type") is None:
                merged["material_type"] = prior.get("material_type")


    return merged


def normalize_material_for_api(raw: str | list | None) -> str | None:
    """Map material labels to Clara API material_type values."""
    if raw is None:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip().lower()
    if text in _MATERIAL_SYNONYMS:
        return text
    return _match_synonym(text, _MATERIAL_SYNONYMS)


def normalize_entities_for_clara(entities: dict[str, Any]) -> dict[str, Any]:
    """Map internal entity values to Clara-safe search params and UX notes."""
    out = dict(entities or {})
    notes: list[str] = []

    multi_cats = _clara_multi_categories_for_entities(out)
    if multi_cats:
        out["clara_multi_categories"] = multi_cats
        out["clara_category"] = None
    else:
        out.pop("clara_multi_categories", None)
        category = out.get("category")
        if category in _CLARA_UNSUPPORTED_CATEGORIES:
            out["unsupported_category"] = True
            out["clara_category"] = None
            notes.append(
                "I'll show you our full collection since we don't have a specific filter for that."
            )
        elif out.get("clara_category_override"):
            out["clara_category"] = out["clara_category_override"]
        elif category:
            if category in CATEGORY_NORMALIZATION_MAP:
                mapped = CATEGORY_NORMALIZATION_MAP[category]
                out["clara_category"] = mapped
                if mapped is None and category not in _CLARA_UNSUPPORTED_CATEGORIES:
                    out["unsupported_category"] = True
                    notes.append(
                        "I'll show you our full collection since we don't have a specific filter for that."
                    )
            else:
                out["clara_category"] = category
        else:
            out["clara_category"] = None

    material = out.get("material_type")
    if material in _CLARA_UNSUPPORTED_MATERIALS:
        out["unsupported_material"] = True
        out["clara_material_type"] = None
    elif material:
        out["clara_material_type"] = _CLARA_MATERIAL_MAP.get(material, material)
    else:
        out["clara_material_type"] = None

    if notes:
        out["_clara_search_note"] = " ".join(notes)
    return out


def is_unrecognizable_input(text: str) -> bool:
    """
    True when free text is nonsense/spam and should not trigger catalog search.

    Excludes valid pincodes, price refinements, catalog keywords, and short affirmations.
    """
    normalized = (text or "").strip()
    if not normalized:
        return False

    if _SHORT_AFFIRMATION_RE.match(normalized):
        return False

    if _PINCODE_ONLY_RE.match(normalized):
        return False

    if _REPEATED_CHAR_RE.match(normalized):
        return True

    if _KEYBOARD_MASH_RE.search(normalized):
        return True

    stripped = normalized.replace(" ", "")
    if stripped.isdigit() and len(stripped) > 6:
        return True

    entities = extract_entities(normalized)
    if any(
        entities.get(key) is not None
        for key in (
            "category",
            "categories",
            "material_type",
            "title",
            "min_price",
            "max_price",
            "city",
            "pincode",
        )
    ):
        return False

    if entities.get("multi_category"):
        return False

    if _PRICE_HINT_RE.search(normalized):
        return False

    if re.search(r"[a-zA-Z]", normalized):
        return False

    return len(normalized) >= 4


def extract_entities(text: str) -> dict[str, Any]:
    """
    Extract search entities from user message.

    Returns dict with category, categories, multi_category, secondary_category,
    material_type, unsupported flags, prices, title, city, pincode.
    """
    normalized = _normalize_text(text)
    categories = _extract_categories(normalized)
    if not categories and not _has_ambiguous_category_phrase(normalized):
        single = _match_synonym(normalized, _CATEGORY_SYNONYMS)
        if single:
            categories = [single]

    metal_colour = None
    if "rose gold" in normalized or "rosegold" in normalized:
        material_type = "rose_gold"
        metal_colour = "rose"
        unsupported_material = False
    elif "white gold" in normalized:
        material_type = "white_gold"
        metal_colour = "white"
        unsupported_material = False
    elif "yellow gold" in normalized:
        material_type = "gold"
        metal_colour = "yellow"
        unsupported_material = False
    else:
        material_type, unsupported_material = _extract_material_type(normalized)
    min_price, max_price = _extract_prices(normalized)
    category = categories[0] if categories else None
    unsupported_category = category in _CLARA_UNSUPPORTED_CATEGORIES if category else False
    title_text = _strip_command_prefix(text)
    title_normalized = _normalize_text(title_text)

    return {
        "category": category,
        "categories": categories or None,
        "multi_category": len(categories) >= 2,
        "secondary_category": categories[1] if len(categories) >= 2 else None,
        "material_type": material_type,
        "metal_colour": metal_colour,
        "unsupported_category": unsupported_category,
        "unsupported_material": unsupported_material,
        "min_price": min_price,
        "max_price": max_price,
        "title": _extract_title(title_normalized, title_text),
        "city": _extract_city(normalized),
        "pincode": _extract_pincode(text),
    }


def _parse_entity_json(raw: str) -> dict:
    """Parse flat entity JSON from LLM response."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {}


async def _call_llm_for_entities(
    *,
    system_prompt: str,
    user_message: str,
    max_tokens: int = 300,
    client_id: str = "kisna",
    phone_number: str | None = None,
) -> str:
    from kisna_chatbot.ai import complete_chat
    from kisna_chatbot.ai.types import AgentName

    return await complete_chat(
        agent=AgentName.CLASSIFIER,
        agent_display_name="Entity Extractor",
        instruction=system_prompt,
        messages=[{"role": "user", "content": user_message}],
        max_output_tokens=max_tokens,
        client_id=client_id,
        phone_number=phone_number,
    )


def extract_structured_fields(text: str) -> dict[str, Any]:
    """Regex-only extraction: prices, pincode, city. No category/title/material."""
    normalized = _normalize_text(text)
    min_price, max_price = _extract_prices(normalized)
    return {
        "min_price": min_price,
        "max_price": max_price,
        "pincode": _extract_pincode(text),
        "city": _extract_city(normalized),
    }


def combine_search_entities(
    llm_entities: dict,
    structured_fields: dict,
) -> dict:
    """
    Build search entities: LLM owns semantics; regex owns structured fields only.
    Prices: LLM value wins when set; regex fills min/max when LLM left them null.
    """
    llm = dict(llm_entities or {})
    structured = dict(structured_fields or {})
    merged: dict[str, Any] = {}

    for key in _REGEX_FILL_FIELDS:
        llm_val = llm.get(key)
        struct_val = structured.get(key)
        merged[key] = llm_val if llm_val is not None else struct_val

    for key in _SEMANTIC_MERGE_FIELDS:
        merged[key] = llm.get(key)

    for key in _LLM_ONLY_FIELDS:
        merged[key] = llm.get(key)

    for key, val in llm.items():
        if val is not None and key not in merged:
            merged[key] = val

    category = merged.get("category")
    material = merged.get("material_type")
    merged["unsupported_category"] = (
        category in _CLARA_UNSUPPORTED_CATEGORIES if category else False
    )
    merged["unsupported_material"] = (
        material in _CLARA_UNSUPPORTED_MATERIALS if material else False
    )
    return merged


async def extract_entities_with_llm(
    user_query: str,
    client_id: str = "kisna",
    phone_number: str | None = None,
    history_str: str | None = None,
) -> dict:
    """
    Fast LLM entity extraction for product search follow-ups.
    Uses entity-only prompt (no intent classification).
    Returns {} on any failure so regex fallback is used.
    """
    if not user_query or not user_query.strip():
        return {}

    from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor
    from kisna_chatbot.processors.classifier import _sanitize_llm_entities

    try:
        user_message = user_query.strip()
        if history_str and history_str.strip():
            user_message = (
                f"Recent conversation:\n{history_str.strip()}\n\n"
                f"Current message: {user_query.strip()}"
            )
        raw = await _call_llm_for_entities(
            system_prompt=kisna_entity_extractor,
            user_message=user_message,
            max_tokens=400,
            client_id=client_id,
            phone_number=phone_number,
        )
        parsed = _parse_entity_json(raw)
        sanitized = _sanitize_llm_entities(parsed)
        logger.debug(
            "entity_extractor: LLM extraction complete",
            extra={"query": user_query, "entities": sanitized},
        )
        return sanitized or {}
    except Exception:
        logger.warning(
            "entity_extractor: LLM extraction failed, regex only",
            extra={"query": user_query},
            exc_info=True,
        )
        return {}


def merge_llm_and_regex_entities(
    llm_entities: dict,
    regex_entities: dict,
) -> dict:
    """Backward-compatible alias: structured fields only from regex side."""
    structured = {
        key: (regex_entities or {}).get(key) for key in _REGEX_FILL_FIELDS
    }
    return combine_search_entities(llm_entities, structured)


_OCCASION_PREFIX_MESSAGES: dict[str, str] = {
    "anniversary": "Here are some great anniversary gift ideas 💍",
}


def apply_occasion_style_hints(
    entities: dict[str, Any],
    *,
    query: str | None = None,
) -> tuple[dict[str, Any], str | None]:
    """Apply occasion/style UX hints; return enhanced entities and optional prefix.

    Title injection (bridal / traditional / …) only runs when the occasion/style
    value is evidenced in ``query`` (or query is omitted for unit tests that
    pass already-gated entities).
    """
    enhanced = dict(entities or {})
    occasion = enhanced.get("occasion")
    style = enhanced.get("style")
    prefix_note: str | None = None

    if occasion or style:
        logger.info(
            "Occasion/style search hints",
            extra={"occasion": occasion, "style": style},
        )

    # Defense in depth: never inject Clara title filters from unevidenced fields.
    if query is not None:
        if occasion and not _occasion_evidenced(query, occasion):
            enhanced["occasion"] = None
            occasion = None
        if style and not _style_evidenced(query, style):
            enhanced["style"] = None
            style = None

    if occasion == "wedding" and not enhanced.get("title"):
        enhanced["title"] = "bridal"

    if occasion == "anniversary":
        prefix_note = _OCCASION_PREFIX_MESSAGES["anniversary"]

    # FIX 7: Do NOT assume category for birthday occasion.
    # Birthday occasion is still stored for client-side tag filtering,
    # but we must not force-set a category the user never stated.

    if style == "traditional" and not enhanced.get("title"):
        enhanced["title"] = "traditional"
    elif style in ("modern", "minimal", "heavy") and not enhanced.get("title"):
        enhanced["title"] = style

    return enhanced, prefix_note


def entities_to_api_params(entities: dict[str, Any]) -> dict[str, Any]:
    """Convert entities dict to keyword args for clara_api.search_products."""
    normalized = normalize_entities_for_clara(entities)
    params: dict[str, Any] = {}

    clara_category = normalized.get("clara_category")
    if clara_category:
        params["category"] = clara_category

    clara_material = normalized.get("clara_material_type")
    if clara_material:
        params["material_type"] = clara_material

    min_p = normalized.get("min_price")
    max_p = normalized.get("max_price")
    if max_p is not None:
        params["max_price"] = int(float(max_p))
    if min_p is not None and float(min_p) > 0:
        params["min_price"] = int(float(min_p))
    elif max_p is not None and (min_p is None or float(min_p) == 0):
        params["min_price"] = 0
    collection = normalized.get("collection")
    title = normalized.get("title")
    if collection:
        params["title"] = collection
        if title and str(title).strip().lower() != str(collection).strip().lower():
            logger.debug(
                "Using collection as Clara title param",
                extra={"collection": collection, "title": title},
            )
    elif title is not None:
        params["title"] = title
    return params


def build_search_context(entities: dict[str, Any]) -> str:
    """Human-readable search description, e.g. 'gold rings under ₹50,000'."""
    parts: list[str] = []

    material = entities.get("material_type")
    if material:
        display_material = _CLARA_MATERIAL_MAP.get(material, material)
        if display_material in _CLARA_UNSUPPORTED_MATERIALS:
            display_material = material.replace("_", " ")
        parts.append(display_material)

    category = entities.get("category")
    if category:
        if entities.get("clara_category_override") == "chain":
            cat_label = "chains"
        else:
            cat_label = category if category.endswith("s") else f"{category}s"
            if cat_label == "mangalsutras":
                cat_label = "mangalsutra"
        parts.append(cat_label.replace("_", " "))

    title = entities.get("title")
    if title and not title_redundant_with_category(entities):
        title_display = str(title).title()
        context_so_far = " ".join(parts).lower()
        if title_display.lower() not in context_so_far:
            parts.append(title_display)

    min_p = entities.get("min_price")
    max_p = entities.get("max_price")
    if min_p is not None and max_p is not None:
        parts.append(f"₹{int(min_p):,} – ₹{int(max_p):,}")
    elif max_p is not None:
        parts.append(f"under ₹{int(max_p):,}")
    elif min_p is not None:
        parts.append(f"above ₹{int(min_p):,}")

    if not parts:
        return "KISNA Jewellery"
    return " ".join(parts)


def has_strict_product_filters(entities: dict) -> bool:
    """True when category, material, or price bounds should be enforced client-side."""
    if not entities:
        return False
    return bool(
        entities.get("category")
        or entities.get("categories")
        or entities.get("material_type")
        or entities.get("title")
        or entities.get("min_price") is not None
        or entities.get("max_price") is not None
    )


def _product_material_matches(product: dict, material_type: str) -> bool:
    clara_material = _CLARA_MATERIAL_MAP.get(material_type, material_type)
    raw = product.get("materialType")
    if isinstance(raw, list):
        return any(normalize_material_for_api(m) == clara_material for m in raw if m)
    normalized = normalize_material_for_api(raw)
    if normalized in _CLARA_MATERIAL_MAP:
        normalized = _CLARA_MATERIAL_MAP[normalized]
    return normalized == clara_material


def _categories_match(entity_cat: str | None, product_cat: str | None) -> bool:
    if entity_cat == product_cat:
        return True
    if not entity_cat or not product_cat:
        return False
    equivalents = {("chain", "necklace"), ("necklace", "chain")}
    return (entity_cat, product_cat) in equivalents


def _product_title_matches_hint(product: dict, hint: str) -> bool:
    needle = (hint or "").strip().lower()
    if not needle:
        return True
    title = (product.get("title") or "").lower()
    if needle in title:
        return True
    product_type = product.get("productType") or {}
    if isinstance(product_type, dict):
        for coll in product_type.get("collections") or []:
            if isinstance(coll, dict) and needle in str(coll.get("title") or "").lower():
                return True
    return False


def _product_matches_entities(product: dict, entities: dict) -> bool:
    if not isinstance(product, dict):
        return False

    categories = entities.get("categories")
    category = entities.get("category")
    if categories and not category:
        product_cat = extract_category_from_product(product)
        if product_cat not in categories:
            return False
    elif category == "bangle_bracelet" or (
        category is None
        and entities.get("multi_category")
        and set(categories or []) >= {"bangle", "bracelet"}
    ):
        product_cat = extract_category_from_product(product)
        if product_cat not in ("bangle", "bracelet"):
            return False
    elif category and not entities.get("unsupported_category"):
        product_cat = extract_category_from_product(product)
        if not _categories_match(category, product_cat):
            return False

    material = entities.get("material_type")
    if material and not entities.get("unsupported_material"):
        if not _product_material_matches(product, material):
            return False

    title_hint = entities.get("title")
    if title_hint and not _product_title_matches_hint(product, str(title_hint)):
        return False

    display_price = resolve_product_prices(product)["display_price"]
    min_price = entities.get("min_price")
    max_price = entities.get("max_price")
    if min_price is not None and display_price < min_price:
        return False
    if max_price is not None and display_price > max_price:
        return False

    return True


def filter_products_by_entities(products: list[dict], entities: dict) -> list[dict]:
    """Keep only products matching active category, material, and price filters."""
    if not products:
        return []
    if not has_strict_product_filters(entities):
        return list(products)
    return [p for p in products if _product_matches_entities(p, entities)]


_EXTRA_FILTER_KEYS = _CLIENT_FILTER_KEYS

_GENDER_DISPLAY = {
    "women": ("women", "for her", "her"),
    "men": ("men", "for him", "him"),
    "kids": ("kids", "children", "child"),
}

_STYLE_DISPLAY = {
    "fashion": "fashion",
    "cocktail": "cocktail",
    "couple_bands": "couple",
    "minimal": "minimal",
    "infinity": "infinity",
    "hearts": "heart",
    "floral": "floral",
    "adjustable": "adjustable",
    "traditional": "traditional",
    "modern": "modern",
    "heavy": "heavy",
}


def has_client_side_filters(entities: dict) -> bool:
    """True when entities need client-side filtering beyond Clara API params."""
    if any(entities.get(k) is not None for k in _CLIENT_FILTER_KEYS):
        return True
    return entities.get("material_type") in ("rose_gold", "white_gold")


def resolve_api_page_size(entities: dict) -> int:
    """Larger fetch when client-side filters will narrow the result pool."""
    if has_client_side_filters(entities):
        return CLIENT_SIDE_FILTER_PAGE_SIZE
    return DEFAULT_API_PAGE_SIZE


def enrich_entities_for_client_filter(entities: dict[str, Any]) -> dict[str, Any]:
    """Derive client-filter fields from material hints (not sent to Clara API)."""
    out = dict(entities or {})
    material = out.get("material_type")
    if material == "rose_gold":
        out["material_type"] = "gold"
        if not out.get("metal_colour"):
            out["metal_colour"] = "rose"
    elif material == "white_gold":
        out["material_type"] = "gold"
        if not out.get("metal_colour"):
            out["metal_colour"] = "white"
    return out


def _has_extra_filters(entities: dict, active_keys: tuple[str, ...] | None = None) -> bool:
    keys = active_keys or _EXTRA_FILTER_KEYS
    return any(entities.get(key) is not None for key in keys)


def _get_parsed_variant(product: dict) -> dict[str, Any]:
    from kisna_chatbot.utils.product_formatter import parse_variant_details

    return parse_variant_details(product)


def _tag_managers(product: dict) -> list[dict]:
    product_type = product.get("productType") or {}
    if not isinstance(product_type, dict):
        return []
    tags = product_type.get("tagManagers") or []
    return [t for t in tags if isinstance(t, dict)]


def _collection_titles(product: dict) -> list[str]:
    product_type = product.get("productType") or {}
    if not isinstance(product_type, dict):
        return []
    titles: list[str] = []
    for coll in product_type.get("collections") or []:
        if isinstance(coll, dict) and coll.get("title"):
            titles.append(str(coll["title"]).lower())
    return titles


def _variant_title(product: dict) -> str:
    variant = product.get("variant") or {}
    if isinstance(variant, dict):
        return str(variant.get("title") or "")
    return ""


def _media_colours(product: dict) -> list[str]:
    colours: list[str] = []
    for item in product.get("mediaUrl") or []:
        if isinstance(item, dict) and item.get("color"):
            colours.append(str(item["color"]).lower())
    return colours


def _product_matches_extra_filter(
    product: dict, key: str, value: Any
) -> bool:
    if value is None:
        return True

    parsed = _get_parsed_variant(product)

    if key == "karat":
        wanted = str(value).upper().replace(" ", "")
        actual = (parsed.get("karat") or "").upper()
        if actual and actual != wanted:
            return False
        return True

    if key == "metal_colour":
        wanted = str(value).lower()
        actual = (parsed.get("metal_colour") or "").lower()
        if actual and actual != wanted:
            return False
        return True

    if key == "size":
        wanted = int(value)
        actual = parsed.get("size")
        if actual is not None and actual != wanted:
            return False
        return True

    if key == "collection":
        needle = str(value).lower()
        cols = _collection_titles(product)
        if any(needle in c for c in cols):
            return True
        product_title = str(product.get("title") or "").lower()
        return needle in product_title

    if key == "gender":
        wanted = str(value).lower()
        labels = _GENDER_DISPLAY.get(wanted, (wanted,))
        tags = [
            (t.get("name") or "").lower()
            for t in _tag_managers(product)
            if str(t.get("slug") or "").lower() == "gender"
        ]
        if tags and not any(
            wanted in t or any(label in t for label in labels) for t in tags
        ):
            return False
        return True

    if key == "occasion":
        occasion_key = str(value).lower()
        wanted_terms = _OCCASION_TAG_TERMS.get(
            occasion_key, (occasion_key.replace("_", " "),)
        )
        tags = [(t.get("name") or "").lower() for t in _tag_managers(product)]
        if tags and not any(
            term in tag for term in wanted_terms for tag in tags
        ):
            return False
        return True

    if key == "style":
        needle = _STYLE_DISPLAY.get(str(value).lower(), str(value).lower())
        tags = [(t.get("name") or "").lower() for t in _tag_managers(product)]
        if tags and not any(needle in tag or tag in needle for tag in tags):
            return False
        return True

    return True


def _filter_products_by_active_extras(
    products: list[dict], entities: dict, active_keys: tuple[str, ...]
) -> list[dict]:
    if not products or not active_keys:
        return list(products)
    filtered: list[dict] = []
    for product in products:
        if all(
            _product_matches_extra_filter(product, key, entities.get(key))
            for key in active_keys
            if entities.get(key) is not None
        ):
            filtered.append(product)
    return filtered


def filter_products_by_extracted_extras(
    products: list[dict], entities: dict
) -> tuple[list[dict], str | None]:
    """
    Client-side filter for fields Clara API does not accept.
    Progressively relaxes extras when fewer than 3 results match.

    The relax_note ("Couldn't find exact match…") is only emitted when the
    strict filter found ZERO matches and relaxation was required to surface any
    products.  If the strict filter already returned 1–2 valid matches (fewer
    than _MIN_EXTRA_FILTER_RESULTS but still genuine hits), those are returned
    with no note — the user asked for exactly these items.
    """
    if not products:
        return [], None

    entities = enrich_entities_for_client_filter(entities)
    if not _has_extra_filters(entities):
        return list(products), None

    original = list(products)
    active = [key for key in _EXTRA_FILTER_KEYS if entities.get(key) is not None]
    relax_note = "Couldn't find exact match, but here are the closest options:"

    filtered = _filter_products_by_active_extras(original, entities, tuple(active))
    if filtered:
        # Strict filter found genuine matches (1 or more) — return them as-is.
        # No fallback note: these ARE the exact items the user asked for.
        return filtered, None

    # Strict filter found zero matches — try relaxing constraints one at a time.
    for drop_key in _EXTRA_RELAXATION_ORDER:
        if drop_key not in active:
            continue
        active = [key for key in active if key != drop_key]
        if not active:
            break
        filtered = _filter_products_by_active_extras(original, entities, tuple(active))
        if len(filtered) >= _MIN_EXTRA_FILTER_RESULTS:
            return filtered, relax_note

    # Nothing matched even after relaxation — surface the full original list with a note.
    return original, relax_note

