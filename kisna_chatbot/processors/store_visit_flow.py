"""data_exchange handler for the Store Visit Flow (json/store_visit.json).

Screens: SV_DETAILS -> SV_STORE (State -> City -> Store, each a round trip)
-> SV_DATETIME (dates and hourly slots refreshed on date change). The
customer's details ride along in each screen's data, so this handler is
stateless: every answer is built from the request alone plus the store cache.
"""

from __future__ import annotations

import re
from datetime import datetime

from kisna_chatbot.config.store_visit import (
    FLOW_TOKEN_PREFIX,
    LOOKING_FOR_OPTIONS,
    MAX_DROPDOWN_OPTIONS,
    get_store_visit_flow_id,
)
from kisna_chatbot.stores import cache as store_cache
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.store_visit_slots import date_window, slots_for_date

SCREEN_DETAILS = "SV_DETAILS"
SCREEN_STORE = "SV_STORE"
SCREEN_DATETIME = "SV_DATETIME"
SCREENS = frozenset({SCREEN_DETAILS, SCREEN_STORE, SCREEN_DATETIME})

DETAIL_FIELDS = ("first_name", "last_name", "email", "phone", "looking_for")

# Meta's Dropdown limits: option title 30 chars, description 300.
_TITLE_MAX = 30
_DESCRIPTION_MAX = 300

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

ERR_FIRST_NAME = "Please enter your first name."
ERR_EMAIL = "Please enter a valid email address, or leave it blank."
ERR_PHONE = "Please enter a valid 10-digit mobile number."
ERR_LOOKING_FOR = "Please choose what you're looking for."
ERR_NO_STORES = "Store booking isn't available right now. Please try again later."
ERR_PICK_STORE = "Please choose a store."
ERR_STORE_GONE = "That store isn't taking bookings right now. Please choose another."
ERR_STORE_NO_DATES = "This store has no open slots in the next 7 days. Please choose another."
ERR_NO_SLOTS = "No slots left on this date. Please choose another date."
ERR_GENERIC = "Something went wrong. Please try again."


def is_store_visit_token(flow_token: str | None) -> bool:
    token = str(flow_token or "")
    if token.startswith(f"{FLOW_TOKEN_PREFIX}:"):
        return True
    flow_id = get_store_visit_flow_id()
    return bool(flow_id) and token == flow_id


def is_store_visit_request(decrypted: dict) -> bool:
    screen = str(decrypted.get("screen") or "").strip()
    return screen in SCREENS or is_store_visit_token(decrypted.get("flow_token"))


def _cap(options: list[dict], what: str) -> list[dict]:
    if len(options) > MAX_DROPDOWN_OPTIONS:
        logger.warning(
            "Store visit dropdown over the WhatsApp cap; truncated",
            extra={"dropdown": what, "options": len(options), "cap": MAX_DROPDOWN_OPTIONS},
        )
        return options[:MAX_DROPDOWN_OPTIONS]
    return options


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def store_title(store: dict) -> str:
    """Store names read "Area - City - State"; City and State are already
    chosen on this screen, so the dropdown shows the area part."""
    name = store.get("name") or ""
    parts = [p.strip() for p in name.split(" - ")]
    if len(parts) >= 2 and parts[-1].lower() == (store.get("state") or "").lower():
        parts = parts[:-1]
    if len(parts) >= 2 and parts[-1].lower() == (store.get("city") or "").lower():
        parts = parts[:-1]
    return _clip(" - ".join(parts) or name, _TITLE_MAX)


def store_address_line(store: dict) -> str:
    bits = [store.get("address") or "", store.get("city") or ""]
    text = ", ".join(b for b in bits if b)
    if store.get("pincode"):
        text = f"{text} {store['pincode']}".strip()
    return text


def _carried(data_in: dict) -> dict:
    return {k: str(data_in.get(k) or "").strip() for k in DETAIL_FIELDS}


def looking_for_options() -> list[dict]:
    return [{"id": i, "title": t} for i, t in LOOKING_FOR_OPTIONS]


def _init_values(**values: str) -> dict:
    """Form prefills (Flow JSON v7.0: Form "init-values", not per component).
    Empty values are left out -- an empty dropdown prefill is not an option."""
    return {k: v for k, v in values.items() if v}


def details_screen_data(first_name: str = "", phone: str = "", error: str = "") -> dict:
    return {
        "first_name": first_name or "",
        "phone": phone or "",
        "looking_for_options": looking_for_options(),
        "details_error": error,
        "init_values": _init_values(first_name=first_name or "", phone=phone or ""),
    }


def _options(values: list[str]) -> list[dict]:
    return [{"id": v, "title": _clip(v, _TITLE_MAX)} for v in values]


