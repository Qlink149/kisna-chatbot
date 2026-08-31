"""Confirm-before-search recap.

Every sticky/inherited slot is read back to the user before it reaches the
Clara API, so a filter that bled in from an earlier turn (gold, "for her",
an old budget) is visible and rejectable instead of silently shaping results.
"""

from __future__ import annotations

import json
import os
import re
import time

CONFIRM_MSGID = "confirm$search"
CONFIRM_YES_MSGID = "confirm$search$yes"
CONFIRM_NO_MSGID = "confirm$search$no"

PENDING_SEARCH_KEY = "pending_search"
AWAITING_CORRECTION_KEY = "awaiting_search_correction"

_YES_TITLES = frozenset({"yes, show me", "yes", "yeah", "correct"})
_NO_TITLES = frozenset({"no, change it", "no", "change"})

_YES_TEXT_RE = re.compile(
    r"^\s*(?:"
    r"(?:yes|yeah|yep|yup|ya|yaa|sure|ok|okay|okk|k|correct|right|"
    r"perfect|sahi|sahi hai|haan|han|haa|ha|hanji|ji|ji haan|thik|"
    r"theek|theek hai|thik hai|bilkul|go ahead)"
    r"(?:\s*,?\s*(?:show me|show|proceed))?"
    r"|"
    r"(?:show me|show|proceed)"
    r")\s*[!.]*\s*$",
    re.I,
)

