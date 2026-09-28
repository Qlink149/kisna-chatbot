"""One store shape for every source: the kisna.com list and the dashboard CSV.

Stored fields: store_id, name, address, city, state, pincode, phone,
open_time ("HH:MM"), close_time, weekly_off (lower-case day names), bookable,
active, source, updated_at.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any

DEFAULT_OPEN = "11:00"
DEFAULT_CLOSE = "21:00"

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Spellings seen in the source data -> the name customers expect to pick.
STATE_ALIASES = {
    "chattisgarh": "Chhattisgarh",
    "chhatisgarh": "Chhattisgarh",
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "delhi ncr": "Delhi",
    "new delhi": "Delhi",
}

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_PINCODE_RE = re.compile(r"^[1-9]\d{5}$")
_SPACES_RE = re.compile(r"\s+")

STORE_FIELDS = (
    "store_id",
    "name",
    "address",
    "city",
    "state",
    "pincode",
    "phone",
    "open_time",
    "close_time",
    "weekly_off",
    "bookable",
    "active",
)


def clean_text(value: Any) -> str:
    return _SPACES_RE.sub(" ", str(value or "")).strip()


def title_place(value: Any) -> str:
    """Trim and title-case a place name, keeping short all-caps tokens (NCR)."""
    def fix(w: str) -> str:
        return w if (w.isupper() and len(w) <= 4) else w[:1].upper() + w[1:].lower()

    words = [w for w in clean_text(value).split(" ") if w]
    return " ".join("-".join(fix(p) for p in w.split("-")) for w in words)


def normalise_state(value: Any) -> str:
    name = title_place(value)
    return STATE_ALIASES.get(name.lower(), name)


def normalise_hhmm(value: Any) -> str | None:
    m = _HHMM_RE.match(clean_text(value))
    if not m:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def normalise_weekly_off(value: Any) -> list[str]:
    """Accept a list or a "sunday;monday" / "Sun, Mon" string."""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[;,|/]", str(value or ""))
    days: list[str] = []
    for p in parts:
        p = p.strip().lower()
        if not p:
            continue
        match = next((d for d in WEEKDAYS if d.startswith(p[:3])), None)
        if match is None:
            raise ValueError(f"unknown weekday {p!r}")
        if match not in days:
            days.append(match)
    return sorted(days, key=WEEKDAYS.index)


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _hours_from_kisna(store_hours: Any) -> tuple[str, str, list[str]]:
    """Most common open/close across open days, plus the days not open."""
    if not isinstance(store_hours, dict):
        return DEFAULT_OPEN, DEFAULT_CLOSE, []
    opens: Counter = Counter()
    closes: Counter = Counter()
    off: list[str] = []
    for day in WEEKDAYS:
        info = store_hours.get(day)
        if not isinstance(info, dict) or str(info.get("status", "")).lower() != "open":
            off.append(day)
            continue
        o, c = normalise_hhmm(info.get("from")), normalise_hhmm(info.get("to"))
        if o:
            opens[o] += 1
        if c:
            closes[c] += 1
    if len(off) == len(WEEKDAYS):
        # No usable hours at all: do not mark every day off, fall back.
        return DEFAULT_OPEN, DEFAULT_CLOSE, []
    open_time = opens.most_common(1)[0][0] if opens else DEFAULT_OPEN
    close_time = closes.most_common(1)[0][0] if closes else DEFAULT_CLOSE
    if minutes(close_time) - minutes(open_time) < 60:
        return DEFAULT_OPEN, DEFAULT_CLOSE, off
    return open_time, close_time, off


def from_kisna_record(raw: dict) -> dict:
    """Map one kisna.com ``allStores`` record (as trimmed in stores_seed.json)."""
    addr = raw.get("address") or {}
    open_time, close_time, weekly_off = _hours_from_kisna(raw.get("storeHours"))
    active = bool(raw.get("active")) and str(raw.get("status", "active")).lower() == "active"
    return {
        "store_id": clean_text(raw.get("branchCode") or raw.get("_id")),
        "name": clean_text(raw.get("name") or raw.get("storeName")),
        "address": clean_text(addr.get("line1")),
        "city": title_place(addr.get("city")),
        "state": normalise_state(addr.get("state")),
        "pincode": clean_text(addr.get("pincode")),
        "phone": clean_text(raw.get("phone")),
        "open_time": open_time,
        "close_time": close_time,
        "weekly_off": weekly_off,
        "bookable": True,
        "active": active,
        "source": "kisna.com",
        "updated_at": int(time.time()),
    }


def _as_bool(value: Any, default: bool) -> bool:
    text = clean_text(value).lower()
    if text == "":
        return default
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    raise ValueError(f"not a yes/no value: {value!r}")


def from_csv_row(row: dict) -> dict:
    """Validate and map one dashboard CSV row. Raises ValueError listing every
    problem in the row, so the importer can report them all at once."""
    row = {clean_text(k).lower(): v for k, v in (row or {}).items() if k is not None}
    errors: list[str] = []

    store_id = clean_text(row.get("store_id"))
    name = clean_text(row.get("name"))
    city = title_place(row.get("city"))
    state = normalise_state(row.get("state"))
    pincode = clean_text(row.get("pincode"))
    for field, value in (("store_id", store_id), ("name", name), ("city", city), ("state", state)):
        if not value:
            errors.append(f"{field} is required")
    if pincode and not _PINCODE_RE.match(pincode):
        errors.append(f"pincode {pincode!r} is not a 6-digit PIN")

    open_raw, close_raw = row.get("open_time"), row.get("close_time")
    open_time = normalise_hhmm(open_raw) if clean_text(open_raw) else DEFAULT_OPEN
    close_time = normalise_hhmm(close_raw) if clean_text(close_raw) else DEFAULT_CLOSE
    if open_time is None:
        errors.append(f"open_time {open_raw!r} is not HH:MM")
    if close_time is None:
        errors.append(f"close_time {close_raw!r} is not HH:MM")
    if open_time and close_time and minutes(close_time) - minutes(open_time) < 60:
        errors.append("close_time must be at least 1 hour after open_time")

    weekly_off: list[str] = []
    try:
        weekly_off = normalise_weekly_off(row.get("weekly_off"))
    except ValueError as e:
        errors.append(str(e))
    if len(weekly_off) == len(WEEKDAYS):
        errors.append("weekly_off cannot be every day")

    bookable = active = True
    try:
        bookable = _as_bool(row.get("bookable"), True)
    except ValueError as e:
        errors.append(f"bookable: {e}")
    try:
        active = _as_bool(row.get("active"), True)
    except ValueError as e:
        errors.append(f"active: {e}")

    if errors:
        raise ValueError("; ".join(errors))
    return {
        "store_id": store_id,
        "name": name,
        "address": clean_text(row.get("address")),
        "city": city,
        "state": state,
        "pincode": pincode,
        "phone": clean_text(row.get("phone")),
        "open_time": open_time,
        "close_time": close_time,
        "weekly_off": weekly_off,
        "bookable": bookable,
        "active": active,
        "source": "csv",
        "updated_at": int(time.time()),
    }


def duplicate_report(stores: list[dict]) -> dict[str, list]:
    """Duplicate store ids, and the same name+city or address+pincode twice."""
    ids = Counter(s["store_id"] for s in stores)
    names = Counter((s["name"].lower(), s["city"].lower()) for s in stores)
    addrs = Counter(
        (s["address"].lower(), s["pincode"]) for s in stores if s.get("address")
    )
    return {
        "store_id": sorted(k for k, n in ids.items() if n > 1),
        "name_city": sorted(k for k, n in names.items() if n > 1),
        "address_pincode": sorted(k for k, n in addrs.items() if n > 1),
    }


def to_csv_row(store: dict) -> dict:
    row = {k: store.get(k, "") for k in STORE_FIELDS}
    row["weekly_off"] = ";".join(store.get("weekly_off") or [])
    row["bookable"] = "true" if store.get("bookable") else "false"
    row["active"] = "true" if store.get("active") else "false"
    return row
