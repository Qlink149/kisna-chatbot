"""Guided jewellery discovery wizard with smart-skip of known slots."""

from __future__ import annotations

import json
import re
from typing import Any

# Steps in ask order. Category can already be filled from the first user message.
# Occasion removed — Clara has no occasion filter (client confirmed).
WIZARD_STEPS = (
    "category",
    "gender",
    "material",
    "budget",
    "fulfillment",
)

READY_TO_SHIP_EDD_DAYS = 7

DIGITAL_GOLD_URL = "https://www.kisna.com/digital-gold"

_GENDER_TITLE_MAP = {
    "female": "women",
    "male": "men",
    "kids": "kids",
    "women": "women",
    "men": "men",
    "for her": "women",
    "for him": "men",
    "wife": "women",
    "husband": "men",
    "girl": "women",
    "boy": "men",
    "ladies": "women",
    "gents": "men",
}

_MATERIAL_TITLE_MAP = {
    "gold": "gold",
    "diamond": "diamond",
    "gemstone": "gemstone",
    "gem stone": "gemstone",
    "stone": "gemstone",
}

_FULFILLMENT_TITLE_MAP = {
    "ready to ship": "ready",
    "ready-to-ship": "ready",
    "ready": "ready",
    "made to order": "mto",
    "made-to-order": "mto",
    "custom": "mto",
    "customise": "mto",
    "customize": "mto",
}

_ESCAPE_RE = re.compile(
    r"\b(skip|just\s+show|show\s+me|browse\s+all|any\s+will\s+do|"
    r"doesn't\s+matter|dont\s+matter|koi\s+bhi|kuch\s+bhi)\b",
    re.I,
)

_WIZARD_MSGID_PREFIX = "wizard$"


def is_wizard_active(user_profile: dict) -> bool:
    return bool(user_profile.get("shopping_wizard_active"))


def clear_wizard_state(user_profile: dict) -> None:
    for key in (
        "shopping_wizard_active",
        "shopping_wizard_step",
        "shopping_wizard_data",
    ):
        user_profile.pop(key, None)


def _wizard_data(user_profile: dict) -> dict:
    data = user_profile.get("shopping_wizard_data")
    if not isinstance(data, dict):
        data = {}
        user_profile["shopping_wizard_data"] = data
    return data


def seed_wizard_from_entities(
    entities: dict | None,
    *,
    query: str | None = None,
) -> dict:
    """Pre-fill wizard slots from classifier / regex entities (smart-skip)."""
    ents = entities or {}
    seeded: dict[str, Any] = {}

    category = ents.get("category")
    if category:
        seeded["category"] = str(category).strip().lower()

    gender = ents.get("gender")
    if gender in ("women", "men", "kids"):
        seeded["gender"] = gender
    elif query and not seeded.get("gender"):
        normalized = " ".join(str(query).strip().lower().split())
        if normalized in _GENDER_TITLE_MAP:
            seeded["gender"] = _GENDER_TITLE_MAP[normalized]
        else:
            for key, val in _GENDER_TITLE_MAP.items():
                if key in normalized:
                    seeded["gender"] = val
                    break

    material = ents.get("material_type")
    if material in ("gold", "diamond", "gemstone"):
        seeded["material_type"] = material

    if ents.get("min_price") is not None or ents.get("max_price") is not None:
        seeded["min_price"] = ents.get("min_price")
        seeded["max_price"] = ents.get("max_price")

    fulfillment = ents.get("fulfillment")
    if fulfillment in ("ready", "mto"):
        seeded["fulfillment"] = fulfillment
    elif query:
        from kisna_chatbot.processors.entity_extractor import extract_fulfillment

        inferred = extract_fulfillment(query)
        if inferred:
            seeded["fulfillment"] = inferred

    return seeded


def get_next_step(collected: dict) -> str | None:
    """Return the next missing step, or None when ready to search."""
    if not collected.get("category"):
        return "category"
    if not collected.get("gender"):
        return "gender"
    if not collected.get("material_type"):
        return "material"
    if collected.get("min_price") is None and collected.get("max_price") is None:
        return "budget"
    if not collected.get("fulfillment"):
        return "fulfillment"
    return None


