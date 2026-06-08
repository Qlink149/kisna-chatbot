"""
Rule-based entity extraction from Hindi/English/Hinglish product search queries.
"""

import re
from typing import Any

from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.price_calculator import resolve_product_prices

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
        "choker",
        "rani haar",
        "layered necklace",
        "long chain",
        "short chain",
    ],
    "bracelet": ["bracelet", "kada", "kadi", "bolo"],
    "bangle": ["bangle", "bangles", "kangan", "chudi", "churi", "kara"],
    "pendant": ["pendant", "locket", "charm", "latkan"],
    "mangalsutra": ["mangalsutra", "mangal sutra", "tanmaniya"],
    "nosewear": ["nose pin", "nosepin", "nose stud", "nath", "nose ring"],
    "watchwear": ["watch pin", "watch charm", "watch wear", "watch"],
    "anklet": ["anklet", "payal", "pajeb", "paayal"],
    "maang_tikka": ["maang tikka", "maangtika", "maang_tikka", "tikka", "tika", "bor"],
    "hathphool": ["hathphool", "hath phool"],
    "kamarband": ["kamarband", "kamar band"],
}

_CLARA_UNSUPPORTED_CATEGORIES = frozenset(
    {"anklet", "maang_tikka", "hathphool", "kamarband"}
)

_CLARA_CATEGORY_MAP: dict[str, str] = {
    "nosewear": "nose wear",
    "watchwear": "watch wear",
}

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
        "dikhao",
        "please",
        "me",
        "want",
        "looking",
        "for",
        "buy",
        "get",
        "find",
        "search",
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
    }
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
    r"\b(under|below|upto|up to|less than|maximum|max|within|tak|se kam|ke andar|ke neeche|above|over|more than|min|at least|se zyada|ke upar|between|from|around|approximately|roughly)\b|₹",
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

_MAX_PATTERNS = [
    re.compile(
        r"(?:under|below|upto|up to|max|maximum|budget|within|less than|kam|se kam)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:tak|se kam|ke andar|ke neeche)",
        re.I,
    ),
    re.compile(
        r"budget\s*(?:of\s*)?₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"within\s*(?:my\s*)?budget\s*(?:of\s*)?₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
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
    re.compile(
        r"([\d,]+(?:\.\d+)?)\s+budget\b",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)\b\s*budget",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)\b",
        re.I,
    ),
]

_MIN_PATTERNS = [
    re.compile(
        r"(?:above|over|more than|min|at least|zyada|se zyada)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:se zyada|ke upar|\+)",
        re.I,
    ),
]

_BUDGET_ONLY_RE = re.compile(
    r"^\s*budget\s+([\d,]+(?:\.\d+)?)\s*$",
    re.I,
)


def _normalize_text(text: str) -> str:
    return text.lower().strip()


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
    for start, _length, api_value in _iter_synonym_matches(text, _CATEGORY_SYNONYMS):
        if api_value in seen:
            continue
        seen.add(api_value)
        ordered.append((start, api_value))

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
                return val * 0.8, val * 1.2
    return None, None


def _extract_max_price(text: str) -> float | None:
    for pattern in _MAX_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(
                text, val, suffix, require_strong_hint=pattern in _MAX_PATTERNS[-1:]
            ):
                return val
    return None


def _extract_min_price(text: str) -> float | None:
    for pattern in _MIN_PATTERNS:
        m = pattern.search(text)
        if m:
            suffix = m.group(2) if m.lastindex and m.lastindex >= 2 else None
            val = _parse_amount(m.group(1), suffix)
            if val is not None and _accept_extracted_price(text, val, suffix, require_strong_hint=True):
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
    max_p = _extract_max_price(preprocessed)
    if max_p is not None:
        return None, max_p
    min_p = _extract_min_price(preprocessed)
    return min_p, None


def _all_category_material_terms() -> set[str]:
    terms: set[str] = set()
    for synonyms in _CATEGORY_SYNONYMS.values():
        terms.update(synonyms)
    for synonyms in _MATERIAL_SYNONYMS.values():
        terms.update(synonyms)
    return terms


