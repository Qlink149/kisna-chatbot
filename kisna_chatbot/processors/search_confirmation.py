"""Confirm-before-search recap.

Every sticky/inherited slot is read back to the user before it reaches the
Clara API, so a filter that bled in from an earlier turn (gold, "for her",
an old budget) is visible and rejectable instead of silently shaping results.
"""

from __future__ import annotations

import json
import os
import re

CONFIRM_MSGID = "confirm$search"
CONFIRM_YES_MSGID = "confirm$search$yes"
CONFIRM_NO_MSGID = "confirm$search$no"

PENDING_SEARCH_KEY = "pending_search"
AWAITING_CORRECTION_KEY = "awaiting_search_correction"

_YES_TITLES = frozenset({"yes, show me", "yes", "yeah", "correct"})
_NO_TITLES = frozenset({"no, change it", "no", "change"})

_YES_TEXT_RE = re.compile(
    r"^\s*(yes|yeah|yep|yup|ya|yaa|sure|ok|okay|okk|k|correct|right|"
    r"perfect|sahi|sahi hai|haan|han|haa|ha|hanji|ji|ji haan|thik|"
    r"theek|theek hai|thik hai|bilkul|go ahead|show me|show|proceed)"
    r"\s*[!.]*\s*$",
    re.I,
)

_NO_TEXT_RE = re.compile(
    r"^\s*(no|nope|nah|na|nahi|nahin|galat|wrong|not correct|incorrect|"
    r"change|change it|edit)\s*[!.]*\s*$",
    re.I,
)

_GENDER_LABELS = {
    "women": "for women",
    "men": "for men",
    "kids": "for kids",
}


def is_confirm_enabled() -> bool:
    return os.getenv("KISNA_SEARCH_CONFIRM_ENABLED", "true").lower() in (
        "1",
        "true",
        "yes",
    )


def _price_phrase(entities: dict) -> str | None:
    min_p = entities.get("min_price")
    max_p = entities.get("max_price")
    try:
        min_v = int(min_p) if min_p is not None else None
        max_v = int(max_p) if max_p is not None else None
    except (TypeError, ValueError):
        return None
    if max_v is not None and (min_v is None or min_v == 0):
        return f"under ₹{max_v:,}"
    if min_v is not None and max_v is not None:
        return f"between ₹{min_v:,} and ₹{max_v:,}"
    if min_v is not None:
        return f"above ₹{min_v:,}"
    return None


def _category_phrase(entities: dict) -> str | None:
    from kisna_chatbot.processors.product_search_agent_v3 import (
        _humanize_category_label,
    )

    categories = entities.get("categories") or []
    if not categories and entities.get("category"):
        categories = [entities["category"]]
    labels = [_humanize_category_label(str(c)) for c in categories if c]
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def build_search_recap(entities: dict) -> str:
    """Plain-language read-back of the filters a search will use."""
    entities = entities or {}
    parts: list[str] = []

    material = entities.get("material_type")
    if material:
        parts.append(str(material).replace("_", " "))

    category = _category_phrase(entities)
    parts.append(category or "jewellery")

    gender = _GENDER_LABELS.get(str(entities.get("gender") or "").lower())
    if gender:
        parts.append(gender)

    price = _price_phrase(entities)
    if price:
        parts.append(price)

    # "Either is fine" carries no filter — say nothing about shipping.
    fulfillment = entities.get("fulfillment")
    if fulfillment == "ready":
        parts.append("ready to ship")
    elif fulfillment == "mto":
        parts.append("made to order")

    return " ".join(parts)


def should_confirm(entities: dict) -> bool:
    """False when there is nothing worth reading back (browse-all)."""
    entities = entities or {}
    if entities.get("category") or entities.get("categories"):
        return True
    return any(
        entities.get(key) is not None
        for key in ("material_type", "gender", "min_price", "max_price")
    )


def build_confirm_prompt(entities: dict) -> dict:
    recap = build_search_recap(entities)
    return {
        "type": "quickreply",
        "text": (
            f"Understood 👍 I'll look in our catalogue for *{recap}*. "
            "Does this sound correct to you?"
        ),
        "caption": "",
        "options": [
            {"title": "Yes, show me"},
            {"title": "No, change it"},
        ],
        "msgid": CONFIRM_MSGID,
        "_compose": "search_confirm",
    }


def build_correction_prompt() -> dict:
    return {
        "type": "text",
        "text": (
            "No problem — what should I change? "
            "e.g. *in gold*, *under 40k*, *for men*"
        ),
        "_compose": "search_correction",
    }


def _button_reply(messages: dict) -> dict | None:
    interactive = (messages or {}).get("interactive") or {}
    if interactive.get("type") != "button_reply":
        return None
    reply = interactive.get("button_reply")
    return reply if isinstance(reply, dict) else None


def _button_msgid(raw_id: str) -> str:
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            return str(parsed.get("msgid") or raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    return raw_id or ""


def parse_confirm_reply(messages: dict, text: str | None = None) -> str | None:
    """Return "yes" / "no" from a confirmation tap or typed answer."""
    reply = _button_reply(messages)
    if reply is not None:
        msgid = _button_msgid(str(reply.get("id") or ""))
        if msgid == CONFIRM_YES_MSGID:
            return "yes"
        if msgid == CONFIRM_NO_MSGID:
            return "no"
        title = (reply.get("title") or "").strip().lower()
        if msgid == CONFIRM_MSGID or title in _YES_TITLES or title in _NO_TITLES:
            if title in _YES_TITLES:
                return "yes"
            if title in _NO_TITLES:
                return "no"
        return None

    if not text:
        return None
    if _YES_TEXT_RE.match(text):
        return "yes"
    if _NO_TEXT_RE.match(text):
        return "no"
    return None


def set_pending_search(
    user_profile: dict,
    entities: dict,
    *,
    query_label: str,
    occasion_prefix: str | None = None,
    response_mode: str | None = None,
    exclude_product_id: str | None = None,
) -> None:
    user_profile[PENDING_SEARCH_KEY] = {
        "entities": dict(entities or {}),
        "query_label": query_label,
        "occasion_prefix": occasion_prefix,
        "response_mode": response_mode,
        "exclude_product_id": exclude_product_id,
    }
    user_profile.pop(AWAITING_CORRECTION_KEY, None)


def get_pending_search(user_profile: dict) -> dict | None:
    pending = (user_profile or {}).get(PENDING_SEARCH_KEY)
    return pending if isinstance(pending, dict) else None


def pop_pending_search(user_profile: dict) -> dict | None:
    pending = get_pending_search(user_profile)
    clear_confirm_state(user_profile)
    return pending


def has_pending_search(user_profile: dict) -> bool:
    return get_pending_search(user_profile) is not None


def clear_confirm_state(user_profile: dict) -> None:
    if not isinstance(user_profile, dict):
        return
    user_profile.pop(PENDING_SEARCH_KEY, None)
    user_profile.pop(AWAITING_CORRECTION_KEY, None)


def is_awaiting_correction(user_profile: dict) -> bool:
    return bool((user_profile or {}).get(AWAITING_CORRECTION_KEY))
