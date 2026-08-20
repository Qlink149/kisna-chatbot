"""Pre-search validation of entity values against Clara /filters (Phase 5)."""

from __future__ import annotations

from typing import Any

from kisna_chatbot.integrations.clara_filters import (
    FACET_COLLECTION,
    FACET_COLOR,
    FACET_GENDER,
    FACET_KARAT,
    filters_available,
    get_available_options,
    get_category_id,
    is_value_available,
)
from kisna_chatbot.utils.logger_config import logger

# (entity key, facet, human label for the KIA line)
_VALIDATED_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("karat", FACET_KARAT, "karat"),
    ("metal_colour", FACET_COLOR, "colour"),
    ("collection", FACET_COLLECTION, "collection"),
    ("gender", FACET_GENDER, "gender"),
)

_GENDER_UI = {"women": "Female", "men": "Male", "kids": "Kids"}


def _option_titles(facet: str, options: list[dict], limit: int = 3) -> list[str]:
    titles: list[str] = []
    for opt in options:
        label = str(opt.get("label") or "").strip()
        if not label:
            continue
        if facet == FACET_GENDER:
            key = label.lower()
            if key in ("women", "female"):
                label = "Female"
            elif key in ("mens", "men", "male"):
                label = "Male"
            elif key in ("kids", "kid"):
                label = "Kids"
        elif facet == FACET_COLLECTION and label.lower().endswith(" collection"):
            label = label[: -len(" collection")].strip()
        if label not in titles:
            titles.append(label)
        if len(titles) >= limit:
            break
    return titles


def _single_cross_category_alternative(
    facet: str,
    value: str,
    current_category_id: str | None,
) -> str | None:
    """Return one other category label that offers ``value``, else None.

    Only when exactly one alternative exists — otherwise skip (Q6).
    """
    from kisna_chatbot.integrations import clara_filters as cf

    snap = cf._load_snapshot() or {}
    by_cat = snap.get("by_category") or {}
    if not by_cat:
        return None

    matches: list[str] = []
    for cid, payload in by_cat.items():
        if current_category_id and str(cid) == str(current_category_id):
            continue
        opts = list(cf._options(payload if isinstance(payload, dict) else None, facet))
        if not opts:
            continue
        # Temporarily seed isn't needed — match against this payload's options.
        if cf._match_option(opts, value, fuzzy=(facet == FACET_COLLECTION)) is None:
            continue
        # Resolve a display name from global categories list.
        cat_label = None
        global_payload = cf._resolve_cached_payload(None) or snap.get("global")
        for cat_opt in cf._options(global_payload, "categories"):
            if str(cat_opt.get("value")) == str(cid):
                cat_label = str(cat_opt.get("label") or cat_opt.get("slug") or cid)
                break
        matches.append(cat_label or str(cid))
        if len(matches) > 1:
            return None
    return matches[0] if len(matches) == 1 else None


def build_impossible_value_prompt(entities: dict[str, Any] | None) -> list[dict] | None:
    """If an entity value is impossible for the category, return KIA + ≤3 QRs.

    Cold / unavailable filters → None (degradation: today's search behaviour).
    """
    if not entities or not filters_available():
        return None

    category = entities.get("category")
    category_id = get_category_id(str(category)) if category else None

    for entity_key, facet, human in _VALIDATED_FIELDS:
        raw = entities.get(entity_key)
        if raw is None:
            continue
        value = str(raw).strip()
        if not value or value.lower() in ("any", "none"):
            continue

        # Category-scoped options; collection may fall back to global list.
        fallback = facet == FACET_COLLECTION or category_id is None
        options = get_available_options(
            category_id, facet, fallback_global=fallback
        )
        if not options:
            # Empty facet or cold scoped payload — do not block.
            continue
        if is_value_available(category_id, facet, value):
            continue

        titles = _option_titles(facet, options, limit=3)
        cat_label = str(category).replace("_", " ") if category else "this category"
        line = (
            f"We don't currently offer *{value}* {human} in {cat_label}. "
            f"Here are options we do have:"
        )
        alt = _single_cross_category_alternative(facet, value, category_id)
        if alt:
            line = (
                f"We don't currently offer *{value}* {human} in {cat_label}. "
                f"We do have it in *{alt}*. "
                f"Or pick from what we offer here:"
            )

        logger.info(
            "Impossible filter value blocked before search",
            extra={
                "entity": entity_key,
                "value": value,
                "category": category,
                "category_id": category_id,
                "suggestions": titles,
                "cross_category": alt,
            },
        )

        responses: list[dict] = [{"type": "text", "text": line, "_compose": "filter_validation"}]
        if titles:
            responses.append(
                {
                    "type": "quickreply",
                    "text": f"Choose a {human}:",
                    "caption": "",
                    "options": [{"title": t[:20]} for t in titles],
                    "msgid": f"filter$fix${entity_key}",
                    "_compose": "filter_validation_qr",
                }
            )
        return responses

    return None
