"""Session TTL and transient flag hygiene."""

from __future__ import annotations

import time

SESSION_TTL_SECONDS = 2 * 60 * 60  # 2 hours

_TRANSIENT_KEYS = (
    "pending_clarification",
    "pending_flow_switch",
    "awaiting_store_pincode",
    "store_pincode_attempts",
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
    "shopping_wizard_active",
    "shopping_wizard_step",
    "shopping_wizard_data",
    "shopping_wizard_explicit",
    # An explicit "reply in English only" lasts until the user greets again or
    # the session expires — not forever.
    "language_override",
    # "Shall I connect you?" after customer-care details were sent.
    "awaiting_support_connect",
)

_SEARCH_CONTEXT_KEYS = (
    "last_search_filters",
    "last_search_products",
    "last_search_buffer",
    "last_search_page",
    "last_search_total",
    "last_search_api_total",
    "last_search_filter_ratio",
    "last_viewed_product",
    "shown_product_ids",
    "last_search_at",
    # Recap must die with the search session. Greeting used to leave
    # pending_search in Mongo, so Yes/No after "Hey" still owned the next tap.
    "pending_search",
    "awaiting_search_correction",
)

# Keys that processors pop() in memory. save_to_mongo is $set-only, so a pop
# otherwise leaves the old Mongo value (stale last_search_at after greeting).
# "language" is popped by _expire_session_now on TTL and must actually leave
# Mongo so the next session re-derives it.
_MONGO_UNSET_IF_MISSING = _TRANSIENT_KEYS + _SEARCH_CONTEXT_KEYS + ("language",)

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
        "shopping_wizard_active",
        "shopping_wizard_step",
        "shopping_wizard_data",
        "shopping_wizard_explicit",
        "pending_search",
        "awaiting_search_correction",
    ),
    "ad_flow": ("awaiting_store_pincode", "store_pincode_attempts"),
    "complaint": ("pending_clarification",),
    "callback": ("callback_capture_step", "callback_draft"),
    "general": ("pending_clarification",),
    "offers": (),
    "order_tracking": (),
}


def _has_any_transient(user_profile: dict) -> bool:
    for key in _TRANSIENT_KEYS:
        val = user_profile.get(key)
        if val in (None, False, "", {}, [], 0):
            continue
        return True
    return False


def clear_search_context(user_profile: dict) -> None:
    """Drop active search filters / shown products."""
    for key in _SEARCH_CONTEXT_KEYS:
        user_profile.pop(key, None)


def reset_transient_state(user_profile: dict, *, keep: frozenset[str] | None = None) -> None:
    """Drop one-shot / wizard flags. Optional keep set preserves named keys."""
    keep_set = keep or frozenset()
    for key in _TRANSIENT_KEYS:
        if key not in keep_set:
            user_profile.pop(key, None)


def _expire_session_now(user_profile: dict) -> None:
    reset_transient_state(user_profile)
    user_profile["service_selected"] = ""
    clear_search_context(user_profile)
    # Detected reply language is per-conversation, not a permanent preference: a
    # stale value (e.g. hi-Latn) must not outlive a multi-hour gap and keep
    # answering an all-English customer in Hinglish. It re-derives from the first
    # real message of the next session. An explicit "reply in English" override
    # lives in language_override, which reset_transient_state already clears.
    user_profile.pop("language", None)


def maybe_expire_session(user_profile: dict) -> None:
    """Clear stale wizard/session state when the user returns after TTL.

    If ``last_message_at`` is missing but sticky wait flags are set, treat the
    session as expired — otherwise flags can live forever (e.g. store pincode
    wait from weeks earlier).
    """
    last_at = user_profile.get("last_message_at")
    if not last_at:
        if _has_any_transient(user_profile):
            _expire_session_now(user_profile)
        return
    if time.time() - last_at <= SESSION_TTL_SECONDS:
        return
    _expire_session_now(user_profile)


def mongo_unset_for_missing_session_keys(user_profile: dict) -> dict:
    """Mongo `$unset` map for session keys popped from the in-memory profile."""
    if not isinstance(user_profile, dict):
        return {}
    return {key: "" for key in _MONGO_UNSET_IF_MISSING if key not in user_profile}


def reset_session_on_fresh_start(user_profile: dict) -> None:
    """Greeting / menu = fresh start: wipe waits and prior search context."""
    reset_transient_state(user_profile)
    user_profile["service_selected"] = ""
    clear_search_context(user_profile)


_STICKY_WAIT_KEYS = (
    "shopping_wizard_active",
    "shopping_wizard_step",
    "shopping_wizard_data",
    "shopping_wizard_explicit",
    "awaiting_store_pincode",
    "store_pincode_attempts",
    "awaiting_custom_budget",
    "custom_budget_attempts",
    "pending_search",
    "awaiting_search_correction",
)


def clear_all_sticky_states(user_profile: dict) -> None:
    """Reset every sticky wait. Call before any flow switch.

    Two sticky waits held at once is always a bug: whichever one the routing
    happens to check first silently eats the turn. Production users hit this
    with the wizard and the store wait both set — the wizard won, so their
    pincode was read as a budget and the store lookup never completed.
    """
    for key in _STICKY_WAIT_KEYS:
        user_profile.pop(key, None)


def start_store_lookup(user_profile: dict) -> None:
    """Begin the store pincode wait, clearing any conflicting flow.

    A store lookup and a shopping funnel cannot both own the next message.
    """
    clear_all_sticky_states(user_profile)
    user_profile["awaiting_store_pincode"] = True


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
