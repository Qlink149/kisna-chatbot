"""WhatsApp 24-hour customer care window helpers."""

import time

WINDOW_OPEN_HOURS = 23


def is_window_open(user_profile: dict | None) -> bool:
    """True when the user's last inbound message was within the open window."""
    ts = (user_profile or {}).get("last_message_at")
    if not ts:
        return False
    try:
        elapsed = time.time() - float(ts)
    except (TypeError, ValueError):
        return False
    return elapsed < WINDOW_OPEN_HOURS * 3600
