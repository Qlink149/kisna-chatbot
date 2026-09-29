#!/usr/bin/env python3
"""Generate json/store_visit.json -- the Store Visit WhatsApp Flow.

    python scripts/build_store_visit_flow_json.py

Layout (mirrors the client's reference form):
  SV_DETAILS  "Schedule a Store Visit!" / "Find Your Nearest Store":
              First Name, Last Name (optional), Email ID (optional),
              Phone No (optional), Looking for, Select your State,
              Select your City, Nearest Kisna Store. WhatsApp itself marks
              optional fields "(Optional)"; required ones carry no marker.
              State -> City -> Store refresh this same screen via
              data_exchange (processors/store_visit_flow.py). Every dropdown
              has a data-source from the first render: all states; City and
              Store start as one disabled placeholder.
              The first screen always comes from the endpoint's INIT (the
              WhatsApp send and the preview both use flow_action
              data_exchange).
  SV_DATETIME date + time, "Submit".

Typed text survives a State / City refresh on the server side regardless of
client behaviour: each on-select payload carries every field's current value
(${form.*}) and the endpoint returns them as the form's init-values.

Meta limits honoured (checked by tests/test_store_visit.py): input labels
<= 20 chars; prefills via Form "init-values" (component init-value is
rejected in Flow JSON 7.0).
"""

from __future__ import annotations

import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "json" / "store_visit.json"

DETAILS = ("first_name", "last_name", "email", "phone", "looking_for")

OPTION = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "enabled": {"type": "boolean"},
    },
}
STORE_OPTION = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "enabled": {"type": "boolean"},
    },
}


def s(example=""):
    return {"type": "string", "__example__": example}


def arr(items, example):
    return {"type": "array", "items": items, "__example__": example}


def init_obj(example):
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in example},
        "__example__": example,
    }


def form_fields() -> dict:
    """Every screen-1 field's current value, for data_exchange payloads."""
    return {k: "${form.%s}" % k for k in DETAILS}


def carried_data() -> dict:
    return {k: s("") for k in DETAILS}


def carried_payload() -> dict:
    return {k: "${data.%s}" % k for k in DETAILS}


details_screen = {
    "id": "SV_DETAILS",
    "title": "Schedule a Store Visit!",
    "data": {
        "looking_for_options": arr(OPTION, [{"id": "diamond_jewellery", "title": "Diamond Jewellery"}]),
        "states": arr(OPTION, [{"id": "Punjab", "title": "Punjab"}]),
        "cities": arr(OPTION, [{"id": "_none", "title": "Select a state first", "enabled": False}]),
        "stores": arr(
            STORE_OPTION,
            [{"id": "_none", "title": "Select a city first", "enabled": False}],
        ),
        "details_error": s(""),
        "init_values": init_obj(
            {
                "first_name": "Priya",
                "last_name": "",
                "email": "",
                "phone": "919812345678",
                "looking_for": "",
                "state": "",
                "city": "",
            }
        ),
    },
    "layout": {
        "type": "SingleColumnLayout",
        "children": [
            {
                "type": "Form",
                "name": "details_form",
                "init-values": "${data.init_values}",
                "children": [
                    {"type": "TextHeading", "text": "Find Your Nearest Store"},
                    {
                        "type": "TextInput",
                        "name": "first_name",
                        "label": "First Name",
                        "required": True,
                        "input-type": "text",
                    },
                    {
                        "type": "TextInput",
                        "name": "last_name",
                        "label": "Last Name",
                        "required": False,
                        "input-type": "text",
                    },
                    {
                        "type": "TextInput",
                        "name": "email",
                        "label": "Email ID",
                        "required": False,
                        "input-type": "email",
                    },
                    {
                        "type": "TextInput",
                        "name": "phone",
                        "label": "Phone No",
                        "required": False,
                        "input-type": "phone",
                        "helper-text": "Leave blank to use this WhatsApp number",
                    },
                    {
                        "type": "Dropdown",
                        "name": "looking_for",
                        "label": "Looking for",
                        "required": True,
                        "data-source": "${data.looking_for_options}",
                    },
                    {
                        "type": "Dropdown",
                        "name": "state",
                        "label": "Select your State",
                        "required": True,
                        "data-source": "${data.states}",
                        "on-select-action": {
                            "name": "data_exchange",
                            "payload": {"step": "state", "state": "${form.state}", **form_fields()},
                        },
                    },
                    {
                        "type": "Dropdown",
                        "name": "city",
                        "label": "Select your City",
                        "required": True,
                        "data-source": "${data.cities}",
                        "on-select-action": {
                            "name": "data_exchange",
                            "payload": {
                                "step": "city",
                                "state": "${form.state}",
                                "city": "${form.city}",
                                **form_fields(),
                            },
                        },
                    },
                    {
                        "type": "Dropdown",
                        "name": "store_id",
                        "label": "Nearest Kisna Store",
                        "required": True,
                        "data-source": "${data.stores}",
                    },
                    {"type": "TextBody", "text": "${data.details_error}"},
                    {
                        "type": "Footer",
                        "label": "Next",
                        "on-click-action": {
                            "name": "data_exchange",
                            "payload": {
                                "step": "store",
                                "state": "${form.state}",
                                "city": "${form.city}",
                                "store_id": "${form.store_id}",
                                **form_fields(),
                            },
                        },
                    },
                ],
            }
        ],
    },
}

