"""WhatsApp 24-hour customer care window helpers."""

import time

WINDOW_OPEN_HOURS = 23
WINDOW_EXPIRED_DETAIL = "WhatsApp 24-hour conversation window has expired"


def last_inbound_ts(user_profile: dict | None) -> float | None:
    """When the customer last messaged us -- the only clock Meta's window uses.

    ``last_inbound_at`` is written solely on the customer-inbound path.
    ``last_message_at`` is the fallback for profiles that predate it; it is also
    inbound-only today, so the fallback is no worse than the old behaviour.
    ``updated_at`` is deliberately NOT used: agent messages, release and the
    sweeps refresh it, which is how dashboard sends kept going out after Meta
    had already closed the window (error 131047).
    """
    profile = user_profile or {}
    for key in ("last_inbound_at", "last_message_at"):
        value = profile.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def is_window_open(user_profile: dict | None) -> bool:
    """True when the user's last inbound message was within the open window."""
    ts = last_inbound_ts(user_profile)
    if ts is None:
        return False
    return time.time() - ts < WINDOW_OPEN_HOURS * 3600
