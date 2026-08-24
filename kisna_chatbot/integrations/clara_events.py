"""
Real-time event push to the Clara backend (which forwards to Salesforce).

Complaint / callback / video-call submissions are POSTed to
``{base}/api/v1/clara/events`` using the same ``x-clara-api-key`` credential as
the catalogue API in :mod:`kisna_chatbot.integrations.clara_api`.

Delivery is a durable outbox, not a bare call:

    submit -> insert clara_events{status: pending}   (unique event_id)
           -> background task: POST once, then retry at 1s / 2s / 4s
           -> sent | pending (retry later) | failed | failed_permanent

    lifespan -> sweep_pending() every 5 min re-sends anything still due

The customer's WhatsApp reply must never wait on, or be broken by, this push,
so :func:`enqueue_event` swallows every error it can raise.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx
from pymongo.errors import DuplicateKeyError

from kisna_chatbot.database.collections import clara_events as _events
from kisna_chatbot.utils.http_log import log_http_request, log_http_response
from kisna_chatbot.utils.logger_config import logger

_PATH = "/api/v1/clara/events"
_TIMEOUT = 15.0
_SERVICE = "clara_events"
_SOURCE = "whatsapp_chatbot"

# Backoff for the immediate retry burst (the first attempt has no delay), so
# a brief blip is absorbed in-turn. Anything still failing goes to the sweeper.
_INLINE_BACKOFF = (1.0, 2.0, 4.0)
MAX_ATTEMPTS = 8
_MAX_RETRY_DELAY = 3600

# Statuses that must never be re-sent.
_TERMINAL = frozenset({"sent", "failed_permanent"})

# Transient by nature: worth another attempt.
_RETRYABLE_STATUS = frozenset({408, 425, 429})

EVENT_COMPLAINT = "complaint_submitted"
EVENT_CALLBACK = "callback_requested"
EVENT_VIDEO_CALL = "video_call_requested"


# --------------------------------------------------------------------------
# Config (read lazily: env_load freezes module constants at import time)
# --------------------------------------------------------------------------

def _enabled() -> bool:
    return (os.getenv("KISNA_CLARA_EVENTS_ENABLED") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def is_enabled() -> bool:
    """Whether the outbound event push is turned on."""
    return _enabled()


def _base_url() -> str:
    """Events base URL, falling back to the shared Clara base URL."""
    base = (os.getenv("KISNA_CLARA_EVENTS_BASE_URL") or "").strip()
    if not base:
        base = (os.getenv("KISNA_CLARA_BASE_URL") or "").strip()
    return base.rstrip("/")


def _api_key() -> str:
    return (os.getenv("CLARA_API_KEY") or "").strip()


def _headers() -> dict[str, str]:
    return {
        "x-clara-api-key": _api_key(),
        "Content-Type": "application/json",
    }


# --------------------------------------------------------------------------
# Payload builders (pure -- no I/O, so they can be tested against the contract)
# --------------------------------------------------------------------------

# The client's endpoint expects plain ASCII labels; our slot titles use
# typographic dashes for WhatsApp. Normalise on the wire only.
_DASH_TRANSLATION = str.maketrans(
    {
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "―": "-",  # horizontal bar
        "−": "-",  # minus sign
    }
)


def _ascii_dashes(text: str | None) -> str:
    return (text or "").translate(_DASH_TRANSLATION)


def _iso_utc(epoch: int | float | None) -> str:
    """Render an epoch as UTC ISO-8601 with a trailing Z."""
    if epoch is None:
        epoch = time.time()
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def _envelope(
    *,
    event_id: str,
    event_type: str,
    client_id: str,
    phone_number: str,
    customer_name: str,
    occurred_at_epoch: int | float | None,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": _iso_utc(occurred_at_epoch),
        "source": _SOURCE,
        "brand": client_id or "kisna",
        "customer": {
            "whatsapp_number": _digits(phone_number),
            "name": customer_name or "",
        },
        "data": data,
    }


def build_complaint_event(
    *,
    event_id: str,
    client_id: str,
    phone_number: str,
    customer_name: str,
    order_id: str,
    complaint_type: str,
    issue_description: str,
    occurred_at_epoch: int | float | None = None,
) -> dict[str, Any]:
    """Build a ``complaint_submitted`` payload.

    ``complaint_type`` is the opaque option id straight from the WhatsApp Flow
    (``4_Returns_Related`` etc). Those ids already match the client's contract,
    so it is passed through verbatim -- no mapping table.
    """
    return _envelope(
        event_id=event_id,
        event_type=EVENT_COMPLAINT,
        client_id=client_id,
        phone_number=phone_number,
        customer_name=customer_name,
        occurred_at_epoch=occurred_at_epoch,
        data={
            "order_id": order_id or "",
            "complaint_type": complaint_type or "",
            "issue_description": issue_description or "",
        },
    )


def build_support_request_event(
    *,
    request_id: str,
    client_id: str,
    phone_number: str,
    customer_name: str,
    mobile: str,
    request_type: str,
    preferred_date: str | None,
    preferred_time: str | None,
    preferred_time_label: str | None,
    reason: str | None = None,
    occurred_at_epoch: int | float | None = None,
) -> dict[str, Any]:
    """Build a ``callback_requested`` or ``video_call_requested`` payload.

    Video-call requests carry no ``reason`` field at all, per the contract.
    ``preferred_date`` / ``preferred_time`` must be the *final booked* slot,
    which may differ from what the customer asked for.
    """
    is_video = request_type == "video_call"

    data: dict[str, Any] = {
        "request_id": request_id,
        "request_type": "video_call" if is_video else "callback",
        "mobile": _digits(mobile),
    }
    if not is_video and reason:
        data["reason"] = reason
    data["preferred_date"] = preferred_date or ""
    data["preferred_time"] = preferred_time or ""
    data["preferred_time_label"] = _ascii_dashes(preferred_time_label)

    return _envelope(
        event_id=request_id,
        event_type=EVENT_VIDEO_CALL if is_video else EVENT_CALLBACK,
        client_id=client_id,
        phone_number=phone_number,
        customer_name=customer_name,
        occurred_at_epoch=occurred_at_epoch,
        data=data,
    )


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------

def _safe_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return (response.text or "")[:500]


async def _post(payload: dict[str, Any]) -> tuple[int | None, Any, str | None]:
    """POST one event. Never raises; returns (status_code, body, error)."""
    base = _base_url()
    if not base:
        return None, None, "missing KISNA_CLARA_BASE_URL"
    if not _api_key():
        return None, None, "missing CLARA_API_KEY"

    url = f"{base}{_PATH}"
    start = log_http_request(_SERVICE, "POST", url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, headers=_headers(), json=payload)
        body = _safe_body(response)
        log_http_response(
            _SERVICE,
            "POST",
            url,
            start=start,
            status_code=response.status_code,
            body_preview=body,
        )
        return response.status_code, body, None
    except httpx.TimeoutException:
        log_http_response(_SERVICE, "POST", url, start=start, error="timeout")
        return None, None, "timeout"
    except Exception as exc:
        log_http_response(_SERVICE, "POST", url, start=start, error=str(exc))
        return None, None, str(exc)


def _downstream_status(body: Any) -> tuple[bool | None, str | None]:
    """Read the Salesforce sub-result out of a 2xx response body.

    The endpoint answers 200 even when its own Salesforce push fails, e.g.
    {"data": {"status": "failed",
              "salesforce": {"success": false, "error": "Salesforce call failed"}}}
    We must not retry that -- the receiver has already stored the enquiry, and
    re-sending creates a duplicate -- but it is not a clean delivery either, so
    it gets recorded and logged.

    Returns (ok, error): ok is None when the body says nothing about it.
    """
    if not isinstance(body, dict):
        return None, None
    data = body.get("data")
    if not isinstance(data, dict):
        return None, None

    sf = data.get("salesforce")
    if isinstance(sf, dict) and "success" in sf:
        ok = bool(sf.get("success"))
        return ok, None if ok else str(sf.get("error") or "salesforce push failed")

    status = data.get("status")
    if isinstance(status, str):
        ok = status.lower() not in ("failed", "error")
        return ok, None if ok else f"downstream status: {status}"
    return None, None


def _classify(status: int | None, error: str | None) -> str:
    """Return 'sent' | 'retry' | 'permanent'."""
    if error is not None or status is None:
        return "retry"
    if 200 <= status < 300:
        return "sent"
    if status == 409:
        # Duplicate replay of the same event_id -- already recorded downstream.
        return "sent"
    if status >= 500 or status in _RETRYABLE_STATUS:
        return "retry"
    # Any other 4xx is a contract problem, not an outage. Retrying won't help.
    return "permanent"


def _retry_delay(attempts: int) -> int:
    return min(60 * (2 ** attempts), _MAX_RETRY_DELAY)


async def _attempt_once(doc: dict[str, Any]) -> str:
    """Send one event and record the outcome.

    Returns 'sent' | 'retry' | 'permanent'. Every attempt counts against
    MAX_ATTEMPTS, including the in-turn burst.
    """
    event_id = doc["event_id"]
    status_code, body, error = await _post(doc["payload"])
    outcome = _classify(status_code, error)
    now = int(time.time())

    if outcome == "sent":
        downstream_ok, downstream_error = _downstream_status(body)
        _events.update_one(
            {"event_id": event_id},
            {
                "$set": {
                    "status": "sent",
                    "sent_at": now,
                    "status_code": status_code,
                    "response": body,
                    "last_error": None,
                    "downstream_ok": downstream_ok,
                    "downstream_error": downstream_error,
                }
            },
        )
        if downstream_ok is False:
            # Accepted by the endpoint but their Salesforce push failed. Do NOT
            # retry: the receiver is not idempotent, so a resend duplicates it.
            logger.error(
                "Clara event accepted but downstream Salesforce push failed",
                extra={
                    "event": "clara_event_downstream_failed",
                    "event_id": event_id,
                    "event_type": doc.get("event_type"),
                    "downstream_error": downstream_error,
                    "response": body,
                },
            )
        else:
            logger.info(
                "Clara event delivered",
                extra={
                    "event": "clara_event_sent",
                    "event_id": event_id,
                    "event_type": doc.get("event_type"),
                    "status_code": status_code,
                },
            )
        return outcome

    attempts = int(doc.get("attempts", 0)) + 1
    detail = error or f"HTTP {status_code}: {str(body)[:200]}"

    if outcome == "permanent":
        new_status = "failed_permanent"
    elif attempts >= MAX_ATTEMPTS:
        new_status = "failed"
    else:
        new_status = "pending"

    update: dict[str, Any] = {
        "status": new_status,
        "attempts": attempts,
        "last_error": detail,
        "status_code": status_code,
        "last_attempt_at": now,
    }
    if new_status == "pending":
        update["next_attempt_at"] = now + _retry_delay(attempts)

    _events.update_one({"event_id": event_id}, {"$set": update})
    doc["attempts"] = attempts

    if new_status == "pending":
        logger.warning(
            "Clara event delivery failed; will retry",
            extra={
                "event": "clara_event_retry",
                "event_id": event_id,
                "attempts": attempts,
                "error": detail,
            },
        )
    else:
        logger.error(
            "Clara event delivery abandoned",
            extra={
                "event": "clara_event_failed",
                "event_id": event_id,
                "event_type": doc.get("event_type"),
                "status": new_status,
                "attempts": attempts,
                "error": detail,
                "payload": doc.get("payload"),
            },
        )
    return outcome


async def _deliver(event_id: str) -> None:
    """Send now, retrying after 1s / 2s / 4s, then leave it to the sweeper.

    Re-reads the row each pass so a concurrent sweep cannot double-send.
    """
    for delay in (None, *_INLINE_BACKOFF):
        if delay is not None:
            await asyncio.sleep(delay)
        try:
            doc = _events.find_one({"event_id": event_id})
        except Exception:
            logger.exception(
                "Clara event lookup failed",
                extra={"event": "clara_event_lookup_error", "event_id": event_id},
            )
            return
        if not doc or doc.get("status") in _TERMINAL or doc.get("status") == "failed":
            return
        try:
            if await _attempt_once(doc) != "retry":
                return
        except Exception:
            logger.exception(
                "Clara event delivery raised",
                extra={"event": "clara_event_error", "event_id": event_id},
            )
            return


# --------------------------------------------------------------------------
# Outbox
# --------------------------------------------------------------------------

_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """Fire-and-forget, holding a strong ref so the task is not GC'd mid-flight."""
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # No running loop (sync context / shutdown): drop it, the sweeper will retry.
        coro.close()
        return
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


