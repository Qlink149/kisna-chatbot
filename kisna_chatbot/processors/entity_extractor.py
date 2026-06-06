"""
Rule-based entity extraction from Hindi/English/Hinglish product search queries.
"""

import re
from typing import Any

_CATEGORY_SYNONYMS: dict[str, list[str]] = {
    "ring": [
        "ring",
        "rings",
        "anguthi",
        "angoothi",
        "angooti",
        "band",
    ],
    "earring": [
        "earring",
        "earrings",
        "bali",
        "jhumka",
        "jhhumka",
        "tops",
        "studs",
        "hoops",
        "drops",
        "danglers",
        "sui dhaga",
    ],
    "necklace": ["necklace", "haar", "mala", "chain", "tanmani"],
    "bracelet": ["bracelet", "kada", "cuff", "bolo"],
    "bangle": ["bangle", "bangles", "kangan", "chudi", "churi"],
    "pendant": ["pendant", "locket", "charm", "tanmaniya"],
    "mangalsutra": ["mangalsutra", "mangal sutra"],
    "nosewear": ["nose pin", "nath", "nose ring"],
    "watchwear": ["watch pin", "watch charm"],
}

_MATERIAL_SYNONYMS: dict[str, list[str]] = {
    "gold": [
        "gold",
        "sona",
        "sone",
        "sone ka",
        "18k",
        "14k",
        "22k",
        "yellow gold",
        "white gold",
        "rose gold",
    ],
    "diamond": ["diamond", "heera", "solitaire", "diamond studded"],
    "gemstone": ["gemstone", "ruby", "emerald", "sapphire"],
}

_COLLECTIONS = [
    "rivaah",
    "elysia",
    "aadya",
    "evil eye",
    "tanishta",
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

_PINCODE_RE = re.compile(r"\b([1-9]\d{5})\b")

# Price patterns — order matters: range first, then max, then min
_RANGE_PATTERNS = [
    re.compile(
        r"(?:between|from)\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:and|to|-)\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:to|-)\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*se\s*"
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*tak",
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
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:tak|se kam|ke andar|ke neeche)",
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
]

_MIN_PATTERNS = [
    re.compile(
        r"(?:above|over|more than|min|at least|zyada|se zyada)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:se zyada|ke upar|\+)",
        re.I,
    ),
]


def _normalize_text(text: str) -> str:
    return text.lower().strip()


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


def _match_synonym(text: str, synonyms_map: dict[str, list[str]]) -> str | None:
    """Return API value for longest matching synonym."""
    best: tuple[int, str] | None = None
    for api_value, synonyms in synonyms_map.items():
        for syn in synonyms:
            if syn in text:
                length = len(syn)
                if best is None or length > best[0]:
                    best = (length, api_value)
    return best[1] if best else None


def _extract_price_range(text: str) -> tuple[float | None, float | None]:
    for pattern in _RANGE_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            low = _parse_amount(groups[0], groups[1] if len(groups) > 1 else None)
            high = _parse_amount(groups[2], groups[3] if len(groups) > 3 else None)
            if low is not None and high is not None:
                return min(low, high), max(low, high)
    return None, None


def _extract_max_price(text: str) -> float | None:
    for pattern in _MAX_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            val = _parse_amount(groups[0], groups[1] if len(groups) > 1 else None)
            if val is not None:
                return val
    return None


def _extract_min_price(text: str) -> float | None:
    for pattern in _MIN_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            val = _parse_amount(groups[0], groups[1] if len(groups) > 1 else None)
            if val is not None:
                return val
    return None


def _extract_prices(text: str) -> tuple[float | None, float | None]:
    min_p, max_p = _extract_price_range(text)
    if min_p is not None or max_p is not None:
        return min_p, max_p
    max_p = _extract_max_price(text)
    if max_p is not None:
        return None, max_p
    min_p = _extract_min_price(text)
    return min_p, None


def _extract_title(text: str) -> str | None:
    for coll in _COLLECTIONS:
        if coll in text:
            return coll
    return None


def _extract_city(text: str) -> str | None:
    for city in _CITIES:
        if re.search(rf"\b{re.escape(city)}\b", text):
            return city.title() if city != "bengaluru" else "Bengaluru"
    return None


def _extract_pincode(text: str) -> str | None:
    m = _PINCODE_RE.search(text)
    return m.group(1) if m else None


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
        "material_type": new.get("material_type"),
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
        for key in ("category", "material_type", "title"):
            if merged.get(key) is None and prior.get(key) is not None:
                merged[key] = prior[key]

    elif not new_has_category and prior.get("category") and not _SEARCH_RESET_RE.search(
        normalized_query
    ):
        if not new_has_material and not new_has_title and new_has_price:
            merged["category"] = prior.get("category")
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


def extract_entities(text: str) -> dict[str, Any]:
    """
    Extract search entities from user message.

    Returns dict with keys: category, material_type, min_price, max_price,
    title, city, pincode (each str|float|None).
    """
    normalized = _normalize_text(text)
    min_price, max_price = _extract_prices(normalized)

    return {
        "category": _match_synonym(normalized, _CATEGORY_SYNONYMS),
        "material_type": _match_synonym(normalized, _MATERIAL_SYNONYMS),
        "min_price": min_price,
        "max_price": max_price,
        "title": _extract_title(normalized),
        "city": _extract_city(normalized),
        "pincode": _extract_pincode(text),
    }


def entities_to_api_params(entities: dict[str, Any]) -> dict[str, Any]:
    """Convert entities dict to keyword args for clara_api.search_products."""
    params: dict[str, Any] = {}
    for key in ("category", "material_type", "min_price", "max_price", "title"):
        val = entities.get(key)
        if val is not None:
            params[key] = val
    return params


def build_search_context(entities: dict[str, Any]) -> str:
    """Human-readable search description, e.g. 'gold rings under ₹50,000'."""
    parts: list[str] = []

    material = entities.get("material_type")
    if material:
        parts.append(material)

    category = entities.get("category")
    if category:
        cat_label = category if category.endswith("s") else f"{category}s"
        if cat_label == "mangalsutras":
            cat_label = "mangalsutra"
        parts.append(cat_label)

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
