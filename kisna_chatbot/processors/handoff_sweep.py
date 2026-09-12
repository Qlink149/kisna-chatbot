"""Background sweep for the handoff-fallback batch (F10 + F11).

  F10 -- if a customer asked for a live agent and no one has picked it up
  within KISNA_HANDOFF_CALLBACK_DELAY_SECONDS (default 5 min), send a
  callback-form fallback so they are never just left waiting in silence
  (audit: 16 handoff events where the bot kept talking after promising a
  human, 108 stray turns; no ticket, no ETA, ever).

  F11 -- if a human_takeover has sat active for KISNA_TAKEOVER_TTL_SECONDS
  (default 12h) with no resolution, auto-expire it so the bot resumes
  instead of staying muted for a customer nobody is actually attending
  (audit: 48 users in human_takeover.active=True, only 23 ever resolved).

Same single-loop pattern as reengagement.py / clara_events, driven by
main.py's lifespan, plus an opportunistic call on the inbound path so the
fallback still fires if the background loop is somehow not running.
"""

from __future__ import annotations

import asyncio
import os
import time

from kisna_chatbot.database.collections import callback_requests, users
from kisna_chatbot.database.db_utils import _user_filter, save_agent_message, set_takeover
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.reply_composer import narrate
from kisna_chatbot.whatsapp_functions.flow.send_callback_request_flow import (
    send_callback_request_flow,
)
from kisna_chatbot.whatsapp_functions.send_text_message import (
    send_text_message_with_retry,
)

_DEFAULT_CLIENT_ID = "kisna"
_MAX_AGE_SECONDS = 23 * 60 * 60  # stay inside WhatsApp's 24h free-form window
_DEFAULT_BATCH_LIMIT = 25

_FALLBACK_TEXT = (
    "Our team hasn't picked this up yet — I'm sorry for the wait. "
    "Let me book you a callback instead so you're not left hanging."
)


# --------------------------------------------------------------------------
# Config (read lazily -- env_load freezes module constants at import time)
# --------------------------------------------------------------------------

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def sweep_seconds() -> int:
    return _int_env("KISNA_HANDOFF_SWEEP_SECONDS", 60)


def _callback_delay_seconds() -> int:
    return _int_env("KISNA_HANDOFF_CALLBACK_DELAY_SECONDS", 300)


def _takeover_ttl_seconds() -> int:
    return _int_env("KISNA_TAKEOVER_TTL_SECONDS", 12 * 60 * 60)


# --------------------------------------------------------------------------
# F10: callback fallback when no agent has picked up a handoff
# --------------------------------------------------------------------------

def _has_pending_callback(phone: str, client_id: str) -> bool:
    return (
        callback_requests.find_one(
            {"client_id": client_id, "phone_number": phone, "status": "pending"}
        )
        is not None
    )


async def _process_one_handoff(user_profile: dict, now: int) -> bool:
    phone = user_profile.get("phone_number")
    client_id = user_profile.get("client_id") or _DEFAULT_CLIENT_ID
    if not phone:
        return False

    # At-most-once: arm the marker atomically BEFORE sending. The filter
    # requires the field to be absent, so a concurrent sweep pass or the
    # opportunistic inbound-path trigger racing this one can never both get
    # a non-None result -- exactly one of them "wins" the send.
    armed = users.find_one_and_update(
        {**_user_filter(phone, client_id), "handoff_callback_sent_at": {"$exists": False}},
        {"$set": {"handoff_callback_sent_at": now}},
    )
    if armed is None:
        return False

    if _has_pending_callback(phone, client_id):
        # Booked some other way already (e.g. the user did it themselves) --
        # the arm above still stands, so this phone is not re-checked again
        # for this handoff episode.
        return False

    # Sent straight to Gupshup from this background sweep, never through the
    # bot_response / localize_bot_responses pipeline -- so it must already be
    # in the customer's language before it leaves here, same as
    # reengagement.compose_reengagement. Falls back to the English original on
    # any narrate() failure.
    language = user_profile.get("language") or "en"
    text = await narrate(_FALLBACK_TEXT, language=language, phone_number=phone, client_id=client_id)
    text = text or _FALLBACK_TEXT

    await asyncio.to_thread(
        send_text_message_with_retry, phone, {"type": "text", "text": text}
    )
    try:
        await asyncio.to_thread(send_callback_request_flow, phone)
    except Exception:
        logger.exception(
            "handoff-fallback callback flow send failed",
            extra={"phone_number": phone},
        )
    try:
        await asyncio.to_thread(save_agent_message, phone, text, client_id)
    except Exception:
        logger.warning("handoff-fallback chat_history log skipped", exc_info=True)

    logger.info("handoff-fallback callback sent", extra={"phone_number": phone})
    return True


