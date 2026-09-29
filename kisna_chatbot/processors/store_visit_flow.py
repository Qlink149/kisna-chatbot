"""data_exchange handler for the Store Visit Flow (json/store_visit.json).

Screens: SV_DETAILS (details + State -> City -> Store on one screen, each
pick a round trip that refreshes it) -> SV_DATETIME (dates and hourly slots
refreshed on date change). Each State / City pick sends every typed field
back, and the refreshed screen returns them as init-values, so typed text is
never lost. The customer's details then ride along in SV_DATETIME's data, so
this handler is stateless: every answer is built from the request alone plus
the store cache. Layout: scripts/build_store_visit_flow_json.py.
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
SCREEN_DATETIME = "SV_DATETIME"
SCREENS = frozenset({SCREEN_DETAILS, SCREEN_DATETIME})

DETAIL_FIELDS = ("first_name", "last_name", "email", "phone", "looking_for")

# Meta's Dropdown limits: option title 30 chars, description 300.
_TITLE_MAX = 30
_DESCRIPTION_MAX = 300

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

ERR_FIRST_NAME = "Please enter your first name."
ERR_EMAIL = "Please enter a valid email address, or leave it blank."
ERR_PHONE = "Please enter a valid 10-digit mobile number, or leave it blank."
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


def remember_send(flow_token: str, first_name: str, phone: str) -> None:
    """Called when the form is sent: the prefill for this form's INIT.

    The first screen always comes from the endpoint (flow_action
    data_exchange -> INIT), in WhatsApp and in the preview alike, and INIT
    carries only the flow_token -- so the customer's name and number are
    kept here, keyed by it (TTL-expired, see main.py)."""
    from kisna_chatbot.database.collections import store_visit_flow_sessions

    store_visit_flow_sessions.update_one(
        {"flow_token": flow_token},
        {
            "$set": {
                "first_name": (first_name or "").strip()[:60],
                "phone": str(phone or ""),
                "created_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )


def send_prefill(flow_token: str | None) -> dict:
    """{"first_name", "phone"} saved when this form was sent, or {} (the
    preview, an expired token, or a lookup failure -- never an error)."""
    if not flow_token:
        return {}
    try:
        from kisna_chatbot.database.collections import store_visit_flow_sessions

        doc = store_visit_flow_sessions.find_one({"flow_token": flow_token}, {"_id": 0})
    except Exception:
        logger.exception("Store visit prefill lookup failed")
        return {}
    return {"first_name": doc.get("first_name", ""), "phone": doc.get("phone", "")} if doc else {}


def looking_for_options() -> list[dict]:
    return [{"id": i, "title": t} for i, t in LOOKING_FOR_OPTIONS]


def _init_values(**values: str) -> dict:
    """Form prefills (Flow JSON v7.0: Form "init-values", not per component).
    Empty values are left out -- an empty dropdown prefill is not an option."""
    return {k: v for k, v in values.items() if v}


def details_screen_data(
    first_name: str = "",
    phone: str = "",
    error: str = "",
    *,
    form: dict | None = None,
    state: str = "",
    city: str = "",
) -> dict:
    """SV_DETAILS: the customer's details AND the State -> City -> Store
    cascade on one screen (mirrors the client's reference form).

    ``form`` is what the customer has typed so far (sent back by every
    on-select); it is returned as the Form's init-values so a State / City
    refresh never loses typed text, whatever the client does with form state.
    Without ``form`` (first send, INIT) only name + phone are prefilled."""
    values = dict(form) if form is not None else {"first_name": first_name, "phone": phone}
    cascade = _cascade(state, city)
    return {
        "looking_for_options": looking_for_options(),
        **cascade,
        "details_error": error or ("" if cascade["states"][0]["id"] != "_none" else ERR_NO_STORES),
        "init_values": _init_values(
            **{k: str(values.get(k) or "") for k in DETAIL_FIELDS},
            state=state,
            city=city if state else "",
        ),
    }


def _options(values: list[str]) -> list[dict]:
    return [{"id": v, "title": _clip(v, _TITLE_MAX)} for v in values]


def _details_screen(form: dict, *, state: str = "", city: str = "", error: str = "") -> dict:
    return {
        "screen": SCREEN_DETAILS,
        "data": details_screen_data(error=error, form=form, state=state, city=city),
    }


PLACEHOLDER_CITY = "Select a state first"
PLACEHOLDER_STORE = "Select a city first"
PLACEHOLDER_EMPTY = "No stores available"


def _placeholder(title: str) -> list[dict]:
    """One disabled option: every Dropdown needs a data-source from the first
    render, and a disabled item cannot be picked, so Next stays locked."""
    return [{"id": "_none", "title": title, "enabled": False}]


def _cascade(state: str = "", city: str = "") -> dict:
    """All states always; cities once a state is picked, stores once a city is
    picked -- until then, a disabled placeholder that says what to pick."""
    states = store_cache.list_states()
    data = {
        "states": _cap(_options(states), "state") or _placeholder(PLACEHOLDER_EMPTY),
        "cities": _placeholder(PLACEHOLDER_CITY),
        "stores": _placeholder(PLACEHOLDER_STORE),
    }
    if state:
        cities = store_cache.list_cities(state)
        data["cities"] = _cap(_options(cities), "city") or _placeholder(PLACEHOLDER_EMPTY)
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
        ) or _placeholder(PLACEHOLDER_EMPTY)
    return data


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
    # Optional: blank means "use this WhatsApp number" (the submission falls
    # back to it). A number that IS typed must look like one.
    digits = re.sub(r"\D", "", carried["phone"])
    if digits and not (10 <= len(digits) <= 13):
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
        return _route(action, screen, data_in, now, flow_token=str(decrypted.get("flow_token") or ""))
    except Exception:
        logger.exception("Store visit data_exchange failed", extra={"screen": screen})
        return {"screen": SCREEN_DETAILS, "data": details_screen_data(error=ERR_GENERIC)}


def _route(action: str, screen: str, data_in: dict, now: datetime | None, *, flow_token: str = "") -> dict:
    form = _carried(data_in)
    state = str(data_in.get("state") or "").strip()
    city = str(data_in.get("city") or "").strip()

    if action == "INIT":
        # The form's first screen, for WhatsApp and the preview alike.
        prefill = send_prefill(flow_token)
        return {
            "screen": SCREEN_DETAILS,
            "data": details_screen_data(prefill.get("first_name", ""), prefill.get("phone", "")),
        }

    if action == "BACK":
        # Back from date/time: the details + cascade screen, text kept.
        return _details_screen(form, state=state, city=city)

    step = str(data_in.get("step") or "").strip()

    # State / City picked: refresh screen 1 with the next list. Everything
    # typed so far comes back as init-values.
    if step == "state":
        return _details_screen(form, state=state)

    if step == "city":
        return _details_screen(form, state=state, city=city)

    # Next on screen 1: details and store checked together.
    if step == "store":
        error = _validate_details(form)
        if error:
            return _details_screen(form, state=state, city=city, error=error)
        store_id = str(data_in.get("store_id") or "").strip()
        if not store_id or store_id == "_none":
            return _details_screen(form, state=state, city=city, error=ERR_PICK_STORE)
        store = store_cache.get_store(store_id)
        if store is None:
            return _details_screen(form, state=state, city=city, error=ERR_STORE_GONE)
        if not date_window(store, now)["has_dates"]:
            return _details_screen(form, state=state, city=city, error=ERR_STORE_NO_DATES)
        return _datetime_screen(form, store, None, now)

    if step == "date":
        store = store_cache.get_store(str(data_in.get("store_id") or "").strip())
        if store is None:
            return _details_screen(form, error=ERR_STORE_GONE)
        return _datetime_screen(form, store, str(data_in.get("preferred_date") or ""), now)

    logger.warning(
        "Store visit data_exchange: unknown step",
        extra={"action": action, "screen": screen, "step": step},
    )
    return _details_screen(form, state=state, city=city, error=ERR_GENERIC)
