"""Support availability — hours, holidays, and status checks (IST)."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

WEEKDAY_OPEN = time(10, 0)
WEEKDAY_CLOSE = time(18, 30)
SAT_OPEN = time(10, 0)
SAT_CLOSE = time(16, 0)

# Company holiday calendar (YYYY-MM-DD → display name).
# Empty until client supplies the official list — fill entries here.
SUPPORT_HOLIDAYS: dict[str, str] = {}


def format_support_hours_text() -> str:
    """Human-readable support hours for customer-facing messages."""
    return "10:00am–6:30pm Mon–Fri, 10am–4pm Sat IST"


def _to_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def _date_key(day: date | datetime | str) -> str:
    if isinstance(day, str):
        return day.strip()
    if isinstance(day, datetime):
        day = _to_ist(day).date()
    return day.isoformat()


def is_holiday(day: date | datetime | str) -> bool:
    """True if the given calendar day is a company holiday."""
    return _date_key(day) in SUPPORT_HOLIDAYS


def holiday_name(day: date | datetime | str) -> str | None:
    """Return holiday display name, or None if not a holiday."""
    return SUPPORT_HOLIDAYS.get(_date_key(day))


def is_working_day(day: date | datetime | str) -> bool:
    """True for Mon–Sat that are not company holidays (Sunday always closed)."""
    if isinstance(day, str):
        try:
            parsed = datetime.strptime(day.strip(), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return False
    elif isinstance(day, datetime):
        parsed = _to_ist(day).date()
    else:
        parsed = day

    if parsed.weekday() == 6:  # Sunday
        return False
    return not is_holiday(parsed)


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
    now = _to_ist(now)
    date_key = now.strftime("%Y-%m-%d")
    if date_key in SUPPORT_HOLIDAYS:
        return {"status": "closed_holiday", "holiday": SUPPORT_HOLIDAYS[date_key]}

    if not _is_within_hours(now):
        return {"status": "closed_hours"}

    return {"status": "open"}
