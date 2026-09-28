"""Store Visit: the offer (form, or the locator link when the form can't be
sent) and the Flow submission (validate, save, push, confirm)."""

from __future__ import annotations

import json
import os
import re
import time

from pymongo.errors import DuplicateKeyError

from kisna_chatbot.config.store_visit import (
    LOOKING_FOR_OPTIONS,
    looking_for_title,
    store_visit_events_enabled,
)
from kisna_chatbot.database.collections import store_visits
from kisna_chatbot.integrations.clara_events import (
    build_store_visit_event,
    enqueue_event as enqueue_clara_event,
)
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.store_visit_flow import (
    is_store_visit_token,
    store_address_line,
)
from kisna_chatbot.prompts.form_copy import (
    STORE_VISIT_PREFORM,
    format_visit_scheduled_for,
    store_visit_confirmation,
    store_visit_pins,
)
from kisna_chatbot.stores import cache as store_cache
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.request_ids import generate_request_id
from kisna_chatbot.utils.store_visit_slots import clock_label, is_slot_bookable
from kisna_chatbot.utils.kisna_url_tracking import append_kisna_utm

SOURCE = "whatsapp_flow_v2"
STATUSES = ("new", "contacted", "visited", "cancelled", "no_show")

LOCATOR_LINE = "You can also browse all KISNA stores here: {url}"
LOCATOR_ONLY = "You can find your nearest KISNA store here: {url} 📍"

_REJECT_SLOT = (
    "Sorry, that time is no longer available. Please choose another slot "
    "in the form below."
)
_REJECT_STORE = (
    "Sorry, that store isn't taking bookings right now. Please choose "
    "another store in the form below."
)
_REJECT_DETAILS = "Some details were missing. Please fill in the form again below."
_GENERIC_ERROR = (
    "Sorry, we couldn't book your visit right now. Please try again in a moment."
)


def store_locator_url() -> str:
    url = (os.getenv("KISNA_STORE_LOCATOR_URL") or "").strip() or "https://www.kisna.com/store"
    return append_kisna_utm(url)


def build_store_visit_bot_response(user_profile: dict | None = None, data: dict | None = None) -> list[dict]:
    """The Store Visit offer: the form (client pre-form text as its body) with
    the locator link as a secondary line -- or only the link when the form
    can't be sent (flow id unset, or no bookable store). Never asks for a
    pincode."""
    from kisna_chatbot.whatsapp_functions.flow.send_store_visit_flow import (
        store_visit_form_available,
    )

    url = store_locator_url()
    if not store_visit_form_available():
        return [
            {
                "type": "text",
                "text": LOCATOR_ONLY.format(url=url),
                "_compose": "store_locator_link",
                "_pin": (url,),
            }
        ]
    profile = user_profile or {}
    name = profile.get("username") or (data or {}).get("whatsapp_username") or ""
    return [
        {
            "type": "flow",
            "flow": "store_visit",
            "text": STORE_VISIT_PREFORM,
            "name": name,
            "_compose": "store_visit_flow_prompt",
        },
        {
            "type": "text",
            "text": LOCATOR_LINE.format(url=url),
            "_compose": "store_locator_link",
            "_pin": (url,),
        },
    ]


def _parse_submission(messages: dict) -> dict | None:
    interactive = (messages or {}).get("interactive") or {}
    nfm = interactive.get("nfm_reply")
    if not isinstance(nfm, dict) or "response_json" not in nfm:
        return None
    try:
        flow_data = json.loads(nfm["response_json"])
    except (TypeError, ValueError):
        return None
    if not isinstance(flow_data, dict):
        return None
    if not is_store_visit_token(flow_data.get("flow_token")) and flow_data.get("request_type") != "store_visit":
        return None
    return flow_data


def _clean(flow_data: dict, key: str) -> str:
    return re.sub(r"\s+", " ", str(flow_data.get(key) or "")).strip()


def _confirmation_items(doc: dict) -> list[dict]:
    store = doc["store"]
    address = store_address_line(store)
    store_line = f"{store['name']}, {address}" if address else store["name"]
    scheduled_for = format_visit_scheduled_for(doc["preferred_date"], doc["preferred_time"])
    return [
        {
            "type": "text",
            "text": store_visit_confirmation(doc["request_id"], store_line, scheduled_for),
            "_compose": "store_visit_confirmed",
            "_pin": store_visit_pins(doc["request_id"], store["name"], address, scheduled_for),
        }
    ]