def start_wizard(
    user_profile: dict,
    *,
    entities: dict | None = None,
    prepend_welcome: list[dict] | None = None,
    query: str | None = None,
) -> list[dict]:
    """Activate wizard, seed known slots, return next prompt messages."""
    collected = seed_wizard_from_entities(entities, query=query)
    user_profile["shopping_wizard_active"] = True
    user_profile["shopping_wizard_data"] = collected
    step = get_next_step(collected)
    if step is None:
        # Everything known — leave active so caller can complete search.
        user_profile["shopping_wizard_step"] = "complete"
        responses = list(prepend_welcome or [])
        return responses

    user_profile["shopping_wizard_step"] = step
    responses = list(prepend_welcome or [])
    responses.append(build_step_prompt(step, collected))
    return responses


def build_step_prompt(step: str, collected: dict | None = None) -> dict:
    collected = collected or {}
    if step == "category":
        return {
            "type": "text",
            "text": (
                "Hi! 👋 What are you looking for today? "
                "e.g. rings, earrings, necklaces…"
            ),
            "_compose": "wizard_category",
        }
    if step == "gender":
        return {
            "type": "quickreply",
            "text": "Great! Who is it for?",
            "caption": "",
            "options": [
                {"title": "Female"},
                {"title": "Male"},
                {"title": "Kids"},
            ],
            "msgid": "wizard$gender",
            "_compose": "wizard_gender",
        }
    if step == "material":
        return {
            "type": "quickreply",
            "text": "What type of jewellery are you interested in?",
            "caption": "",
            "options": [
                {"title": "Gold"},
                {"title": "Diamond"},
                {"title": "Gemstone"},
            ],
            "msgid": "wizard$material",
            "_compose": "wizard_material",
        }
    if step == "budget":
        return {
            "type": "text",
            "text": "What's your budget? e.g. under 25k, 15–35k, around 1 lakh",
            "_compose": "wizard_budget",
        }
    if step == "fulfillment":
        return {
            "type": "quickreply",
            "text": (
                "Are you looking for a ready-to-ship product or would you "
                "prefer a made-to-order design?"
            ),
            "caption": "",
            "options": [
                {"title": "Ready to ship"},
                {"title": "Made to order"},
            ],
            "msgid": "wizard$fulfillment",
            "_compose": "wizard_fulfillment",
        }
    return {
        "type": "text",
        "text": "Tell me a bit more about what you're looking for 🙂",
    }


def build_wizard_summary(collected: dict) -> str:
    """Final intro before product cards."""
    parts: list[str] = []
    material = collected.get("material_type")
    if material:
        parts.append(str(material))
    category = collected.get("category")
    if category:
        label = category if str(category).endswith("s") else f"{category}s"
        if label == "mangalsutras":
            label = "mangalsutra"
        parts.append(label.replace("_", " "))
    max_p = collected.get("max_price")
    min_p = collected.get("min_price")
    if max_p is not None and (min_p is None or float(min_p) == 0):
        parts.append(f"under ₹{int(max_p):,}")
    elif min_p is not None and max_p is not None:
        parts.append(f"₹{int(min_p):,}–₹{int(max_p):,}")
    elif min_p is not None:
        parts.append(f"above ₹{int(min_p):,}")
    desc = " ".join(parts) if parts else "jewellery"
    fulfillment = collected.get("fulfillment")
    if fulfillment == "ready":
        return f"Perfect! Let me show you the best ready-to-ship {desc}."
    if fulfillment == "mto":
        return (
            f"Perfect! Here are {desc} you can get made to order — "
            f"any of these can be crafted for you."
        )
    return f"Perfect! Let me show you the best {desc}."


def entities_from_wizard(collected: dict) -> dict:
    """Map wizard data into product-search entities."""
    return {
        "category": collected.get("category"),
        "material_type": collected.get("material_type"),
        "min_price": collected.get("min_price"),
        "max_price": collected.get("max_price"),
        "gender": collected.get("gender"),
        "fulfillment": collected.get("fulfillment"),
        "title": None,
        "city": None,
        "pincode": None,
        "karat": None,
        "metal_colour": None,
        "size": None,
        "collection": None,
        "style": None,
        "action": None,
        "occasion": None,
    }


def filter_by_fulfillment(
    products: list[dict],
    fulfillment: str | None,
    *,
    edd_days: int = READY_TO_SHIP_EDD_DAYS,
) -> tuple[list[dict], str | None]:
    """Legacy EDD post-filter — no longer used when Clara readyTOShip is set.

    Kept for tests / emergency fallback only. Prefer API boolean readyTOShip.
    MTO must never post-filter (every product is MTO-eligible).
    """
    if not fulfillment or fulfillment != "ready" or not products:
        return products, None

    ready: list[dict] = []
    for p in products:
        shipping = p.get("shipping") if isinstance(p, dict) else None
        edd = None
        if isinstance(shipping, dict):
            edd = shipping.get("edd")
        try:
            if edd is not None and int(edd) <= edd_days:
                ready.append(p)
        except (TypeError, ValueError):
            continue

    if ready:
        return ready, None
    return products, None


