"""One store shape for every source: the kisna.com list and the dashboard CSV.

Stored fields: store_id, name, address, city, state, pincode, phone,
open_time ("HH:MM"), close_time, weekly_off (lower-case day names), bookable,
active, source, updated_at, hours_overridden (open/close set by the dashboard;
only then do they set visit slots -- see effective_hours).
"""

from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any

DEFAULT_OPEN = "11:00"
DEFAULT_CLOSE = "21:00"

# Store-visit slot hours when the dashboard has not set a store's hours: the
# client's hourly 11:00 AM ... 8:00 PM (a slot must end by close, so the last
# one starts 20:00). kisna.com hours are stored but no longer set slots.
SLOT_DEFAULT_OPEN = "11:00"
SLOT_DEFAULT_CLOSE = "21:00"

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

    def place(value: Any) -> Any:
        # The live API nests {"_id", "name"}; the trimmed seed file has the name.
        return value.get("name") if isinstance(value, dict) else value

    addr = {**addr, "city": place(addr.get("city")), "state": place(addr.get("state"))}
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


# Field ownership (see stores/sync.py): the dashboard may change only these.
OVERRIDE_FIELDS = ("bookable", "open_time", "close_time", "weekly_off")
SYNCED_FIELDS = ("name", "address", "city", "state", "pincode", "phone")
_SYNCED_NORMALISERS = {
    "name": clean_text,
    "address": clean_text,
    "city": title_place,
    "state": normalise_state,
    "pincode": clean_text,
    "phone": clean_text,
}


def validate_overrides(values: dict, current: dict) -> tuple[dict, list[str]]:
    """Check dashboard-supplied override values against the stored store.

    ``values`` may hold any subset of OVERRIDE_FIELDS (raw strings from a CSV
    or typed values from the API). Returns (update, errors); ``update`` has
    only the fields that were supplied, normalised."""
    errors: list[str] = []
    update: dict[str, Any] = {}
    if "bookable" in values:
        try:
            v = values["bookable"]
            update["bookable"] = v if isinstance(v, bool) else _as_bool(v, bool(current.get("bookable", True)))
        except ValueError as e:
            errors.append(f"bookable: {e}")
    for field in ("open_time", "close_time"):
        if field in values:
            raw = values[field]
            if clean_text(raw) == "":
                continue  # blank = unchanged
            hhmm = normalise_hhmm(raw)
            if hhmm is None:
                errors.append(f"{field} {raw!r} is not HH:MM")
            else:
                update[field] = hhmm
    if "weekly_off" in values:
        try:
            update["weekly_off"] = normalise_weekly_off(values["weekly_off"])
        except ValueError as e:
            errors.append(str(e))
        else:
            if len(update["weekly_off"]) == len(WEEKDAYS):
                errors.append("weekly_off cannot be every day")
    shown_open, shown_close = effective_hours(current)
    open_t = update.get("open_time") or shown_open
    close_t = update.get("close_time") or shown_close
    if not any("_time" in e for e in errors) and minutes(close_t) - minutes(open_t) < 60:
        errors.append("close_time must be at least 1 hour after open_time")
    # Hours become the store's own only when they differ from what the
    # dashboard shows: its edit form (and a re-uploaded CSV) sends the shown
    # hours back unchanged, and that must not pin anything.
    update.pop("open_time", None)
    update.pop("close_time", None)
    if (open_t, close_t) != (shown_open, shown_close):
        update.update(open_time=open_t, close_time=close_t, hours_overridden=True)
    return update, errors


def effective_hours(store: dict) -> tuple[str, str]:
    """(open, close) that set the store's visit slots: the dashboard's hours
    once it has set them, else the client's default."""
    if store.get("hours_overridden"):
        return (store.get("open_time") or SLOT_DEFAULT_OPEN, store.get("close_time") or SLOT_DEFAULT_CLOSE)
    return SLOT_DEFAULT_OPEN, SLOT_DEFAULT_CLOSE


def for_dashboard(store: dict) -> dict:
    """The store as the dashboard shows and downloads it: open/close are the
    hours that set slots, not kisna.com's."""
    open_t, close_t = effective_hours(store)
    return {**store, "open_time": open_t, "close_time": close_t, "hours_overridden": bool(store.get("hours_overridden"))}


def synced_field_conflicts(row: dict, current: dict) -> list[str]:
    """Synced columns may be present (a downloaded CSV re-uploaded) but must
    match what kisna.com gave us; any change is an error."""
    errors = []
    for field, norm in _SYNCED_NORMALISERS.items():
        if field not in row or row[field] is None:
            continue
        given = norm(row[field])
        if given != norm(current.get(field, "")):
            errors.append(
                f"{field} {given!r} differs from kisna.com ({current.get(field, '')!r}): "
                f"{field} comes from the website and can't be changed here"
            )
    if "active" in row and clean_text(row["active"]) != "":
        try:
            if _as_bool(row["active"], True) != bool(current.get("active")):
                errors.append("active is set by the kisna.com sync and can't be changed here")
        except ValueError as e:
            errors.append(f"active: {e}")
    return errors


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
    row["open_time"], row["close_time"] = effective_hours(store)
    row["weekly_off"] = ";".join(store.get("weekly_off") or [])
    row["bookable"] = "true" if store.get("bookable") else "false"
    row["active"] = "true" if store.get("active") else "false"
    return row