def _retry_items(text: str, user_profile: dict, data: dict) -> list[dict]:
    """The reason, then the form again (or the locator link if the form is
    no longer available)."""
    items = [{"type": "text", "text": text, "_compose": "store_visit_retry"}]
    offer = build_store_visit_bot_response(user_profile, data)
    flow = [i for i in offer if i.get("type") == "flow"]
    return items + (flow or offer)


def store_snapshot(store: dict) -> dict:
    return {
        k: store.get(k, "")
        for k in ("store_id", "name", "address", "city", "state", "pincode", "phone")
    }


class StoreVisitAgent(Processor):
    """Handles the Store Visit Flow submission (nfm_reply)."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        return _parse_submission(data.get("messages", {})) is not None

    async def process(self, data: dict) -> dict:
        if not self.should_run(data):
            return data
        flow_data = _parse_submission(data.get("messages", {}))
        phone_number = data.get("phone_number", "")
        user_profile = data.setdefault("user_profile", {})
        try:
            data["bot_response"] = await self._submit(data, user_profile, flow_data, phone_number)
        except Exception as e:
            logger.exception(
                "StoreVisitAgent submission failed",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR, "_compose": "system_error"}]
        user_profile["service_selected"] = ""
        return data

    async def _submit(self, data: dict, user_profile: dict, flow_data: dict, phone_number: str) -> list[dict]:
        flow_token = str(flow_data.get("flow_token") or "")
        if flow_token:
            existing = store_visits.find_one({"flow_token": flow_token}, {"_id": 0})
            if existing:
                logger.info(
                    "Store visit resubmitted; replaying confirmation",
                    extra={"phone_number": phone_number, "request_id": existing.get("request_id")},
                )
                return _confirmation_items(existing)

        first_name = _clean(flow_data, "first_name")
        mobile = re.sub(r"\D", "", _clean(flow_data, "phone")) or re.sub(r"\D", "", phone_number)
        looking_for = _clean(flow_data, "looking_for")
        if not first_name or looking_for not in dict(LOOKING_FOR_OPTIONS):
            return _retry_items(_REJECT_DETAILS, user_profile, data)

        store = store_cache.get_store(_clean(flow_data, "store_id"))
        if store is None:
            return _retry_items(_REJECT_STORE, user_profile, data)

        preferred_date = _clean(flow_data, "preferred_date")
        preferred_time = _clean(flow_data, "preferred_time")
        if not is_slot_bookable(store, preferred_date, preferred_time):
            return _retry_items(_REJECT_SLOT, user_profile, data)

        client_id = data.get("client_id") or getattr(data.get("client_config"), "client_id", "kisna")
        now = int(time.time())
        doc = {
            "request_id": generate_request_id("SV"),
            "flow_token": flow_token or None,
            "client_id": client_id,
            "phone_number": phone_number,
            "username": user_profile.get("username") or data.get("whatsapp_username", ""),
            "first_name": first_name,
            "last_name": _clean(flow_data, "last_name"),
            "email": _clean(flow_data, "email"),
            "mobile": mobile,
            "looking_for": looking_for,
            "looking_for_label": looking_for_title(looking_for),
            "store": store_snapshot(store),
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "preferred_time_label": clock_label(preferred_time),
            "language": user_profile.get("language") or "en",
            "status": "new",
            "status_history": [{"status": "new", "by": "customer", "at": now}],
            "source": SOURCE,
            "created_at": now,
        }
        if not flow_token:
            doc.pop("flow_token")
        try:
            store_visits.insert_one(doc)
        except DuplicateKeyError:
            existing = store_visits.find_one({"flow_token": flow_token}, {"_id": 0})
            if existing:
                return _confirmation_items(existing)
            raise
        doc.pop("_id", None)

        if store_visit_events_enabled():
            await enqueue_clara_event(
                build_store_visit_event(
                    request_id=doc["request_id"],
                    client_id=client_id,
                    phone_number=phone_number,
                    customer_name=f"{first_name} {doc['last_name']}".strip(),
                    first_name=first_name,
                    last_name=doc["last_name"],
                    email=doc["email"],
                    mobile=mobile,
                    looking_for=looking_for,
                    looking_for_label=doc["looking_for_label"],
                    store=doc["store"],
                    preferred_date=preferred_date,
                    preferred_time=preferred_time,
                    preferred_time_label=doc["preferred_time_label"],
                    occurred_at_epoch=now,
                )
            )

        logger.info(
            "Store visit booked",
            extra={
                "phone_number": phone_number,
                "request_id": doc["request_id"],
                "store_id": store["store_id"],
                "preferred_date": preferred_date,
                "preferred_time": preferred_time,
            },
        )
        return _confirmation_items(doc)