def parse_wizard_button(messages: dict) -> tuple[str, str] | None:
    """Return (step, value) from a wizard quick-reply tap, or None."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return None
    button_reply = interactive.get("button_reply", {})
    raw_id = button_reply.get("id", "")
    msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    if not isinstance(msgid, str) or not msgid.startswith(_WIZARD_MSGID_PREFIX):
        # Fallback: parent msgid may be wizard$gender — match title maps
        title = (button_reply.get("title") or "").strip().lower()
        if title in _GENDER_TITLE_MAP:
            return "gender", _GENDER_TITLE_MAP[title]
        if title in _MATERIAL_TITLE_MAP:
            return "material", _MATERIAL_TITLE_MAP[title]
        if title in _FULFILLMENT_TITLE_MAP:
            return "fulfillment", _FULFILLMENT_TITLE_MAP[title]
        return None

    parts = msgid.split("$")
    # wizard$gender or wizard$gender$female
    if len(parts) >= 3 and parts[2]:
        step, value = parts[1], parts[2]
        return step, value

    step = parts[1] if len(parts) >= 2 else ""
    title = (button_reply.get("title") or "").strip().lower()
    if step == "gender" and title in _GENDER_TITLE_MAP:
        return "gender", _GENDER_TITLE_MAP[title]
    if step == "material" and title in _MATERIAL_TITLE_MAP:
        return "material", _MATERIAL_TITLE_MAP[title]
    if step == "fulfillment" and title in _FULFILLMENT_TITLE_MAP:
        return "fulfillment", _FULFILLMENT_TITLE_MAP[title]
    return None


def parse_wizard_list(messages: dict) -> tuple[str, str] | None:
    """Return (step, value) from a wizard list reply, or None.

    Occasion list replies are ignored (step removed); kept for stale inbound taps.
    """
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return None
    list_reply = interactive.get("list_reply", {})
    raw_id = list_reply.get("id", "")
    postback = ""
    try:
        payload = json.loads(raw_id)
        if isinstance(payload, dict):
            postback = str(payload.get("postbackText", "") or "")
    except (json.JSONDecodeError, TypeError):
        pass

    candidate = postback or ""
    # Stale occasion taps from older sessions — ignore (do not set occasion)
    if candidate.startswith("wizard$occasion$"):
        return None
    return None


def is_wizard_interactive(messages: dict) -> bool:
    return parse_wizard_button(messages) is not None or parse_wizard_list(messages) is not None


def _apply_slot(collected: dict, step: str, value: Any) -> None:
    if step == "category" and value:
        collected["category"] = str(value).strip().lower()
    elif step == "gender" and value:
        collected["gender"] = value
    elif step == "material" and value:
        collected["material_type"] = value
    elif step == "budget":
        if isinstance(value, tuple) and len(value) == 2:
            collected["min_price"] = value[0]
            collected["max_price"] = value[1]
    elif step == "fulfillment" and value:
        collected["fulfillment"] = value


def _parse_text_for_step(step: str, text: str) -> Any | None:
    from kisna_chatbot.processors.entity_extractor import (
        extract_entities,
        normalize_internal_category,
    )

    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return None

    if step == "category":
        ents = extract_entities(text)
        if ents.get("category"):
            return ents["category"]
        guess = normalize_internal_category(
            {"category": normalized.replace(" ", "_")}
        )
        if guess.get("category") and guess["category"] != normalized.replace(
            " ", "_"
        ):
            return guess["category"]
        if ents.get("categories"):
            return ents["categories"][0]
        return None

    if step == "gender":
        if normalized in _GENDER_TITLE_MAP:
            return _GENDER_TITLE_MAP[normalized]
        for key, val in _GENDER_TITLE_MAP.items():
            if key in normalized:
                return val
        return None

    if step == "material":
        if normalized in _MATERIAL_TITLE_MAP:
            return _MATERIAL_TITLE_MAP[normalized]
        ents = extract_entities(text)
        mat = ents.get("material_type")
        if mat in ("gold", "diamond", "gemstone"):
            return mat
        return None

    if step == "budget":
        ents = extract_entities(text)
        min_p = ents.get("min_price")
        max_p = ents.get("max_price")
        if min_p is None and max_p is None:
            digits = re.sub(r"[^\d]", "", text or "")
            if digits.isdigit() and len(digits) >= 3:
                amount = int(digits)
                return (int(amount * 0.9), int(amount * 1.1))
            return None
        return (min_p, max_p)

    if step == "fulfillment":
        if normalized in _FULFILLMENT_TITLE_MAP:
            return _FULFILLMENT_TITLE_MAP[normalized]
        for key, val in _FULFILLMENT_TITLE_MAP.items():
            if key in normalized:
                return val
        from kisna_chatbot.processors.entity_extractor import extract_fulfillment

        return extract_fulfillment(text)

    return None


def advance_wizard(
    user_profile: dict,
    messages: dict,
    *,
    text: str | None = None,
) -> tuple[str, list[dict] | None]:
    """
    Process one wizard turn.

    Returns:
        ("prompt", [bot_responses]) — ask next step
        ("complete", None) — all slots filled; caller should search
        ("escape", None) — user bailed; clear and fall through
        ("reask", [bot_responses]) — invalid answer; re-prompt
    """
    from kisna_chatbot.processors.entity_extractor import extract_entities

    collected = _wizard_data(user_profile)
    # Drop stale occasion from older sessions
    collected.pop("occasion", None)
    step = user_profile.get("shopping_wizard_step") or get_next_step(collected)
    if step == "occasion":
        step = get_next_step(collected)
        user_profile["shopping_wizard_step"] = step

    if text and _ESCAPE_RE.search(text):
        clear_wizard_state(user_profile)
        return "escape", None

    # Interactive answers
    parsed = parse_wizard_button(messages) or parse_wizard_list(messages)
    if parsed:
        ans_step, value = parsed
        if ans_step == "occasion":
            # Stale occasion reply — skip and continue to next missing step
            next_step = get_next_step(collected)
            if next_step is None:
                user_profile["shopping_wizard_step"] = "complete"
                return "complete", None
            user_profile["shopping_wizard_step"] = next_step
            return "prompt", [build_step_prompt(next_step, collected)]
        if ans_step == "gender":
            value = _GENDER_TITLE_MAP.get(str(value).lower(), value)
        if ans_step == "material":
            value = _MATERIAL_TITLE_MAP.get(str(value).lower(), value)
        if ans_step == "fulfillment":
            value = _FULFILLMENT_TITLE_MAP.get(
                str(value).lower().replace("_", " "), value
            )
            if value not in ("ready", "mto"):
                if str(value).lower() in ("ready", "mto"):
                    pass
                elif "ready" in str(value).lower():
                    value = "ready"
                elif "mto" in str(value).lower() or "order" in str(value).lower():
                    value = "mto"
        _apply_slot(collected, ans_step, value)
    elif text:
        # Free-text for current step; also allow multi-slot extraction
        value = _parse_text_for_step(step, text) if step else None
        if value is not None and step:
            _apply_slot(collected, step, value)
        # Opportunistic fill; gender/fulfillment may overwrite when re-stated
        ents = extract_entities(text or "")
        before = dict(collected)
        seeded = seed_wizard_from_entities(ents, query=text)
        for k, v in seeded.items():
            if v is None:
                continue
            if k in ("gender", "fulfillment"):
                collected[k] = v
            elif not collected.get(k):
                collected[k] = v
        if value is None and collected == before and step:
            # Nothing parsed — re-ask
            user_profile["shopping_wizard_step"] = step
            return "reask", [build_step_prompt(step, collected)]
    else:
        if step:
            return "reask", [build_step_prompt(step, collected)]
        return "complete", None

    user_profile["shopping_wizard_data"] = collected
    next_step = get_next_step(collected)
    if next_step is None:
        user_profile["shopping_wizard_step"] = "complete"
        return "complete", None

    user_profile["shopping_wizard_step"] = next_step
    return "prompt", [build_step_prompt(next_step, collected)]


def should_start_wizard(entities: dict | None, *, confidence: float = 1.0) -> bool:
    """True when product search should enter the guided funnel.

    Smart-skip: if every slot is already known, skip the wizard entirely.
    """
    collected = seed_wizard_from_entities(entities)
    if get_next_step(collected) is None:
        return False
    return True
