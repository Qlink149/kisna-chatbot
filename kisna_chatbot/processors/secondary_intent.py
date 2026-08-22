"""Answer the SECOND thing a customer asked in one message.

A single message often carries two requests — "gold ring dikhao aur store bhi
batao". Only the primary one was ever answered; the other was dropped with no
acknowledgement at all, in every language tested. The classifier now reports it
as ``secondary_intent`` and this module deals with it.

Two rules shape everything here:

* **Never start a second flow.** This runs AFTER the primary pipeline has
  already produced a reply and set up session state. Touching
  ``service_selected``, ``awaiting_store_pincode`` or the wizard would have the
  two halves fighting over the same keys — which is exactly why a full second
  pipeline run was rejected in favour of this.
* **Never ask a second question.** The primary reply usually ENDS in a question
  ("Who is it for?"). Appending another one gives the customer two things to
  answer in one WhatsApp turn, which is worse than what we started with. So a
  secondary that would need its own input is acknowledged, not pursued.

That splits the supported intents in two: ``offers`` and ``gold_rate`` are
stateless single-message lookups and are answered outright; ``store_info`` and
``general`` need a location or a conversation, so they get one line promising
to come back to it.
"""

from kisna_chatbot.utils.logger_config import logger

# Answered in full — a self-contained lookup that needs nothing from the user.
_ANSWERABLE = ("offers", "gold_rate")

# Acknowledged only — answering properly would need input we would have to ask
# for, and the primary reply has usually just asked a question of its own.
_ACKNOWLEDGE_ONLY = {
    "store_info": (
        "And about our stores — tell me your city or pincode whenever you're "
        "ready and I'll find the nearest one 📍"
    ),
    "general": (
        "I'll answer your other question too — just send it again on its own "
        "and I'll go into detail 😊"
    ),
}


async def append_secondary_answer(data: dict) -> dict:
    """Append the second request's answer, or an acknowledgement of it.

    Best-effort by design: this runs after a reply the customer is already
    entitled to, so any failure here must leave that reply untouched rather
    than take the turn down with it.
    """
    secondary = data.get("secondary_intent")
    if not secondary:
        return data

    responses = data.get("bot_response")
    if not isinstance(responses, list) or not responses:
        # Nothing to append to — the primary did not produce a reply, so the
        # secondary is not the interesting problem on this turn.
        return data

    phone_number = data.get("phone_number")
    try:
        extra = await _build_secondary_response(data, secondary)
    except Exception:
        logger.warning(
            "secondary intent append failed — primary reply kept",
            extra={"phone_number": phone_number, "secondary_intent": secondary},
            exc_info=True,
        )
        return data

    if not extra:
        return data

    responses.extend(extra)
    logger.info(
        "Answered a secondary intent",
        extra={
            "phone_number": phone_number,
            "primary": data.get("classified_category"),
            "secondary_intent": secondary,
            "answered": secondary in _ANSWERABLE,
        },
    )
    return data


async def _build_secondary_response(data: dict, secondary: str) -> list[dict]:
    if secondary == "gold_rate":
        from kisna_chatbot.processors.gold_rate_handler import (
            build_gold_rate_bot_response,
        )

        return await build_gold_rate_bot_response(data.get("app_state")) or []

    if secondary == "offers":
        return await _offers_response(data)

    text = _ACKNOWLEDGE_ONLY.get(secondary)
    if not text:
        return []
    # _compose so it is mirrored into the customer's language like every other
    # canned line — this must not arrive in English after a Tamil reply.
    return [{"type": "text", "text": text, "_compose": f"secondary_{secondary}"}]


async def _offers_response(data: dict) -> list[dict]:
    """Current offers as one message, reusing the offers agent's own builder."""
    from kisna_chatbot.integrations.clara_api import get_promotions
    from kisna_chatbot.processors.offers_agent import (
        _build_bot_response,
        _build_offers_text,
    )
    from kisna_chatbot.utils.clara_cache import get_cached_promotions

    promotions = await get_cached_promotions(data.get("app_state"))
    if not promotions:
        promotions = await get_promotions() or []
    if not promotions:
        return []
    text = _build_offers_text(promotions)
    if not text:
        return []
    # Reuse the offers agent's own builder rather than wrapping the text
    # by hand: it carries the "_compose" tag, and without that the whole
    # offers table arrived in English at the end of a Hindi reply.
    return _build_bot_response(text)
