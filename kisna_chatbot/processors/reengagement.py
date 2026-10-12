"""Win-back nudge for customers who went quiet mid-conversation.

If a user's last turn was ``DELAY``..``MAX_AGE`` seconds ago (default 3h..23h,
i.e. still inside WhatsApp's 24-hour session window) we send ONE message: the
client's drop-off broadcast, built by ``build_dropoff_message()`` from the
campaigns live today -- verbatim in English, faithfully translated otherwise.

Isolated by design:

* default OFF (``KISNA_REENGAGE_ENABLED``);
* driven by a ``lifespan`` background loop, exactly like the Clara events sweeper
  (safe as a single loop because the container pins ``--workers 1``);
* everything is derived from the existing ``users.last_message_at`` -- the inbound
  pipeline is untouched apart from one line (``STOP`` also sets
  ``reengage_opted_out``);
* only ``reengage_*`` fields are written back, so a nudge never bumps
  ``last_message_at`` and never resets its own timer.
"""

from __future__ import annotations

import asyncio
import os
import re
import time

from kisna_chatbot.database.collections import users
from kisna_chatbot.database.db_utils import (
    _user_filter,
    get_takeover_status,
    save_agent_message,
)
from kisna_chatbot.prompts.kisna_knowledge_base import build_dropoff_message
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.reply_composer import compose, normalize_language
from kisna_chatbot.utils.whatsapp_window import is_window_open
from kisna_chatbot.whatsapp_functions.send_text_message import (
    send_text_message_with_retry,
)

_DEFAULT_CLIENT_ID = "kisna"


