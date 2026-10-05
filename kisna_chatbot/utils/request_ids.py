"""Generate human-readable request IDs for callback / video-call requests."""

from __future__ import annotations

import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def generate_request_id(prefix: str = "CB") -> str:
    """Return ID like KIS-CB-20260710-A1B2.

    The suffix always starts with a letter (A-F): an all-digit suffix made
    "20261002-0848" read as a phone number, so WhatsApp linked it."""
    date_part = datetime.now(IST).strftime("%Y%m%d")
    suffix = secrets.choice("ABCDEF") + secrets.token_hex(2).upper()[:3]
    return f"KIS-{prefix}-{date_part}-{suffix}"
