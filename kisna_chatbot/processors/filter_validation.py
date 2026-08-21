"""Pre-search validation of entity values against Clara /filters (Phase 5)."""

from __future__ import annotations

import json
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
_GENDER_UI_REVERSE = {v.lower(): k for k, v in _GENDER_UI.items()}

# Bug 4: filter$fix$<entity_key> quick-reply state. The button msgid only
# carries which field was invalid (karat/metal_colour/collection/gender) —
# the corrected VALUE comes from the tapped button's title, and the entities
# it needs to be applied to were never persisted anywhere, so the tap landed
# nowhere (generic fallback text, service_selected left empty). This mirrors
# search_confirmation.py's PENDING_SEARCH_KEY pattern.
PENDING_FILTER_FIX_KEY = "pending_filter_fix"


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


def build_impossible_value_prompt(
    entities: dict[str, Any] | None,
    user_profile: dict[str, Any] | None = None,
) -> list[dict] | None:
    """If an entity value is impossible for the category, return KIA + ≤3 QRs.

    Cold / unavailable filters → None (degradation: today's search behaviour).

    When ``user_profile`` is given and a QR is returned, the triggering
    entities are stashed under PENDING_FILTER_FIX_KEY so a later
    ``filter$fix$<entity_key>`` tap (see ``parse_filter_fix_button`` /
    ``resolve_filter_fix``) has something to correct and re-search.
    """
    if not entities or not filters_available():
        return None

    # Chain is stored internally as category="necklace" with the real Clara
    # category in clara_category_override (see entity_extractor.py's
    # _CLARA_CATEGORY_OVERRIDE_FROM) — entities_to_api_params already prefers
    # the override; validation must too, or it checks filter availability
    # against the wrong category (necklace's karats, not chain's) and can
    # offer/apply a value that is not actually valid for what's being searched.
    category = entities.get("clara_category_override") or entities.get("category")
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
            if isinstance(user_profile, dict):
                set_pending_filter_fix(user_profile, entities, entity_key)
        return responses

    return None


def set_pending_filter_fix(
    user_profile: dict[str, Any], entities: dict[str, Any], entity_key: str
) -> None:
    user_profile[PENDING_FILTER_FIX_KEY] = {
        "entities": dict(entities or {}),
        "entity_key": entity_key,
    }


def get_pending_filter_fix(user_profile: dict[str, Any]) -> dict[str, Any] | None:
    pending = (user_profile or {}).get(PENDING_FILTER_FIX_KEY)
    return pending if isinstance(pending, dict) else None


def pop_pending_filter_fix(user_profile: dict[str, Any]) -> dict[str, Any] | None:
    pending = get_pending_filter_fix(user_profile)
    if isinstance(user_profile, dict):
        user_profile.pop(PENDING_FILTER_FIX_KEY, None)
    return pending


def parse_filter_fix_button(messages: dict) -> tuple[str, str] | None:
    """Return (entity_key, tapped_title) from a filter$fix$<entity_key> tap, or None."""
    interactive = (messages or {}).get("interactive") or {}
    if interactive.get("type") != "button_reply":
        return None
    reply = interactive.get("button_reply")
    if not isinstance(reply, dict):
        return None

    raw_id = str(reply.get("id") or "")
    msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            msgid = str(parsed.get("msgid") or raw_id)
    except (json.JSONDecodeError, TypeError):
        pass

    if not msgid.startswith("filter$fix$"):
        return None
    entity_key = msgid[len("filter$fix$") :]
    if not entity_key:
        return None
    title = (reply.get("title") or "").strip()
    if not title:
        return None
    return entity_key, title


def is_filter_fix_interactive(messages: dict) -> bool:
    return parse_filter_fix_button(messages) is not None


def resolve_filter_fix_value(entity_key: str, title: str) -> str | None:
    """Map a tapped button title back to the internal entity value.

    karat/metal_colour/collection reuse the same fuzzy option matching as
    validation (get_karat_id/get_colour_id/get_collection_id), so the label
    text Clara gave us for the button IS a value those resolvers already
    accept — pass it straight through. gender is the one facet whose
    internal value ("women"/"men"/"kids") differs from its UI label
    ("Female"/"Male"/"Kids"), so that one needs the reverse map.
    """
    if entity_key == "gender":
        return _GENDER_UI_REVERSE.get(title.strip().lower())
    return title