# --------------------------------------------------------------------------
# Config (read lazily -- env_load freezes module constants at import time)
# --------------------------------------------------------------------------

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _enabled() -> bool:
    return (os.getenv("KISNA_REENGAGE_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_enabled() -> bool:
    """Whether the win-back nudge is turned on."""
    return _enabled()


def _delay_seconds() -> int:
    return _int_env("KISNA_REENGAGE_DELAY_SECONDS", 3 * 60 * 60)


def _max_age_seconds() -> int:
    return _int_env("KISNA_REENGAGE_MAX_AGE_SECONDS", 23 * 60 * 60)


def _cooldown_seconds() -> int:
    return _int_env("KISNA_REENGAGE_COOLDOWN_SECONDS", 7 * 24 * 60 * 60)


def sweep_seconds() -> int:
    """How often the background loop runs."""
    return _int_env("KISNA_REENGAGE_SWEEP_SECONDS", 15 * 60)


def _batch_limit() -> int:
    return _int_env("KISNA_REENGAGE_BATCH_LIMIT", 25)


def _client_ids() -> list[str]:
    """Brands this nudge applies to. The copy and KB are KISNA-specific, so a
    shared-codebase sibling brand (e.g. ``nkl``) must NOT be swept in."""
    raw = (os.getenv("KISNA_REENGAGE_CLIENT_IDS") or _DEFAULT_CLIENT_ID).strip()
    return [c.strip() for c in raw.split(",") if c.strip()] or [_DEFAULT_CLIENT_ID]


# --------------------------------------------------------------------------
# Message copy -- grounded in kisna_knowledge_base.py
# --------------------------------------------------------------------------

# The message is the client's drop-off broadcast (KB v2.1): header, the
# campaign lines live today (IST), footer -- see build_dropoff_message(). It is
# the ONLY outbound text allowed to carry the making-charge percentages, so it
# is never paraphrased: English is sent verbatim, and other languages get a
# faithful compose() translation with the figures and links pinned, never a
# narrate() rewrite.
_DROPOFF_TEMPLATE_KEY = "reengage_dropoff"
# One message now, not a rotation; kept so reengage_last_line stays populated.
_DROPOFF_LINE_INDEX = 0
_URL_RE = re.compile(r"https?://\S+")
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?%")
_PINNED_FIGURES = ("1-Year", "4X", "18+")


def build_reengagement_message(
    user_profile: dict, making_charges: dict | None = None
) -> tuple[str, int]:
    """(English drop-off message for today, line index). Sync, side-effect free."""
    return build_dropoff_message(making_charges=making_charges), _DROPOFF_LINE_INDEX


async def compose_reengagement(
    user_profile: dict, making_charges: dict | None = None
) -> tuple[str, int]:
    """(text, line_index) -- verbatim in English, faithfully translated otherwise."""
    message, idx = build_reengagement_message(user_profile, making_charges)
    language = normalize_language(user_profile.get("language") or "en")
    if language == "en":
        return message, idx
    # Every percentage in the message (the live making-charge figures, GRP's
    # 25%) and the fixed figures are kept exactly as written.
    pins = (
        tuple(_URL_RE.findall(message))
        + tuple(dict.fromkeys(_PERCENT_RE.findall(message)))
        + tuple(figure for figure in _PINNED_FIGURES if figure in message)
    )
    text = await compose(
        _DROPOFF_TEMPLATE_KEY,
        message,
        language=language,
        phone_number=user_profile.get("phone_number"),
        client_id=user_profile.get("client_id") or _DEFAULT_CLIENT_ID,
        pin=pins,
    )
    return (text or message), idx


# --------------------------------------------------------------------------
# Live making-charge percentages (Clara promotions API)
# --------------------------------------------------------------------------

# The drop-off quotes the same figures as "View Offers": the highest active
# making-charge (labour) % per category. Refreshed every 2 hours like the
# promotions cache; if a refresh fails, the LAST SUCCESSFUL figures are used
# (client decision, 2026-10-12). Before any success: no percentage lines.
_OFFERS_TTL_SECONDS = 2 * 60 * 60
_OFFERS_RETRY_SECONDS = 5 * 60
_live_offers: dict = {"pct": None, "fetched_at": 0.0, "failed_at": 0.0}


def making_charges_from_promotions(promotions: list) -> dict:
    """{"diamond": 100, "gold": 100}: the highest active, percentage (not flat)
    making-charge discount per category. A category without one is absent."""
    from kisna_chatbot.processors.offers_agent import _active_promotions, _is_labour_promo

    best: dict = {}
    for promo in _active_promotions(promotions or []):
        category = (promo.get("category") or "").strip().lower()
        if category not in ("diamond", "gold") or promo.get("isFlat") or not _is_labour_promo(promo):
            continue
        raw = promo.get("discount", promo.get("disc"))
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            continue
        if pct <= 0:
            continue
        pct = int(pct) if pct.is_integer() else pct
        best[category] = max(best.get(category, 0), pct)
    return best


async def live_making_charges() -> dict:
    """Today's figures, cached; the last successful result if the API fails."""
    now = time.time()
    cached = _live_offers["pct"]
    if cached is not None and now - _live_offers["fetched_at"] < _OFFERS_TTL_SECONDS:
        return cached
    if now - _live_offers["failed_at"] < _OFFERS_RETRY_SECONDS:
        return cached or {}
    try:
        from kisna_chatbot.integrations.clara_api import get_promotions

        pct = making_charges_from_promotions(await get_promotions())
    except Exception:
        _live_offers["failed_at"] = now
        logger.warning(
            "drop-off offers fetch failed; using the last successful figures",
            extra={"have_previous": cached is not None},
            exc_info=True,
        )
        return cached or {}
    _live_offers.update(pct=pct, fetched_at=now, failed_at=0.0)
    return pct


# --------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------

def _skip_reason(user_profile: dict, now: float) -> str | None:
    last_at = user_profile.get("last_message_at")
    if not last_at:
        return "no_last_message_at"
    try:
        idle = now - float(last_at)
    except (TypeError, ValueError):
        return "bad_last_message_at"
    if idle < _delay_seconds():
        return "not_idle_enough"
    if idle > _max_age_seconds() or not is_window_open(user_profile):
        return "window_closed"
    if user_profile.get("reengage_opted_out"):
        return "opted_out"
    sent_at = user_profile.get("reengage_last_sent_at")
    if sent_at is not None:
        try:
            if float(sent_at) >= float(last_at):
                return "already_nudged_this_lull"
            if now - float(sent_at) < _cooldown_seconds():
                return "cooldown"
        except (TypeError, ValueError):
            pass
    return None


async def _process_one(user_profile: dict, now: int) -> bool:
    phone = user_profile.get("phone_number")
    client_id = user_profile.get("client_id") or _DEFAULT_CLIENT_ID
    if not phone:
        return False
    if client_id not in _client_ids():
        # The copy is KISNA-specific; never send it to a sibling brand's users.
        return False

    reason = _skip_reason(user_profile, now)
    if reason:
        logger.debug(
            "reengagement skip",
            extra={"phone_number": phone, "reason": reason},
        )
        return False

    takeover = get_takeover_status(phone, client_id)
    if takeover and takeover.get("active"):
        return False

    text, idx = await compose_reengagement(user_profile, await live_making_charges())
    if not text or not text.strip():
        return False

    # Arm the cooldown BEFORE sending. A win-back nudge is a courtesy, not a
    # critical message: at-most-once is the right semantic. If we recorded only
    # after a successful send, a misconfigured/blocked Gupshup would keep the
    # user "due" and re-attempt (LLM cost + log noise) every single sweep.
    users.update_one(
        _user_filter(phone, client_id),
        {"$set": {"reengage_last_sent_at": now, "reengage_last_line": idx}},
    )
    await asyncio.to_thread(
        send_text_message_with_retry, phone, {"type": "text", "text": text}
    )
    try:
        await asyncio.to_thread(save_agent_message, phone, text, client_id)
    except Exception:
        logger.warning("reengagement chat_history log skipped", exc_info=True)

    logger.info(
        "reengagement nudge sent",
        extra={"phone_number": phone, "line": idx},
    )
    return True


# Guards against the background loop and the manual endpoint sweeping at once:
# overlapping runs could read the same candidate before the first arms its
# cooldown and double-send. A plain flag, not asyncio.Lock — one event loop, and
# there is no await between the check and the set.
_sweep_in_progress = False


async def sweep_reengagement(limit: int | None = None) -> int:
    """Send win-back nudges to everyone who is due. Returns how many were sent.

    Never raises: a Mongo blip or one bad user must not stop the loop.
    """
    global _sweep_in_progress
    if not _enabled():
        return 0
    if _sweep_in_progress:
        logger.info("reengagement sweep already running; skipping overlap")
        return 0
    _sweep_in_progress = True
    try:
        return await _run_sweep(limit)
    finally:
        _sweep_in_progress = False


async def _run_sweep(limit: int | None) -> int:
    now = int(time.time())
    limit = limit or _batch_limit()
    delay = _delay_seconds()
    max_age = _max_age_seconds()
    cooldown = _cooldown_seconds()

    try:
        candidates = list(
            users.find(
                {
                    "client_id": {"$in": _client_ids()},
                    "last_message_at": {
                        "$lte": now - delay,
                        "$gte": now - max_age,
                    },
                    "reengage_opted_out": {"$ne": True},
                    "$or": [
                        {"reengage_last_sent_at": {"$exists": False}},
                        {"reengage_last_sent_at": {"$lt": now - cooldown}},
                    ],
                }
            )
            .sort("last_message_at", 1)
            .limit(limit)
        )
    except Exception:
        logger.exception("reengagement sweep query failed")
        return 0

    sent = 0
    for user_profile in candidates:
        try:
            if await _process_one(user_profile, now):
                sent += 1
        except Exception:
            logger.exception(
                "reengagement send failed",
                extra={"phone_number": user_profile.get("phone_number")},
            )
    if sent:
        logger.info("reengagement sweep complete", extra={"sent": sent})
    return sent
