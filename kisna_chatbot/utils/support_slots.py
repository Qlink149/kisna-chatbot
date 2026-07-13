"""IST hourly support slots for callback / video-call booking."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_IST = timezone(timedelta(hours=5, minutes=30))

# Canonical hourly slots (start hour inclusive → end hour exclusive for booking).
SUPPORT_SLOTS: list[tuple[str, str, int]] = [
    ("10-11", "Morning — 10 AM–11 AM", 10),
    ("11-12", "Morning — 11 AM–12 PM", 11),
    ("12-13", "Morning — 12 PM–1 PM", 12),
    ("13-14", "Afternoon — 1 PM–2 PM", 13),
    ("14-15", "Afternoon — 2 PM–3 PM", 14),
    ("15-16", "Afternoon — 3 PM–4 PM", 15),
    ("16-17", "Afternoon — 4 PM–5 PM", 16),
]

SLOT_LABELS: dict[str, str] = {sid: title for sid, title, _ in SUPPORT_SLOTS}
SLOT_START_HOUR: dict[str, int] = {sid: hour for sid, _, hour in SUPPORT_SLOTS}

# Legacy morning/afternoon map to a representative start hour for validation.
_LEGACY_START: dict[str, int] = {
    "morning": 10,
    "afternoon": 13,
}


def now_ist(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(_IST)
    if now.tzinfo is None:
        return now.replace(tzinfo=_IST)
    return now.astimezone(_IST)


def today_ist_iso(now: datetime | None = None) -> str:
    return now_ist(now).date().isoformat()


def _parse_iso_date(iso_date: str):
    return datetime.strptime(iso_date, "%Y-%m-%d").date()


def available_slots_for_date(
    iso_date: str,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """
    Return bookable slots for iso_date (YYYY-MM-DD).

    Rule: slot start must be strictly after `now` (IST) when the date is today.
    Future dates return all slots. Past dates return [].
    """
    current = now_ist(now)
    try:
        day = _parse_iso_date(iso_date)
    except (TypeError, ValueError):
        return []

    today = current.date()
    if day < today:
        return []

    slots: list[dict[str, str]] = []
    for sid, title, start_hour in SUPPORT_SLOTS:
        if day > today:
            slots.append({"id": sid, "title": title})
            continue
        # Same calendar day: start must be strictly after current clock time
        slot_start = current.replace(
            hour=start_hour, minute=0, second=0, microsecond=0
        )
        if slot_start > current:
            slots.append({"id": sid, "title": title})
    return slots


def is_slot_still_bookable(
    iso_date: str,
    slot_id: str,
    now: datetime | None = None,
) -> bool:
    sid = (slot_id or "").strip()
    return any(s["id"] == sid for s in available_slots_for_date(iso_date, now=now))


def is_preferred_datetime_valid(
    iso_date: str | None,
    slot_id: str | None,
    now: datetime | None = None,
) -> tuple[bool, str]:
    """
    Validate preferred_date + preferred_time for booking.

    Returns (ok, reason_code) where reason_code is '' | 'missing_date' |
    'invalid_date' | 'past_date' | 'missing_slot' | 'past_slot' | 'invalid_slot'.
    """
    current = now_ist(now)
    if not iso_date or not str(iso_date).strip():
        return False, "missing_date"
    try:
        day = _parse_iso_date(str(iso_date).strip())
    except (TypeError, ValueError):
        return False, "invalid_date"

    if day < current.date():
        return False, "past_date"

    sid = (slot_id or "").strip()
    if not sid:
        return False, "missing_slot"

    if sid in SLOT_START_HOUR:
        if not is_slot_still_bookable(str(iso_date).strip(), sid, now=current):
            return False, "past_slot"
        return True, ""

    if sid in _LEGACY_START:
        # Legacy coarse buckets: treat as bookable only on future dates,
        # or today if representative start is still in the future.
        if day > current.date():
            return True, ""
        start_hour = _LEGACY_START[sid]
        slot_start = current.replace(
            hour=start_hour, minute=0, second=0, microsecond=0
        )
        if slot_start > current:
            return True, ""
        return False, "past_slot"

    return False, "invalid_slot"


def format_slots_for_prompt(slots: list[dict[str, str]] | None = None) -> str:
    items = slots if slots is not None else [
        {"id": sid, "title": title} for sid, title, _ in SUPPORT_SLOTS
    ]
    if not items:
        return "(no slots left today — please pick another date)"
    return ", ".join(f"{s['id']} ({s['title']})" for s in items)


def screen_data_for_date(
    iso_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Payload fragment for Flow screen data (min_date, time_slots, slot_error)."""
    current = now_ist(now)
    min_date = today_ist_iso(current)
    date_str = (iso_date or min_date).strip()
    slots = available_slots_for_date(date_str, now=current)
    slot_error = ""
    if date_str == min_date and not slots:
        slot_error = (
            "No time slots left today. Please choose another date."
        )
    elif not slots and date_str < min_date:
        slot_error = "Please choose today or a future date."
    return {
        "min_date": min_date,
        "time_slots": slots,
        "slot_error": slot_error,
    }