_NO_TEXT_RE = re.compile(
    r"^\s*(?:"
    r"(?:no|nope|nah|na|nahi|nahin|galat|wrong|not correct|incorrect|"
    r"change|edit)"
    r"(?:\s*,?\s*(?:change it|change))?"
    r"|"
    r"(?:change it)"
    r")\s*[!.]*\s*$",
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


def _metal_phrase(entities: dict) -> str | None:
    """Karat/colour/material as one natural phrase: '18kt rose gold',
    'white gold', '14kt diamond', or plain 'gold'/'diamond'/'gemstone'.

    karat and metal_colour are both real, resolvable filters (Clara IDs, not
    guesses) that used to reach the search silently -- the user had no way
    to see "18kt" or "rose gold" was applied before results came back.
    """
    karat = entities.get("karat")
    colour = entities.get("metal_colour")
    material = entities.get("material_type")
    bits: list[str] = []
    if karat:
        bits.append(str(karat).lower())
    if colour:
        bits.append(str(colour).lower())
        bits.append("gold")
    elif material:
        bits.append(str(material).replace("_", " "))
    return " ".join(bits) if bits else None


def _collection_phrase(entities: dict) -> str | None:
    collection = entities.get("collection")
    if not collection:
        return None
    label = str(collection).strip().title()
    if not label.lower().endswith("collection"):
        label = f"{label} Collection"
    return f"in {label}"


def _category_phrase(entities: dict) -> str | None:
    from kisna_chatbot.processors.product_search_agent_v3 import (
        _humanize_category_label,
    )

    # "chain" is stored as category="necklace" + clara_category_override="chain";
    # the recap must read "chains" (mirrors entity_extractor.build_search_context).
    override = entities.get("clara_category_override")
    if override:
        categories = [override]
    else:
        categories = entities.get("categories") or []
        if not categories and entities.get("category"):
            categories = [entities["category"]]
    labels = [_humanize_category_label(str(c)) for c in categories if c]
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return f"{', '.join(labels[:-1])} and {labels[-1]}"


def _title_phrase(entities: dict) -> str | None:
    """Bracket the customer's own product name so the recap stays specific.

    Skipped when the title just echoes the category (e.g. title="chains",
    category="chain") -- title_redundant_with_category already exists for
    exactly this, see build_search_context's identical guard.
    """
    from kisna_chatbot.processors.entity_extractor import (
        title_redundant_with_category,
    )

    title = entities.get("title")
    if not title or not str(title).strip():
        return None
    if title_redundant_with_category(entities):
        return None
    return f'("{str(title).strip().title()}")'


def build_search_recap(entities: dict) -> str:
    """Plain-language read-back of the filters a search will use."""
    entities = entities or {}
    parts: list[str] = []

    metal = _metal_phrase(entities)
    if metal:
        parts.append(metal)

    category = _category_phrase(entities)
    if not category:
        from kisna_chatbot.utils.rakhi_season import recap_product_word

        category = recap_product_word(entities)
    parts.append(category or "jewellery")

    title_phrase = _title_phrase(entities)
    if title_phrase:
        parts.append(title_phrase)

    gender = _GENDER_LABELS.get(str(entities.get("gender") or "").lower())
    if gender:
        parts.append(gender)

    collection = _collection_phrase(entities)
    if collection:
        parts.append(collection)

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
        for key in (
            "material_type",
            "gender",
            "min_price",
            "max_price",
            "karat",
            "metal_colour",
            "collection",
        )
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


def is_confirm_interactive(messages: dict) -> bool:
    """True when this inbound is the search-recap Yes/No quick-reply."""
    reply = _button_reply(messages)
    if reply is None:
        return False
    msgid = _button_msgid(str(reply.get("id") or ""))
    if msgid.startswith("confirm$"):
        return True
    title = (reply.get("title") or "").strip().lower()
    return title in {"yes, show me", "no, change it"}


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
        if msgid == CONFIRM_MSGID or msgid.startswith("confirm$") or title in _YES_TITLES or title in _NO_TITLES:
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


# Deliberately tiny and separate, in the same shape as the escape gate in
# classifier.py: it answers ONE question, so it works in every language rather
# than in the languages someone remembered to list.
#
# WHY IT EXISTS. _YES_TEXT_RE below is Latin-only and matches 0 of 12 native
# affirmatives -- हाँ, होय, હા, ஆம், అవును, হ্যাঁ, ಹೌದು, അതെ, ਹਾਂ, ହଁ, جی ہاں,
# হয়. parse_confirm_reply returned None for all of them, the turn re-classified
# as action="more", and the recap re-rendered -- forever. A customer typing in
# their own script could not complete a search at all; only tapping the button
# escaped. Adding twelve more words would have left the thirteenth language
# broken, which is the failure this codebase keeps rediscovering.
_CONFIRM_GATE_PROMPT = """A jewellery shop's WhatsApp bot read a search back to the
customer and asked "Does this sound correct?".

WHAT WAS READ BACK:
{recap}

Decide what the customer's reply is doing. Answer with exactly one word:

yes      - they agree / approve / want to proceed, in ANY language or script
           ("haan", "हाँ", "होय", "ஆம்", "ಹೌದು", "جی ہاں", "ok", "go ahead",
           "correct", "that's right", a thumbs-up)
no       - they disagree, or want to change something about it
neither  - it is not an answer to that question at all: a different product, a
           store, an order, a return, a price question, a greeting

If it could be either yes or no, answer "neither" — a wrong guess sends the
customer a search they did not ask for.
Reply with the single word only. No punctuation, no explanation."""


async def confirm_reply_gate(
    user_message: str,
    recap: str,
    *,
    client_id: str = "kisna",
    phone_number: str | None = None,
) -> str | None:
    """"yes" / "no" / None. None means undecided — the caller keeps its own verdict.

    Never makes an outage worse than no gate: any failure returns None and the
    turn behaves exactly as it did before this existed.
    """
    from kisna_chatbot.ai.factory import complete_chat
    from kisna_chatbot.ai.types import AgentName
    from kisna_chatbot.utils.logger_config import logger

    try:
        raw = await complete_chat(
            agent=AgentName.CLASSIFIER,
            agent_display_name="Confirm Gate",
            instruction=_CONFIRM_GATE_PROMPT.format(recap=recap or "(the search)"),
            messages=[{"role": "user", "content": user_message}],
            max_output_tokens=8,
            phone_number=phone_number,
            client_id=client_id,
        )
    except Exception:
        logger.warning(
            "Confirm gate unavailable — keeping the regex verdict",
            extra={"phone_number": phone_number},
            exc_info=True,
        )
        return None
    verdict = (raw or "").strip().strip(".\"'").lower()
    if verdict.startswith("yes"):
        return "yes"
    if verdict.startswith("no"):
        return "no"
    return None


async def parse_confirm_reply_async(
    messages: dict,
    text: str | None = None,
    *,
    recap: str = "",
    client_id: str = "kisna",
    phone_number: str | None = None,
) -> str | None:
    """parse_confirm_reply, with an LLM gate behind it for non-Latin replies.

    The Latin regex stays the fast path and costs nothing. The gate only fires
    when the regex found nothing AND the message is in a script it cannot read,
    so English and romanized traffic are unaffected.
    """
    from kisna_chatbot.utils.script_detect import has_non_latin_letters

    verdict = parse_confirm_reply(messages, text)
    if verdict is not None:
        return verdict
    if not (text or "").strip() or not has_non_latin_letters(text):
        return None
    return await confirm_reply_gate(
        text, recap, client_id=client_id, phone_number=phone_number
    )


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
    # Recap wait counts as an active search session. Without this stamp,
    # a stale last_search_at from an earlier browse expires the recap
    # before Yes/No can run.
    user_profile["last_search_at"] = int(time.time())


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
