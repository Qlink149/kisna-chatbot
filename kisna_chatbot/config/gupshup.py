"""Gupshup WhatsApp configuration helpers (env read at call time)."""

import os
from functools import lru_cache

from kisna_chatbot.models.enums import FLowId


def get_gupshup_source() -> str:
    """WhatsApp sender number (E.164 without +). GUPSHUP_SOURCE alone is sufficient."""
    return os.getenv("GUPSHUP_PHONE_NUMBER", "") or os.getenv("GUPSHUP_SOURCE", "")


def get_damage_complaint_flow_id() -> str:
    """WhatsApp Flow id for damage/complaint form (Kisna WABA)."""
    override = os.getenv("KISNA_DAMAGE_COMPLAINT_FLOW_ID", "").strip()
    if override:
        return override
    return FLowId.DAMAGE_COMPLAINT.value


def get_budget_flow_id() -> str:
    """WhatsApp Flow id for budget custom-input form. Empty string when not configured."""
    return os.getenv("KISNA_BUDGET_FLOW_ID", "").strip()


@lru_cache(maxsize=1)
def build_phone_number_id_map() -> dict[str, str]:
    """
    Map Meta phone_number_id from webhook metadata to client_id slug.

    Only non-empty env values are included.
    """
    mapping: dict[str, str] = {}
    kisna_id = os.getenv("KISNA_PHONE_NUMBER_ID", "").strip()
    if kisna_id:
        mapping[kisna_id] = "kisna"
    nkl_id = os.getenv("NKL_PHONE_NUMBER_ID", "").strip()
    if nkl_id:
        mapping[nkl_id] = "nkl"
    return mapping


def refresh_phone_number_id_map() -> None:
    """Clear cached phone_number_id map (e.g. after env changes in tests)."""
    build_phone_number_id_map.cache_clear()
