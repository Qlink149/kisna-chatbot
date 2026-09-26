"""Support availability — hours, holidays, and status checks (IST).

``is_within_working_hours`` is the ONE function that decides "inside working
hours" for the whole codebase: Mon–Fri 10:00–18:30 IST, Sat 10:00–16:00 IST,
Sunday closed, holidays closed. Every branch that needs that answer (handoff
vs offline, confirmation variants, the 5-minute fallback gate) calls it or
``get_support_status`` / ``working_seconds_between``, which are built on it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

WEEKDAY_OPEN = time(10, 0)
WEEKDAY_CLOSE = time(18, 30)
SAT_OPEN = time(10, 0)
SAT_CLOSE = time(16, 0)

# Company holiday calendar (YYYY-MM-DD → display name).
#
# PROVISIONAL: the 2026-11 entries and everything from 2026-12-25 on are the
# standard Indian national holidays, added so the calendar cannot silently run
# out (it previously ended 2026-11-11). Replace with Kisna's own holiday list
# when it arrives. tests/test_p3_forms_fallback_routing.py fails when the last
# entry is within 60 days of today, so the list must be extended before then.
SUPPORT_HOLIDAYS: dict[str, str] = {
    "2026-09-14": "Store Holiday",
    "2026-10-02": "Gandhi Jayanti",
    "2026-10-20": "Store Holiday",
    "2026-11-08": "Diwali",
    "2026-11-09": "Day after Diwali",
    "2026-11-10": "Store Holiday",
    "2026-11-11": "Store Holiday",
    "2026-12-25": "Christmas",
    "2027-01-01": "New Year's Day",
    "2027-01-26": "Republic Day",
    "2027-03-22": "Holi",
    "2027-08-15": "Independence Day",
    "2027-10-02": "Gandhi Jayanti",
    "2027-10-09": "Dussehra",
    "2027-10-29": "Diwali",
    "2027-10-30": "Day after Diwali",
    "2027-12-25": "Christmas",
}


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


def _open_window(day: date) -> tuple[time, time] | None:
    """(open, close) for a working day, else None. Close is exclusive:
    18:30:00 on a weekday is already closed."""
    if not is_working_day(day):
        return None
    if day.weekday() == 5:
        return SAT_OPEN, SAT_CLOSE
    return WEEKDAY_OPEN, WEEKDAY_CLOSE


def is_within_working_hours(now: datetime | None = None) -> bool:
    """THE working-hours decision: Mon–Fri 10:00–18:30 IST, Sat 10:00–16:00 IST,
    Sunday closed, holidays closed. Open at 10:00:00; closed at 18:30:00 /
    16:00:00 (exclusive). A naive ``now`` is taken as IST."""
    current = _to_ist(now)
    window = _open_window(current.date())
    if window is None:
        return False
    open_at, close_at = window
    return open_at <= current.time() < close_at


def get_support_status(now: datetime | None = None) -> dict:
    """
    Return support availability status.

    One of:
      {"status": "open"}
      {"status": "closed_holiday", "holiday": "..."}
      {"status": "closed_hours"}
    """
    current = _to_ist(now)
    date_key = current.strftime("%Y-%m-%d")
    if date_key in SUPPORT_HOLIDAYS:
        return {"status": "closed_holiday", "holiday": SUPPORT_HOLIDAYS[date_key]}
    if not is_within_working_hours(current):
        return {"status": "closed_hours"}
    return {"status": "open"}


def working_seconds_between(start: datetime, end: datetime) -> int:
    """Seconds of WORKING time between two instants (IST): only the parts of
    [start, end) that fall inside open hours on working days count.

    Used by the 5-minute handoff fallback: a request at 18:28 on a weekday has
    accrued 2 working minutes by 18:33 (the desk closed at 18:30), so the
    fallback does not fire then; a request at 09:58 has accrued 5 working
    minutes at 10:05 (the clock started at 10:00), not at 10:03.
    """
    start_ist = _to_ist(start)
    end_ist = _to_ist(end)
    if end_ist <= start_ist:
        return 0
    total = 0
    day = start_ist.date()
    while day <= end_ist.date():
        window = _open_window(day)
        if window is not None:
            open_dt = datetime.combine(day, window[0], tzinfo=IST)
            close_dt = datetime.combine(day, window[1], tzinfo=IST)
            lo = max(start_ist, open_dt)
            hi = min(end_ist, close_dt)
            if hi > lo:
                total += int((hi - lo).total_seconds())
        day += timedelta(days=1)
    return total