async def _sweep_callback_fallback(limit: int) -> int:
    now = int(time.time())
    delay = _callback_delay_seconds()
    try:
        candidates = list(
            users.find(
                {
                    "client_id": _DEFAULT_CLIENT_ID,
                    "live_agent_required": True,
                    "live_agent_requested_at": {
                        "$lte": now - delay,
                        "$gte": now - _MAX_AGE_SECONDS,
                    },
                    "human_takeover.active": {"$ne": True},
                    "handoff_callback_sent_at": {"$exists": False},
                }
            )
            .sort("live_agent_requested_at", 1)
            .limit(limit)
        )
    except Exception:
        logger.exception("handoff callback-fallback sweep query failed")
        return 0

    sent = 0
    for user_profile in candidates:
        try:
            if await _process_one_handoff(user_profile, now):
                sent += 1
        except Exception:
            logger.exception(
                "handoff-fallback send failed",
                extra={"phone_number": user_profile.get("phone_number")},
            )
    return sent


# --------------------------------------------------------------------------
# F11: auto-expire a stale human_takeover
# --------------------------------------------------------------------------

async def _process_one_takeover_expiry(user_profile: dict) -> bool:
    phone = user_profile.get("phone_number")
    client_id = user_profile.get("client_id") or _DEFAULT_CLIENT_ID
    if not phone:
        return False
    await asyncio.to_thread(set_takeover, phone, False, client_id)
    # Clear the handoff-callback arm too, so a FUTURE handoff for this same
    # phone can re-arm its own 5-minute timer instead of staying permanently
    # "already sent" from an episode that's now over.
    users.update_one(
        _user_filter(phone, client_id), {"$unset": {"handoff_callback_sent_at": ""}}
    )
    logger.info("stale human_takeover auto-expired", extra={"phone_number": phone})
    return True


async def _sweep_stale_takeovers(limit: int) -> int:
    now = int(time.time())
    ttl = _takeover_ttl_seconds()
    try:
        candidates = list(
            users.find(
                {
                    "client_id": _DEFAULT_CLIENT_ID,
                    "human_takeover.active": True,
                    "human_takeover.taken_at": {"$lte": now - ttl},
                }
            ).limit(limit)
        )
    except Exception:
        logger.exception("stale takeover sweep query failed")
        return 0

    expired = 0
    for user_profile in candidates:
        try:
            if await _process_one_takeover_expiry(user_profile):
                expired += 1
        except Exception:
            logger.exception(
                "takeover auto-expire failed",
                extra={"phone_number": user_profile.get("phone_number")},
            )
    return expired


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

# Guards against the background loop and the opportunistic inbound-path
# trigger sweeping at once -- same reasoning as reengagement.py's flag: one
# event loop, no await between the check and the set.
_sweep_in_progress = False


async def sweep_handoff(limit: int | None = None) -> dict:
    """Run both passes. Returns counts. Never raises."""
    global _sweep_in_progress
    if _sweep_in_progress:
        return {"callbacks_sent": 0, "takeovers_expired": 0}
    _sweep_in_progress = True
    try:
        batch_limit = limit or _DEFAULT_BATCH_LIMIT
        callbacks_sent = await _sweep_callback_fallback(batch_limit)
        takeovers_expired = await _sweep_stale_takeovers(batch_limit)
        if callbacks_sent or takeovers_expired:
            logger.info(
                "handoff sweep complete",
                extra={
                    "callbacks_sent": callbacks_sent,
                    "takeovers_expired": takeovers_expired,
                },
            )
        return {"callbacks_sent": callbacks_sent, "takeovers_expired": takeovers_expired}
    finally:
        _sweep_in_progress = False


def trigger_opportunistic_sweep() -> None:
    """Fire-and-forget sweep call from the inbound message path, so the
    fallback still fires even if the background lifespan loop is somehow not
    running (e.g. a future serverless deployment). Cheap: a small, indexed,
    limited Mongo query -- safe to call on every inbound message.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    def _log_if_failed(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.warning("opportunistic handoff sweep failed", exc_info=exc)

    task = loop.create_task(sweep_handoff(limit=5))
    task.add_done_callback(_log_if_failed)
