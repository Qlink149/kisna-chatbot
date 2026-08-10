"""IST booking slots for callback / video-call requests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Callable

from kisna_chatbot.utils.support_hours import (
    holiday_name,
    is_working_day,
)

_IST = timezone(timedelta(hours=5, minutes=30))

DAILY_MAX = 10
SLOT_CAPACITY = 5
LOOKAHEAD_DAYS = 60

# Canonical slot definitions: (id, title, start_hour)
WEEKDAY_SLOTS: list[tuple[str, str, int]] = [
    ("10-13", "Morning — 10 AM–1 PM", 10),
    ("13-15", "Afternoon — 1 PM–3 PM", 13),
    ("15-18", "Evening — 3 PM–6 PM", 15),
]

SATURDAY_SLOTS: list[tuple[str, str, int]] = [
    ("10-16", "Day — 10 AM–4 PM", 10),
]

# Flat list for labels / legacy lookups (all known slot ids).
SUPPORT_SLOTS: list[tuple[str, str, int]] = WEEKDAY_SLOTS + SATURDAY_SLOTS

SLOT_LABELS: dict[str, str] = {sid: title for sid, title, _ in SUPPORT_SLOTS}
SLOT_START_HOUR: dict[str, int] = {sid: hour for sid, _, hour in SUPPORT_SLOTS}

# Map legacy hourly / coarse ids → current block ids (weekday).
_LEGACY_TO_BLOCK: dict[str, str] = {
    "morning": "10-13",
    "afternoon": "13-15",
    "10-11": "10-13",
    "11-12": "10-13",
    "12-13": "10-13",
    "13-14": "13-15",
    "14-15": "13-15",
    "15-16": "15-18",
    "16-17": "15-18",
}

_ACTIVE_STATUSES = ("pending", "completed")

# Optional overrides for tests: (iso_date) -> count, (iso_date, slot_id) -> count
_day_count_override: Callable[[str], int] | None = None
_slot_count_override: Callable[[str, str], int] | None = None


def now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(_IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=_IST)
    return now.astimezone(_IST)


def today_ist_iso(now: datetime | None = None) -> str:
    return now_ist(now).date().isoformat()


def _parse_iso_date(iso_date: str) -> date:
    return datetime.strptime(iso_date, "%Y-%m-%d").date()


def normalize_slot_id(slot_id: str | None, iso_date: str | None = None) -> str:
    """Map legacy / free-text slot ids onto the current schedule."""
    sid = (slot_id or "").strip()
    if not sid:
        return ""
    if sid in SLOT_START_HOUR:
        # Saturday only has 10-16; weekday blocks are invalid on Sat and vice versa.
        if iso_date:
            try:
                day = _parse_iso_date(iso_date)
            except (TypeError, ValueError):
                return sid
            allowed = {s[0] for s in slots_for_weekday(day.weekday())}
            if sid in allowed:
                return sid
            # Remap weekday block → Saturday single slot (or reverse via legacy).
            if day.weekday() == 5:
                return "10-16"
            if sid == "10-16":
                return "10-13"
        return sid
    mapped = _LEGACY_TO_BLOCK.get(sid)
    if mapped and iso_date:
        try:
            day = _parse_iso_date(iso_date)
            if day.weekday() == 5:
                return "10-16"
        except (TypeError, ValueError):
            pass
    return mapped or sid


def slots_for_weekday(weekday: int) -> list[tuple[str, str, int]]:
    """weekday: Mon=0 … Sun=6."""
    if weekday == 6:
        return []
    if weekday == 5:
        return list(SATURDAY_SLOTS)
    return list(WEEKDAY_SLOTS)


def count_day_bookings(iso_date: str) -> int:
    if _day_count_override is not None:
        return _day_count_override(iso_date)
    from kisna_chatbot.database.collections import callback_requests

    return int(
        callback_requests.count_documents(
            {
                "preferred_date": iso_date,
                "status": {"$in": list(_ACTIVE_STATUSES)},
            }
        )
    )


def count_slot_bookings(iso_date: str, slot_id: str) -> int:
    sid = normalize_slot_id(slot_id, iso_date)
    if _slot_count_override is not None:
        return _slot_count_override(iso_date, sid)
    from kisna_chatbot.database.collections import callback_requests

    # Count exact slot id plus legacy ids that map into this block.
    legacy_ids = [
        legacy
        for legacy, block in _LEGACY_TO_BLOCK.items()
        if normalize_slot_id(legacy, iso_date) == sid
    ]
    slot_ids = list({sid, *legacy_ids})
    return int(
        callback_requests.count_documents(
            {
                "preferred_date": iso_date,
                "preferred_time": {"$in": slot_ids},
                "status": {"$in": list(_ACTIVE_STATUSES)},
            }
        )
    )


def set_capacity_overrides(
    day_count: Callable[[str], int] | None = None,
    slot_count: Callable[[str, str], int] | None = None,
) -> None:
    """Test helper to inject booking counts without Mongo."""
    global _day_count_override, _slot_count_override
    _day_count_override = day_count
    _slot_count_override = slot_count


def clear_capacity_overrides() -> None:
    set_capacity_overrides(None, None)


def _slot_still_in_future(
    day: date,
    start_hour: int,
    current: datetime,
) -> bool:
    today = current.date()
    if day > today:
        return True
    if day < today:
        return False
    slot_start = current.replace(
        hour=start_hour, minute=0, second=0, microsecond=0
    )
    return slot_start > current


def available_slots_for_date(
    iso_date: str,
    now: datetime | None = None,
    *,
    check_capacity: bool = True,
) -> list[dict[str, str]]:
    """
    Return bookable slots for iso_date (YYYY-MM-DD).

    Excludes Sundays, holidays, past dates/slots, days at daily max,
    and slots at per-slot capacity.
    """
    current = now_ist(now)
    try:
        day = _parse_iso_date(iso_date)
    except (TypeError, ValueError):
        return []

    today = current.date()
    if day < today:
        return []
    if not is_working_day(day):
        return []

    if check_capacity and count_day_bookings(iso_date) >= DAILY_MAX:
        return []

    slots: list[dict[str, str]] = []
    for sid, title, start_hour in slots_for_weekday(day.weekday()):
        if not _slot_still_in_future(day, start_hour, current):
            continue
        if check_capacity and count_slot_bookings(iso_date, sid) >= SLOT_CAPACITY:
            continue
        slots.append({"id": sid, "title": title})
    return slots


def is_slot_still_bookable(
    iso_date: str,
    slot_id: str,
    now: datetime | None = None,
    *,
    check_capacity: bool = True,
) -> bool:
    sid = normalize_slot_id(slot_id, iso_date)
    return any(
        s["id"] == sid
        for s in available_slots_for_date(
            iso_date, now=now, check_capacity=check_capacity
        )
    )


def is_preferred_datetime_valid(
    iso_date: str | None,
    slot_id: str | None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """
    Validate preferred_date + preferred_time for booking.

    Returns (ok, reason_code) where reason_code is '' | 'missing_date' |
    'invalid_date' | 'past_date' | 'closed_day' | 'day_full' | 'missing_slot' |
    'past_slot' | 'slot_full' | 'invalid_slot'.
    """
    current = now_ist(now)
    if not iso_date or not str(iso_date).strip():
        return False, "missing_date"
    date_str = str(iso_date).strip()
    try:
        day = _parse_iso_date(date_str)
    except (TypeError, ValueError):
        return False, "invalid_date"

    if day < current.date():
        return False, "past_date"

    if not is_working_day(day):
        return False, "closed_day"

    raw_sid = (slot_id or "").strip()
    if not raw_sid:
        return False, "missing_slot"

    sid = normalize_slot_id(raw_sid, date_str)
    allowed = {s[0] for s in slots_for_weekday(day.weekday())}
    if sid not in allowed and sid not in SLOT_START_HOUR and sid not in _LEGACY_TO_BLOCK:
        return False, "invalid_slot"
    if sid not in allowed:
        return False, "invalid_slot"

    if count_day_bookings(date_str) >= DAILY_MAX:
        return False, "day_full"

    start_hour = SLOT_START_HOUR[sid]
    if not _slot_still_in_future(day, start_hour, current):
        return False, "past_slot"

    if count_slot_bookings(date_str, sid) >= SLOT_CAPACITY:
        return False, "slot_full"

    return True, ""


def find_next_available(
    preferred_date: str | None = None,
    preferred_time: str | None = None,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """
    Find the next bookable (date, slot_id).

    Starts at preferred_date/time when provided: later slots same day first,
    then subsequent working days. Bounded by LOOKAHEAD_DAYS.
    """
    current = now_ist(now)
    today = current.date()

    start_day = today
    start_slot_index = 0
    if preferred_date:
        try:
            start_day = _parse_iso_date(str(preferred_date).strip())
        except (TypeError, ValueError):
            start_day = today
        if start_day < today:
            start_day = today

    if preferred_time and preferred_date:
        sid = normalize_slot_id(preferred_time, str(preferred_date).strip())
        day_slots = slots_for_weekday(start_day.weekday())
        for idx, (slot_id, _, _) in enumerate(day_slots):
            if slot_id == sid:
                start_slot_index = idx  # include preferred; caller checks first
                break

    for offset in range(LOOKAHEAD_DAYS + 1):
        day = start_day + timedelta(days=offset)
        if day < today:
            continue
        date_str = day.isoformat()
        if not is_working_day(day):
            continue
        if count_day_bookings(date_str) >= DAILY_MAX:
            continue

        day_slots = slots_for_weekday(day.weekday())
        first_idx = start_slot_index if offset == 0 else 0
        for sid, _title, start_hour in day_slots[first_idx:]:
            if not _slot_still_in_future(day, start_hour, current):
                continue
            if count_slot_bookings(date_str, sid) >= SLOT_CAPACITY:
                continue
            return date_str, sid

    return None


def resolve_booking_slot(
    preferred_date: str | None,
    preferred_time: str | None,
    now: datetime | None = None,
) -> tuple[str, str, bool] | None:
    """
    Return (date, slot_id, was_rescheduled) or None if nothing available.

    Books preferred when still free; otherwise next available.
    """
    current = now_ist(now)
    date_str = (preferred_date or "").strip()
    sid = normalize_slot_id(preferred_time, date_str) if preferred_time else ""

    if date_str and sid:
        ok, _reason = is_preferred_datetime_valid(date_str, sid, now=current)
        if ok:
            return date_str, sid, False

    # Prefer next slot after the requested one when request was full/past.
    nxt = find_next_available(
        preferred_date=date_str or today_ist_iso(current),
        preferred_time=sid or preferred_time,
        now=current,
    )
    if nxt is None:
        # If preferred was in the past / closed, search from today with no slot bias.
        nxt = find_next_available(now=current)
    if nxt is None:
        return None
    assigned_date, assigned_slot = nxt
    was_rescheduled = not (
        date_str == assigned_date and sid == assigned_slot
    )
    return assigned_date, assigned_slot, was_rescheduled


def format_slots_for_prompt(slots: list[dict[str, str]] | None = None) -> str:
    items = slots if slots is not None else [
        {"id": sid, "title": title} for sid, title, _ in WEEKDAY_SLOTS
    ]
    if not items:
        return "(no slots left today — please pick another date)"
    return ", ".join(f"{s['id']} ({s['title']})" for s in items)


def earliest_bookable_date(now: datetime | None = None) -> str:
    """First working day (from today) that still has at least one open slot."""
    current = now_ist(now)
    for offset in range(LOOKAHEAD_DAYS + 1):
        day = current.date() + timedelta(days=offset)
        date_str = day.isoformat()
        if available_slots_for_date(date_str, now=current):
            return date_str
    return today_ist_iso(current)


def screen_data_for_date(
    iso_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Payload fragment for Flow screen data (min_date, time_slots, slot_error)."""
    current = now_ist(now)
    min_date = earliest_bookable_date(current)
    date_str = (iso_date or min_date).strip()
    slots = available_slots_for_date(date_str, now=current)
    slot_error = ""

    try:
        day = _parse_iso_date(date_str)
    except (TypeError, ValueError):
        day = None

    if day is not None and day < current.date():
        slot_error = "Please choose today or a future date."
    elif day is not None and not is_working_day(day):
        name = holiday_name(day)
        if name:
            slot_error = (
                f"We're closed on {name}. Please choose another working day."
            )
        else:
            slot_error = (
                "We're closed on Sundays and holidays. "
                "Please choose a working day (Mon–Sat)."
            )
    elif day is not None and count_day_bookings(date_str) >= DAILY_MAX:
        slot_error = (
            "This day is fully booked. Please choose another date."
        )
    elif not slots:
        if date_str == today_ist_iso(current):
            slot_error = (
                "No time slots left today. Please choose another date."
            )
        else:
            slot_error = (
                "No time slots available for this date. "
                "Please choose another date."
            )

    return {
        "min_date": min_date,
        "time_slots": slots,
        "slot_error": slot_error,
    }