datetime_screen = {
    "id": "SV_DATETIME",
    "title": "Choose Date & Time",
    "terminal": True,
    "data": {
        **carried_data(),
        "store_id": s("F203"),
        "store_name": s("INA Colony - Amritsar - Punjab"),
        "store_address": s("Mall Road, Amritsar 143001"),
        "min_date": s("2026-09-30"),
        "max_date": s("2026-10-06"),
        "unavailable_dates": arr({"type": "string"}, ["2026-10-02"]),
        "selected_date": s(""),
        "time_slots": arr(OPTION, [{"id": "11:30", "title": "11:30 AM"}]),
        "slot_error": s(""),
        "init_values": init_obj({"preferred_date": "2026-09-30"}),
    },
    "layout": {
        "type": "SingleColumnLayout",
        "children": [
            {
                "type": "Form",
                "name": "datetime_form",
                "init-values": "${data.init_values}",
                "children": [
                    {"type": "TextSubheading", "text": "${data.store_name}"},
                    {"type": "TextCaption", "text": "${data.store_address}"},
                    {
                        "type": "DatePicker",
                        "name": "preferred_date",
                        "label": "Visit date",
                        "required": True,
                        "min-date": "${data.min_date}",
                        "max-date": "${data.max_date}",
                        "unavailable-dates": "${data.unavailable_dates}",
                        "on-select-action": {
                            "name": "data_exchange",
                            "payload": {
                                "step": "date",
                                "store_id": "${data.store_id}",
                                "preferred_date": "${form.preferred_date}",
                                **carried_payload(),
                            },
                        },
                    },
                    {"type": "TextBody", "text": "${data.slot_error}"},
                    {
                        "type": "Dropdown",
                        "name": "preferred_time",
                        "label": "Visit time",
                        "required": True,
                        "data-source": "${data.time_slots}",
                    },
                    {
                        "type": "Footer",
                        "label": "Submit",
                        "on-click-action": {
                            "name": "complete",
                            "payload": {
                                "request_type": "store_visit",
                                "store_id": "${data.store_id}",
                                "preferred_date": "${form.preferred_date}",
                                "preferred_time": "${form.preferred_time}",
                                **carried_payload(),
                            },
                        },
                    },
                ],
            }
        ],
    },
}

FLOW = {
    "version": "7.0",
    "data_api_version": "3.0",
    "routing_model": {"SV_DETAILS": ["SV_DATETIME"], "SV_DATETIME": []},
    "screens": [details_screen, datetime_screen],
}


if __name__ == "__main__":
    OUT.write_text(json.dumps(FLOW, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)