def _store_screen(carried: dict, *, state: str = "", city: str = "", error: str = "") -> dict:
    states = store_cache.list_states()
    data = {
        **carried,
        "states": _cap(_options(states), "state"),
        "cities": [],
        "stores": [],
        "selected_state": state,
        "selected_city": city,
        "cities_visible": False,
        "stores_visible": False,
        "store_error": error or ("" if states else ERR_NO_STORES),
        # Keeps the picks when the screen is re-rendered (each tap, BACK).
        "init_values": _init_values(state=state, city=city),
    }
    if state:
        cities = store_cache.list_cities(state)
        data["cities"] = _cap(_options(cities), "city")
        data["cities_visible"] = bool(cities)
    if state and city:
        stores = store_cache.list_stores(state, city)
        data["stores"] = _cap(
            [
                {
                    "id": s["store_id"],
                    "title": store_title(s),
                    "description": _clip(store_address_line(s), _DESCRIPTION_MAX),
                }
                for s in stores
            ],
            "store",
        )
        data["stores_visible"] = bool(stores)
    # WhatsApp rejects an empty data-source array; keep a disabled placeholder.
    for key in ("cities", "stores"):
        if not data[key]:
            data[key] = [{"id": "_none", "title": "—", "enabled": False}]
    return {"screen": SCREEN_STORE, "data": data}


def _datetime_screen(carried: dict, store: dict, iso_date: str | None, now: datetime | None) -> dict:
    window = date_window(store, now)
    chosen = (iso_date or "").strip() or window["min_date"]
    slots = slots_for_date(store, chosen, now)
    error = "" if slots else ERR_NO_SLOTS
    return {
        "screen": SCREEN_DATETIME,
        "data": {
            **carried,
            "store_id": store["store_id"],
            "store_name": store.get("name") or "",
            "store_address": store_address_line(store),
            "min_date": window["min_date"],
            "max_date": window["max_date"],
            "unavailable_dates": window["unavailable_dates"],
            "selected_date": chosen,
            "time_slots": slots or [{"id": "_none", "title": "—", "enabled": False}],
            "slot_error": error,
            "init_values": _init_values(preferred_date=chosen),
        },
    }


def _validate_details(carried: dict) -> str:
    if not carried["first_name"]:
        return ERR_FIRST_NAME
    if carried["email"] and not _EMAIL_RE.match(carried["email"]):
        return ERR_EMAIL
    digits = re.sub(r"\D", "", carried["phone"])
    if not (10 <= len(digits) <= 13):
        return ERR_PHONE
    if carried["looking_for"] not in dict(LOOKING_FOR_OPTIONS):
        return ERR_LOOKING_FOR
    return ""


def build_store_visit_response(decrypted: dict, now: datetime | None = None) -> dict:
    """Cleartext response for one Store Visit Flow request (never raises)."""
    action = str(decrypted.get("action") or "").strip()
    screen = str(decrypted.get("screen") or "").strip()
    data_in = decrypted.get("data") if isinstance(decrypted.get("data"), dict) else {}
    try:
        return _route(action, screen, data_in, now)
    except Exception:
        logger.exception("Store visit data_exchange failed", extra={"screen": screen})
        return {"screen": SCREEN_DETAILS, "data": details_screen_data(error=ERR_GENERIC)}


def _route(action: str, screen: str, data_in: dict, now: datetime | None) -> dict:
    carried = _carried(data_in)

    if action == "INIT":
        return {"screen": SCREEN_DETAILS, "data": details_screen_data()}

    if action == "BACK":
        if screen == SCREEN_DATETIME:
            return _store_screen(carried)
        return {
            "screen": SCREEN_DETAILS,
            "data": details_screen_data(carried["first_name"], carried["phone"]),
        }

    step = str(data_in.get("step") or "").strip()

    if step == "details":
        error = _validate_details(carried)
        if error:
            return {
                "screen": SCREEN_DETAILS,
                "data": details_screen_data(carried["first_name"], carried["phone"], error),
            }
        return _store_screen(carried)

    if step == "state":
        return _store_screen(carried, state=str(data_in.get("state") or "").strip())

    if step == "city":
        return _store_screen(
            carried,
            state=str(data_in.get("state") or "").strip(),
            city=str(data_in.get("city") or "").strip(),
        )

    if step == "store":
        state = str(data_in.get("state") or "").strip()
        city = str(data_in.get("city") or "").strip()
        store_id = str(data_in.get("store_id") or "").strip()
        if not store_id or store_id == "_none":
            return _store_screen(carried, state=state, city=city, error=ERR_PICK_STORE)
        store = store_cache.get_store(store_id)
        if store is None:
            return _store_screen(carried, state=state, city=city, error=ERR_STORE_GONE)
        if not date_window(store, now)["has_dates"]:
            return _store_screen(carried, state=state, city=city, error=ERR_STORE_NO_DATES)
        return _datetime_screen(carried, store, None, now)

    if step == "date":
        store = store_cache.get_store(str(data_in.get("store_id") or "").strip())
        if store is None:
            return _store_screen(carried, error=ERR_STORE_GONE)
        return _datetime_screen(carried, store, str(data_in.get("preferred_date") or ""), now)

    logger.warning(
        "Store visit data_exchange: unknown step",
        extra={"action": action, "screen": screen, "step": step},
    )
    if screen == SCREEN_STORE:
        return _store_screen(carried, error=ERR_GENERIC)
    return {
        "screen": SCREEN_DETAILS,
        "data": details_screen_data(carried["first_name"], carried["phone"], ERR_GENERIC),
    }
