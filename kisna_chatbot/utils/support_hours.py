"""Support availability — hours, holidays, and status checks (IST)."""

from __future__ import annotations

import os
from datetime import datetime, time
from functools import lru_cache
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

WEEKDAY_OPEN = time(10, 0)
WEEKDAY_CLOSE = time(18, 30)
SAT_OPEN = time(10, 0)
SAT_CLOSE = time(16, 0)

# Empty until client supplies official holiday list — ad-hoc closures via env only.
SUPPORT_HOLIDAYS: dict[str, str] = {}


def format_support_hours_text() -> str:
    """Human-readable support hours for customer-facing messages."""
    return "10:00am–6:30pm Mon–Fri, 10am–4pm Sat IST"


@lru_cache(maxsize=1)
def _env_holidays() -> dict[str, str]:
    raw = (os.getenv("KISNA_SUPPORT_HOLIDAYS") or "").strip()
    if not raw:
        return {}
    holidays: dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        if ":" in piece:
            date_str, name = piece.split(":", 1)
            holidays[date_str.strip()] = name.strip()
        else:
            holidays[piece] = "Holiday"
    return holidays


def _merged_holidays() -> dict[str, str]:
    merged = dict(SUPPORT_HOLIDAYS)
    merged.update(_env_holidays())
    return merged


def _is_within_hours(now: datetime) -> bool:
    weekday = now.weekday()  # Mon=0 … Sun=6
    current = now.time()
    if weekday == 6:
        return False
    if weekday == 5:
        return SAT_OPEN <= current <= SAT_CLOSE
    return WEEKDAY_OPEN <= current <= WEEKDAY_CLOSE


def get_support_status(now: datetime | None = None) -> dict:
    """
    Return support availability status.

    One of:
      {"status": "open"}
      {"status": "closed_holiday", "holiday": "..."}
      {"status": "closed_hours"}
    """
    if now is None:
        now = datetime.now(IST)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    date_key = now.strftime("%Y-%m-%d")
    holidays = _merged_holidays()
    if date_key in holidays:
        return {"status": "closed_holiday", "holiday": holidays[date_key]}

    if not _is_within_hours(now):
        return {"status": "closed_hours"}

    return {"status": "open"}


def clear_support_hours_cache() -> None:
    """Clear cached env holidays (for tests)."""
    _env_holidays.cache_clear()
