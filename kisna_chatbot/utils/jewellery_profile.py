"""
Map product search entities to dashboard jewellery_profile fields.
"""

from typing import Any

_MATERIAL_BUTTON_VALUES = frozenset({"gold", "diamond", "gemstone"})

_OCCASION_SYNONYMS: dict[str, list[str]] = {
    "wedding": ["wedding", "shaadi", "shadi", "marriage", "reception", "vivah"],
    "engagement": ["engagement", "sagai", "roka"],
    "daily wear": ["daily wear", "daily", "everyday", "office", "casual", "office wear"],
    "gift": ["gift", "present", "birthday gift"],
    "festival": [
        "festival",
        "diwali",
        "karva chauth",
        "karwachauth",
        "rakhi",
        "navratri",
        "puja",
    ],
    "anniversary": ["anniversary"],
}


def _normalize_text(text: str) -> str:
    return text.lower().strip()


def _match_synonym(text: str, synonyms_map: dict[str, list[str]]) -> str | None:
    best: tuple[int, str] | None = None
    for canonical, synonyms in synonyms_map.items():
        for syn in synonyms:
            if syn in text:
                length = len(syn)
                if best is None or length > best[0]:
                    best = (length, canonical)
    return best[1] if best else None


def format_budget_range(min_price: Any, max_price: Any) -> str | None:
    """Format price bounds for dashboard display."""
    min_p = min_price if min_price is not None else None
    max_p = max_price if max_price is not None else None

    if min_p is not None and max_p is not None:
        return f"₹{int(min_p):,} – ₹{int(max_p):,}"
    if max_p is not None:
        return f"under ₹{int(max_p):,}"
    if min_p is not None:
        return f"above ₹{int(min_p):,}"
    return None


def extract_occasion(text: str) -> str | None:
    """Extract occasion from natural-language search text."""
    if not text or not text.strip():
        return None
    return _match_synonym(_normalize_text(text), _OCCASION_SYNONYMS)


def _should_extract_occasion(source_text: str | None) -> bool:
    if not source_text or not source_text.strip():
        return False
    normalized = _normalize_text(source_text)
    if normalized.startswith("similar:"):
        return False
    return normalized not in _MATERIAL_BUTTON_VALUES


def entities_to_jewellery_profile(
    entities: dict[str, Any],
    *,
    source_text: str | None = None,
) -> dict[str, str]:
    """Map search entities to dashboard jewellery_profile fields."""
    profile: dict[str, str] = {}

    material = entities.get("material_type")
    if material:
        profile["material_preference"] = str(material)

    category = entities.get("category")
    if category:
        profile["category_preference"] = str(category)

    budget = format_budget_range(
        entities.get("min_price"),
        entities.get("max_price"),
    )
    if budget:
        profile["budget_range"] = budget

    if _should_extract_occasion(source_text):
        occasion = extract_occasion(source_text or "")
        if occasion:
            profile["occasion"] = occasion

    return profile


def merge_jewellery_profile(
    existing: dict[str, Any] | None,
    updates: dict[str, Any],
) -> dict[str, str]:
    """Merge profile updates without clearing omitted fields."""
    merged = dict(existing or {})
    for key, value in updates.items():
        if value:
            merged[key] = value
    return merged