async def enqueue_event(payload: dict[str, Any]) -> None:
    """Persist an event to the outbox and start delivering it.

    Never raises: a Mongo outage or a misconfigured endpoint must not break the
    customer's confirmation message.
    """
    try:
        if not _enabled():
            return

        event_id = payload.get("event_id")
        if not event_id:
            logger.error(
                "Clara event missing event_id; dropped",
                extra={"event": "clara_event_invalid", "payload": payload},
            )
            return

        now = int(time.time())
        try:
            _events.insert_one(
                {
                    "event_id": event_id,
                    "event_type": payload.get("event_type"),
                    "client_id": payload.get("brand"),
                    "phone_number": (payload.get("customer") or {}).get(
                        "whatsapp_number", ""
                    ),
                    "payload": payload,
                    "status": "pending",
                    "attempts": 0,
                    "last_error": None,
                    "status_code": None,
                    "response": None,
                    "created_at": now,
                    "next_attempt_at": now,
                    "sent_at": None,
                }
            )
        except DuplicateKeyError:
            # Already queued -- do not send twice.
            return

        _spawn(_deliver(event_id))
    except Exception:
        logger.exception(
            "Failed to enqueue Clara event",
            extra={
                "event": "clara_event_enqueue_error",
                "event_id": payload.get("event_id") if isinstance(payload, dict) else None,
            },
        )


async def sweep_pending(limit: int = 50) -> int:
    """Re-send outbox rows that are due. Returns how many were attempted."""
    if not _enabled():
        return 0

    now = int(time.time())
    try:
        due: Iterable[dict[str, Any]] = list(
            _events.find(
                {
                    "status": "pending",
                    "attempts": {"$lt": MAX_ATTEMPTS},
                    "next_attempt_at": {"$lte": now},
                }
            )
            .sort("next_attempt_at", 1)
            .limit(limit)
        )
    except Exception:
        logger.exception(
            "Clara events sweep query failed",
            extra={"event": "clara_event_sweep_error"},
        )
        return 0

    attempted = 0
    for doc in due:
        try:
            await _attempt_once(doc)
            attempted += 1
        except Exception:
            logger.exception(
                "Clara event sweep delivery raised",
                extra={
                    "event": "clara_event_sweep_error",
                    "event_id": doc.get("event_id"),
                },
            )
    if attempted:
        logger.info(
            "Clara events swept",
            extra={"event": "clara_event_sweep", "attempted": attempted},
        )
    return attempted
