"""Background sweep for the handoff-fallback batch (F10 + F11).

  F10 -- if a customer asked for a live agent and no one has picked it up
  within KISNA_HANDOFF_CALLBACK_DELAY_SECONDS (default 5 min), send a
  callback-form fallback so they are never just left waiting in silence
  (audit: 16 handoff events where the bot kept talking after promising a
  human, 108 stray turns; no ticket, no ETA, ever).

  F12 -- if an agent took a chat over and has not sent a single message 5
  minutes after the customer started waiting, send the F10 fallback form and
  hand the chat back to the bot silently (no reconnect / rating messages);
  live_agent_required stays set so the chat stays in the agent queue.

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

from datetime import datetime, timezone

from kisna_chatbot.database.collections import callback_requests, chat_messages, users
from kisna_chatbot.database.db_utils import (
    _user_filter,
    save_agent_message,
    save_system_note,
    set_takeover,
)
from kisna_chatbot.prompts.form_copy import CALLBACK_PREFORM, HANDOFF_FALLBACK
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.pubsub import pubsub
from kisna_chatbot.utils.reply_composer import compose, normalize_language
from kisna_chatbot.utils.support_hours import (
    close_of_working_day,
    is_within_working_hours,
    start_of_day_ist,
    working_seconds_between,
)
from kisna_chatbot.utils.whatsapp_window import is_window_open
from kisna_chatbot.whatsapp_functions.flow.send_callback_request_flow import (
    send_callback_request_flow,
)
from kisna_chatbot.whatsapp_functions.send_text_message import (
    send_text_message_with_retry,
)

_DEFAULT_CLIENT_ID = "kisna"
_MAX_AGE_SECONDS = 23 * 60 * 60  # stay inside WhatsApp's 24h free-form window
_DEFAULT_BATCH_LIMIT = 25

# The client's fallback copy (P3): apology, high-volume line, then the form.
_FALLBACK_TEXT = HANDOFF_FALLBACK
_FALLBACK_TEMPLATE_KEY = "handoff_fallback"
_AT_CLOSE_TEMPLATE_KEY = "handoff_at_close"


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

# Eligibility is per handoff EPISODE, not per customer. The marker used to be
# "absent = eligible", and it was only ever cleared by the 12h stale-takeover
# expiry -- so after one fallback a customer was excluded from every later
# handoff for good (24 such users in prod on 2026-09-26). Every new request
# rewrites live_agent_requested_at, so a marker older than it belongs to an
# earlier episode and no longer counts. Both fields are int(time.time()).
_MARKER_FROM_EARLIER_EPISODE = {
    "$or": [
        {"handoff_callback_sent_at": {"$exists": False}},
        {"$expr": {"$lt": ["$handoff_callback_sent_at", "$live_agent_requested_at"]}},
    ]
}
# F12 already sent this episode's form and released the takeover with
# live_agent_required still set (requested_at = taken_at): F10 must not send a
# second one. A new request from the customer rewrites requested_at.
_SILENCE_FALLBACK_NOT_THIS_EPISODE = {
    "$nor": [
        {"$expr": {"$gte": ["$human_takeover.silence_fallback_sent_at", "$live_agent_requested_at"]}},
    ]
}


def _eligible_for_fallback(user_profile: dict) -> bool:
    """Python mirror of _MARKER_FROM_EARLIER_EPISODE (plus "a request exists").

    Re-checked after the query so the episode rule holds even where the
    Mongo query is not evaluated (the test suite mocks the collection).
    """
    requested_at = user_profile.get("live_agent_requested_at")
    if requested_at is None:
        return False
    silence_sent = (user_profile.get("human_takeover") or {}).get("silence_fallback_sent_at")
    try:
        if silence_sent is not None and float(silence_sent) >= float(requested_at):
            return False
    except (TypeError, ValueError):
        pass
    sent_at = user_profile.get("handoff_callback_sent_at")
    if sent_at is None:
        return True
    try:
        return float(sent_at) < float(requested_at)
    except (TypeError, ValueError):
        return False


FALLBACK = "fallback"  # 5 working minutes passed: apology + high-volume text
AT_CLOSE = "at_close"  # desk closed first: after-hours callback form, no apology


def _fallback_kind(requested_at: int, now: int, delay: int) -> str | None:
    """Which fallback, if any, is due for an unanswered handoff (P3 5.2).

    Fires at ``delay`` WORKING seconds after the request, or at the close of
    working hours if the request is still unanswered then -- whichever comes
    first -- and never on a later day:

    * 18:25 request -> FALLBACK at 18:30 (5 working minutes, before close).
    * 18:28 request -> AT_CLOSE at 18:30 (the desk closes before 5 minutes
      accrue); nothing the next morning.
    * 09:58 request -> FALLBACK at 10:05 (the clock starts at 10:00).
    * Checked on a later IST day than the request -> None, always.

    A handoff made outside hours already got the callback form (support_
    handler) and never sets live_agent_required, so it is never a candidate.
    """
    req = datetime.fromtimestamp(int(requested_at), tz=timezone.utc)
    cur = datetime.fromtimestamp(int(now), tz=timezone.utc)
    if start_of_day_ist(cur) != start_of_day_ist(req):
        return None
    close = close_of_working_day(req)
    if close is None:
        return None
    if working_seconds_between(req, min(cur, close)) >= delay:
        return FALLBACK
    if cur >= close:
        return AT_CLOSE
    return None


def _has_pending_callback(phone: str, client_id: str, now: int | None = None) -> bool:
    """A pending callback whose slot is today (IST) or later. Past-dated ones
    are ignored: nobody ever marks a callback done, so an old booking used to
    block every later fallback for that customer (34 customers, 2026-10-05)."""
    today = start_of_day_ist(
        datetime.fromtimestamp(int(now if now is not None else time.time()), tz=timezone.utc)
    ).date().isoformat()
    return (
        callback_requests.find_one(
            {
                "client_id": client_id,
                "phone_number": phone,
                "status": "pending",
                "preferred_date": {"$gte": today},
            }
        )
        is not None
    )


def _log_skip(phone: str, reason: str, **extra) -> None:
    logger.info(
        "handoff-fallback skipped",
        extra={"phone_number": phone, "reason": reason, **extra},
    )


async def _process_one_handoff(user_profile: dict, now: int) -> bool:
    phone = user_profile.get("phone_number")
    client_id = user_profile.get("client_id") or _DEFAULT_CLIENT_ID
    if not phone:
        return False
    if not _eligible_for_fallback(user_profile):
        _log_skip(phone, "already_sent_this_episode")
        return False
    requested_at = user_profile["live_agent_requested_at"]
    kind = _fallback_kind(requested_at, now, _callback_delay_seconds())
    if kind is None:
        # Not due yet (or the day is over) -- leave the marker unarmed. Debug:
        # the sweep revisits a fresh handoff every minute until it is due.
        logger.debug("handoff-fallback not due", extra={"phone_number": phone})
        return False

    # At-most-once per episode: arm the marker atomically BEFORE sending. The
    # filter accepts only a marker absent or older than THIS episode's request,
    # so a concurrent sweep pass or the opportunistic inbound-path trigger
    # racing this one can never both get a non-None result -- once one arms it
    # to `now` (>= requested_at), the other's filter no longer matches.
    armed = users.find_one_and_update(
        {
            **_user_filter(phone, client_id),
            "$or": [
                {"handoff_callback_sent_at": {"$exists": False}},
                {"handoff_callback_sent_at": {"$lt": requested_at}},
            ],
        },
        {"$set": {"handoff_callback_sent_at": now}},
    )
    if armed is None:
        _log_skip(phone, "armed_by_another_sweep")
        return False

    if _has_pending_callback(phone, client_id, now):
        _log_skip(phone, "pending_callback_today_or_later")
        # Booked some other way already (e.g. the user did it themselves) --
        # the arm above still stands, so this phone is not re-checked again
        # for this handoff episode.
        return False

    await _send_fallback_form(user_profile, kind)
    logger.info(
        "handoff-fallback callback sent",
        extra={"phone_number": phone, "kind": kind},
    )
    return True


async def _send_fallback_form(user_profile: dict, kind: str) -> bool:
    """The F10 fallback message, also used by F12. True when the callback Flow
    or its plain-text stand-in was handed to Gupshup; a failed text send
    raises.

    ONE message: the callback form, with the text as its Flow body --
    FALLBACK: the client's apology + high-volume text; AT_CLOSE: the
    after-hours pre-form text, no apology. Sent straight to Gupshup from this
    background sweep, so it is localised here like the drop-off message:
    verbatim in English, faithful compose() otherwise, English on any failure.
    """
    phone = user_profile.get("phone_number")
    client_id = user_profile.get("client_id") or _DEFAULT_CLIENT_ID
    source, key = (
        (_FALLBACK_TEXT, _FALLBACK_TEMPLATE_KEY)
        if kind == FALLBACK
        else (CALLBACK_PREFORM, _AT_CLOSE_TEMPLATE_KEY)
    )
    language = normalize_language(user_profile.get("language") or "en")
    text = source
    if language != "en":
        text = (
            await compose(
                key, source, language=language, phone_number=phone, client_id=client_id
            )
            or source
        )

    sent_as_form = None
    try:
        sent_as_form = await asyncio.to_thread(send_callback_request_flow, phone, text)
    except Exception:
        logger.exception(
            "handoff-fallback callback flow send failed",
            extra={"phone_number": phone},
        )
    if sent_as_form is None:
        # No Flow configured or the Flow send failed: the words must still
        # reach the customer, so send them as plain text.
        await asyncio.to_thread(
            send_text_message_with_retry, phone, {"type": "text", "text": text}
        )
    try:
        await asyncio.to_thread(save_agent_message, phone, text, client_id)
    except Exception:
        logger.warning("handoff-fallback chat_history log skipped", exc_info=True)
    logger.info(
        "fallback form delivered",
        extra={"phone_number": phone, "kind": kind, "as_form": sent_as_form is not None},
    )
    return True


async def _sweep_callback_fallback(limit: int) -> int:
    now = int(time.time())
    # Only today's requests (IST): a fallback never fires on a later day, and
    # bounding the query keeps older unanswered handoffs from filling the
    # batch. No lower delay bound -- an 18:28 request is due at 18:30 (close),
    # before 5 minutes pass; _fallback_kind decides.
    today_start = int(start_of_day_ist(datetime.fromtimestamp(now, tz=timezone.utc)).timestamp())
    try:
        candidates = list(
            users.find(
                {
                    "client_id": _DEFAULT_CLIENT_ID,
                    "live_agent_required": True,
                    "live_agent_requested_at": {
                        "$lte": now,
                        "$gte": max(today_start, now - _MAX_AGE_SECONDS),
                    },
                    "human_takeover.active": {"$ne": True},
                    **_MARKER_FROM_EARLIER_EPISODE,
                    **_SILENCE_FALLBACK_NOT_THIS_EPISODE,
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
# F12: an agent took the chat over and never replied
# --------------------------------------------------------------------------

_SILENCE_MAX_ATTEMPTS = 3
_SILENCE_CLAIM_SECONDS = 120
SILENCE_NOTE = "No agent reply in 5 min, callback form sent, chat returned to bot."
SILENCE_NOTE_BOOKED = (
    "No agent reply in 5 min, customer already has a callback booked, chat returned to bot."
)


def _silence_clock_start(user_profile: dict) -> int | None:
    """When the customer started waiting on this takeover: taken_at if they
    were already waiting at Take over (asked for a person, or their last
    message was unanswered), else their first message after it. None: nobody
    is waiting (the agent opened the chat to write first) -- never fire."""
    takeover = user_profile.get("human_takeover") or {}
    taken_at = takeover.get("taken_at")
    if not taken_at:
        return None
    if takeover.get("waiting_at_start"):
        return int(taken_at)
    first = chat_messages.find_one(
        {
            "phone": user_profile.get("phone_number"),
            "client_id": user_profile.get("client_id") or _DEFAULT_CLIENT_ID,
            "role": "user",
            "ts": {"$gt": int(taken_at)},
        },
        sort=[("ts", 1)],
    )
    return int(first["ts"]) if first else None


def _agent_replied_since_claim(this_takeover: dict) -> bool:
    """Fresh read: has an agent replied (or the takeover ended) since the claim?"""
    current = users.find_one(this_takeover) or {}
    takeover = current.get("human_takeover") or {}
    return bool(takeover.get("agent_replied_at")) or not takeover.get("active")


async def _process_one_silent_takeover(user_profile: dict, now: int) -> bool:
    phone = user_profile.get("phone_number")
    client_id = user_profile.get("client_id") or _DEFAULT_CLIENT_ID
    takeover = user_profile.get("human_takeover") or {}
    if (
        not phone
        or not takeover.get("active")
        or not takeover.get("tracks_silence")
        or takeover.get("agent_replied_at")
        or takeover.get("silence_fallback_sent_at")
        or int(takeover.get("silence_fallback_attempts") or 0) >= _SILENCE_MAX_ATTEMPTS
    ):
        return False
    start = _silence_clock_start(user_profile)
    if start is None or now - start < _callback_delay_seconds():
        return False

    # Once per takeover: claim it first. The filter re-checks that the agent
    # has still not replied and that this is the same takeover (taken_at).
    this_takeover = {**_user_filter(phone, client_id), "human_takeover.taken_at": takeover["taken_at"]}
    claimed = users.find_one_and_update(
        {
            **this_takeover,
            "human_takeover.active": True,
            "human_takeover.agent_replied_at": {"$exists": False},
            "human_takeover.silence_fallback_sent_at": {"$exists": False},
            "$or": [
                {"human_takeover.silence_claim_at": {"$exists": False}},
                {"human_takeover.silence_claim_at": {"$lt": now - _SILENCE_CLAIM_SECONDS}},
            ],
        },
        {"$set": {"human_takeover.silence_claim_at": now}},
    )
    if claimed is None:
        return False

    form_sent = False
    if _has_pending_callback(phone, client_id, now):
        _log_skip(phone, "silence_fallback_pending_callback")
    else:
        kind = (
            FALLBACK
            if is_within_working_hours(datetime.fromtimestamp(now, tz=timezone.utc))
            else AT_CLOSE
        )
        delivered = False
        # Re-read immediately before sending: an agent reply that landed after
        # the claim (e.g. at 4:59) cancels the fallback -- nothing is sent and
        # the agent keeps the chat.
        if _agent_replied_since_claim(this_takeover):
            users.update_one(this_takeover, {"$unset": {"human_takeover.silence_claim_at": ""}})
            _log_skip(phone, "silence_fallback_agent_replied")
            return False
        if not is_window_open(claimed):
            logger.warning("takeover-silence fallback: 24h window closed", extra={"phone_number": phone})
        else:
            try:
                delivered = await _send_fallback_form(user_profile, kind)
            except Exception:
                logger.exception("takeover-silence fallback send failed", extra={"phone_number": phone})
        if not delivered:
            # Not sent: the agent keeps the chat and the next sweep retries.
            users.update_one(
                this_takeover,
                {
                    "$inc": {"human_takeover.silence_fallback_attempts": 1},
                    "$unset": {"human_takeover.silence_claim_at": ""},
                },
            )
            return False
        form_sent = True

    # Hand back silently: no reconnect line, no rating request.
    # live_agent_required stays set (the chat stays in the agent queue) and
    # handoff_callback_sent_at is not touched.
    users.update_one(
        this_takeover,
        {
            "$set": {
                "human_takeover.active": False,
                "human_takeover.released_at": now,
                "human_takeover.released_by": "silence_fallback",
                "human_takeover.silence_fallback_sent_at": now,
                "human_takeover.silence_form_sent": form_sent,
                "updated_at": now,
            },
            "$unset": {"human_takeover.silence_claim_at": ""},
        },
    )
    note = SILENCE_NOTE if form_sent else SILENCE_NOTE_BOOKED
    try:
        await asyncio.to_thread(save_system_note, phone, note, client_id)
        # The dashboard refetches history on "release", which shows the note.
        await pubsub.publish(phone, {"type": "release", "phone_number": phone})
    except Exception:
        logger.warning("takeover-silence note / publish skipped", exc_info=True)
    logger.info(
        "takeover-silence fallback: chat returned to bot",
        extra={"phone_number": phone, "form_sent": form_sent},
    )
    return True


async def _sweep_takeover_silence(limit: int) -> int:
    now = int(time.time())
    try:
        candidates = list(
            users.find(
                {
                    "client_id": _DEFAULT_CLIENT_ID,
                    "human_takeover.active": True,
                    "human_takeover.tracks_silence": True,
                    "human_takeover.agent_replied_at": {"$exists": False},
                    "human_takeover.silence_fallback_sent_at": {"$exists": False},
                    "human_takeover.silence_fallback_attempts": {"$not": {"$gte": _SILENCE_MAX_ATTEMPTS}},
                    "human_takeover.taken_at": {"$gte": now - _takeover_ttl_seconds()},
                }
            ).limit(limit)
        )
    except Exception:
        logger.exception("takeover-silence sweep query failed")
        return 0
    done = 0
    for user_profile in candidates:
        try:
            if await _process_one_silent_takeover(user_profile, now):
                done += 1
        except Exception:
            logger.exception(
                "takeover-silence fallback failed",
                extra={"phone_number": user_profile.get("phone_number")},
            )
    return done


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
        return {"callbacks_sent": 0, "silence_fallbacks": 0, "takeovers_expired": 0}
    _sweep_in_progress = True
    try:
        batch_limit = limit or _DEFAULT_BATCH_LIMIT
        callbacks_sent = await _sweep_callback_fallback(batch_limit)
        silence_fallbacks = await _sweep_takeover_silence(batch_limit)
        takeovers_expired = await _sweep_stale_takeovers(batch_limit)
        if callbacks_sent or silence_fallbacks or takeovers_expired:
            logger.info(
                "handoff sweep complete",
                extra={
                    "callbacks_sent": callbacks_sent,
                    "silence_fallbacks": silence_fallbacks,
                    "takeovers_expired": takeovers_expired,
                },
            )
        return {
            "callbacks_sent": callbacks_sent,
            "silence_fallbacks": silence_fallbacks,
            "takeovers_expired": takeovers_expired,
        }
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
