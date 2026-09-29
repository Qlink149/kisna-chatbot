"""Bookable dates and hourly slots for a store visit.

Dates: today + the next ``BOOKING_DAYS - 1`` days (IST), minus the store's
weekly_off days and the company holiday calendar. Slots: hourly from the
store's open_time while the hour still ends by close_time (10:30-20:00 gives
10:30 ... 18:30 starts), minus anything already past or under
``MIN_LEAD_MINUTES`` away.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from kisna_chatbot.config.store_visit import BOOKING_DAYS, MIN_LEAD_MINUTES, SLOT_MINUTES
from kisna_chatbot.stores.model import WEEKDAYS, minutes
from kisna_chatbot.utils.support_hours import IST, is_holiday


def _now_ist(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=IST)
    return now.astimezone(IST)


def clock_label(hhmm: str) -> str:
    """"18:30" -> "6:30 PM", "11:00" -> "11:00 AM"."""
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    return f"{(h - 1) % 12 + 1}:{m:02d} {suffix}"


def _starts(store: dict) -> list[str]:
    open_m, close_m = minutes(store["open_time"]), minutes(store["close_time"])
    out = []
    t = open_m
    while t + SLOT_MINUTES <= close_m:
        out.append(f"{t // 60:02d}:{t % 60:02d}")
        t += SLOT_MINUTES
    return out


def slots_for_date(store: dict, iso_date: str, now: datetime | None = None) -> list[dict]:
    """[{"id": "11:00", "title": "11:00 AM"}, ...] -- empty when the day is
    closed, outside the booking window, or has no slot 2h+ away."""
    try:
        day = date.fromisoformat(iso_date)
    except (TypeError, ValueError):
        return []
    if day not in bookable_dates(store, now):
        return []
    current = _now_ist(now)
    cutoff = current + timedelta(minutes=MIN_LEAD_MINUTES)
    out = []
    for start in _starts(store):
        h, m = (int(x) for x in start.split(":"))
        begins = datetime(day.year, day.month, day.day, h, m, tzinfo=IST)
        if begins >= cutoff:
            out.append({"id": start, "title": clock_label(start)})
    return out


def _open_day(store: dict, day: date) -> bool:
    off = set(store.get("weekly_off") or [])
    return WEEKDAYS[day.weekday()] not in off and not is_holiday(day)


def bookable_dates(store: dict, now: datetime | None = None) -> list[date]:
    """Open days in the window that still have at least one slot."""
    today = _now_ist(now).date()
    days = []
    for i in range(BOOKING_DAYS):
        d = today + timedelta(days=i)
        if not _open_day(store, d):
            continue
        if i == 0 and not _has_slot_today(store, now):
            continue
        days.append(d)
    return days


def _has_slot_today(store: dict, now: datetime | None) -> bool:
    current = _now_ist(now)
    cutoff = current + timedelta(minutes=MIN_LEAD_MINUTES)
    for start in _starts(store):
        h, m = (int(x) for x in start.split(":"))
        if current.replace(hour=h, minute=m, second=0, microsecond=0) >= cutoff:
            return True
    return False


def date_window(store: dict, now: datetime | None = None) -> dict:
    """DatePicker bounds for the store: min/max and the closed days between."""
    today = _now_ist(now).date()
    last = today + timedelta(days=BOOKING_DAYS - 1)
    open_days = set(bookable_dates(store, now))
    unavailable = [
        (today + timedelta(days=i)).isoformat()
        for i in range(BOOKING_DAYS)
        if (today + timedelta(days=i)) not in open_days
    ]
    first = min(open_days) if open_days else today
    return {
        "min_date": first.isoformat(),
        "max_date": last.isoformat(),
        "unavailable_dates": unavailable,
        "has_dates": bool(open_days),
    }


def is_slot_bookable(store: dict, iso_date: str, slot_id: str, now: datetime | None = None) -> bool:
    return any(s["id"] == slot_id for s in slots_for_date(store, iso_date, now))