def _extract_title(text: str, original_text: str) -> str | None:
    for coll in sorted(_KISNA_COLLECTIONS, key=len, reverse=True):
        if _synonym_in_text(text, coll):
            return coll

    tokens = re.findall(r"\b[A-Za-z][A-Za-z'-]+\b", original_text)
    blocked = _all_category_material_terms() | _TITLE_STOP_WORDS
    for token in tokens:
        lower = token.lower()
        if lower in blocked:
            continue
        if lower in _KISNA_COLLECTIONS:
            return lower
        if token[0].isupper() and len(token) > 2:
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

    refinement_only = (
        not new_has_category
        and not new_has_material
        and not new_has_title
        and (new_has_price or _REFINEMENT_ONLY_RE.search(normalized_query))
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
        ):
            if merged.get(key) in (None, False) and prior.get(key) not in (None, False):
                merged[key] = prior.get(key)

    elif not new_has_category and prior.get("category") and not _SEARCH_RESET_RE.search(
        normalized_query
    ):
        if not new_has_material and not new_has_title and new_has_price:
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

    category = out.get("category")
    if category in _CLARA_UNSUPPORTED_CATEGORIES:
        out["unsupported_category"] = True
        out["clara_category"] = None
        notes.append(
            "I'll show you our full collection since we don't have a specific filter for that."
        )
    elif category:
        out["clara_category"] = _CLARA_CATEGORY_MAP.get(category, category)
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

    material_type, unsupported_material = _extract_material_type(normalized)
    min_price, max_price = _extract_prices(normalized)
    category = categories[0] if categories else None
    unsupported_category = category in _CLARA_UNSUPPORTED_CATEGORIES if category else False

    return {
        "category": category,
        "categories": categories or None,
        "multi_category": len(categories) >= 2,
        "secondary_category": categories[1] if len(categories) >= 2 else None,
        "material_type": material_type,
        "unsupported_category": unsupported_category,
        "unsupported_material": unsupported_material,
        "min_price": min_price,
        "max_price": max_price,
        "title": _extract_title(normalized, text),
        "city": _extract_city(normalized),
        "pincode": _extract_pincode(text),
    }


def merge_llm_and_regex_entities(
    llm_entities: dict,
    regex_entities: dict,
) -> dict:
    """
    Merge LLM and regex entities.
    LLM wins on all fields where it returned non-null.
    Regex fills in any field where LLM returned null.
    """
    merged = dict(regex_entities or {})
    for key, val in (llm_entities or {}).items():
        if val is not None:
            merged[key] = val
    return merged


_OCCASION_PREFIX_MESSAGES: dict[str, str] = {
    "anniversary": "Here are some great anniversary gift ideas 💍",
}


def apply_occasion_style_hints(
    entities: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Apply occasion/style UX hints; return enhanced entities and optional prefix."""
    enhanced = dict(entities or {})
    occasion = enhanced.get("occasion")
    style = enhanced.get("style")
    prefix_note: str | None = None

    if occasion or style:
        logger.info(
            "Occasion/style search hints",
            extra={"occasion": occasion, "style": style},
        )

    if occasion == "wedding" and not enhanced.get("title"):
        enhanced["title"] = "bridal"

    if occasion == "anniversary":
        prefix_note = _OCCASION_PREFIX_MESSAGES["anniversary"]

    if occasion == "birthday" and not enhanced.get("category"):
        enhanced["category"] = "earring"

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
    if min_p is not None and float(min_p) > 0:
        params["min_price"] = min_p
    max_p = normalized.get("max_price")
    if max_p is not None:
        params["max_price"] = max_p
    title = normalized.get("title")
    if title is not None:
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
        cat_label = category if category.endswith("s") else f"{category}s"
        if cat_label == "mangalsutras":
            cat_label = "mangalsutra"
        parts.append(cat_label.replace("_", " "))

    title = entities.get("title")
    if title:
        parts.append(title.title())

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
        or entities.get("material_type")
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


def _product_matches_entities(product: dict, entities: dict) -> bool:
    if not isinstance(product, dict):
        return False

    category = entities.get("category")
    if category and not entities.get("unsupported_category"):
        if extract_category_from_product(product) != category:
            return False

    material = entities.get("material_type")
    if material and not entities.get("unsupported_material"):
        if not _product_material_matches(product, material):
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

