"""Store Visit Flow settings."""

from __future__ import annotations

import os

# "What are you looking for?" -- (id, title). Ids are stored and sent to
# Salesforce; titles are what the customer sees. Edit here, not in the JSON.
LOOKING_FOR_OPTIONS: tuple[tuple[str, str], ...] = (
    ("diamond_jewellery", "Diamond Jewellery"),
    ("gold_jewellery", "Gold Jewellery"),
    ("solitaires", "Solitaires"),
    ("engagement_bridal", "Engagement & Bridal"),
    ("gemstone_jewellery", "Gemstone Jewellery"),
    ("other", "Other"),
)

BOOKING_DAYS = 7          # today + the next 6 days
MIN_LEAD_MINUTES = 120    # a slot must start at least 2h from now
SLOT_MINUTES = 60

# WhatsApp caps a Dropdown's data-source at 200 options.
MAX_DROPDOWN_OPTIONS = 200

# Every Store Visit flow_token starts with this, then the flow id and a
# per-send nonce. The nonce makes the token unique per form sent, which is
# what the submission idempotency key relies on.
FLOW_TOKEN_PREFIX = "sv"


def get_store_visit_flow_id() -> str:
    return os.getenv("KISNA_STORE_VISIT_FLOW_ID", "").strip()


def store_visit_events_enabled() -> bool:
    """Push ``store_visit_requested`` to the Clara backend (-> Salesforce).
    Off by default until the client maps the event to a Salesforce object."""
    return os.getenv("KISNA_STORE_VISIT_EVENTS_ENABLED", "false").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def looking_for_title(option_id: str) -> str:
    return dict(LOOKING_FOR_OPTIONS).get(option_id, option_id)
