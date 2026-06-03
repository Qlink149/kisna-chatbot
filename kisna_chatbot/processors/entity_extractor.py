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
        r"(?:under|below|upto|up to|max|budget|within|kam|se kam)\s*"
        r"₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
        re.I,
    ),
    re.compile(
        r"([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?\s*(?:tak|se kam|ke andar|ke neeche)",
        re.I,
    ),
    re.compile(
        r"budget\s*₹?\s*([\d,]+(?:\.\d+)?)\s*(k|lakh|lac)?",
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
