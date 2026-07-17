"""Session TTL and transient flag hygiene."""

from __future__ import annotations

import time

SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours

_TRANSIENT_KEYS = (
    "pending_clarification",
    "pending_flow_switch",
    "awaiting_store_pincode",
    "awaiting_rating",
    "awaiting_custom_budget",
    "callback_capture_step",
    "callback_draft",
    "preference_step",
    "pref_category",
    "pref_material",
    "pref_type",
    "pref_title",
    "custom_budget_attempts",
    "pending_vague_slot_fill",
    "pending_variant_select",
    "_price_direction_hint",
)

_SERVICE_TRANSIENT_KEYS: dict[str, tuple[str, ...]] = {
    "product_search": (
        "pending_vague_slot_fill",
        "awaiting_custom_budget",
        "preference_step",
        "pref_category",
        "pref_material",
        "pref_type",
        "pref_title",
        "custom_budget_attempts",
    ),
    "ad_flow": ("awaiting_store_pincode",),
    "complaint": ("pending_clarification",),
    "callback": ("callback_capture_step", "callback_draft"),
    "general": ("pending_clarification",),
    "offers": (),
    "order_tracking": (),
}


def maybe_expire_session(user_profile: dict) -> None:
    """Clear stale wizard/session state when the user returns after TTL."""
    last_at = user_profile.get("last_message_at")
    if not last_at:
        return
    if time.time() - last_at <= SESSION_TTL_SECONDS:
        return
    reset_transient_state(user_profile)
    user_profile["service_selected"] = ""
    user_profile.pop("last_search_filters", None)
    user_profile.pop("last_search_products", None)
    user_profile.pop("last_viewed_product", None)
    user_profile.pop("shown_product_ids", None)


def reset_transient_state(user_profile: dict, *, keep: frozenset[str] | None = None) -> None:
    """Drop one-shot / wizard flags. Optional keep set preserves named keys."""
    keep_set = keep or frozenset()
    for key in _TRANSIENT_KEYS:
        if key not in keep_set:
            user_profile.pop(key, None)


def clear_transient_for_service_change(
    user_profile: dict,
    *,
    from_service: str,
    to_service: str,
) -> None:
    """Clear flags from the service being left when intent routes elsewhere."""
    if from_service == to_service:
        return
    keys_to_clear: set[str] = set(_TRANSIENT_KEYS)
    keys_to_clear.update(_SERVICE_TRANSIENT_KEYS.get(from_service, ()))
    keys_to_clear.update(_SERVICE_TRANSIENT_KEYS.get(to_service, ()))
    for key in keys_to_clear:
        user_profile.pop(key, None)
