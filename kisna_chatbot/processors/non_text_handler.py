"""Early handling for non-text WhatsApp inbound message types."""

import time
from typing import Literal

from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.utils.session_state import start_store_lookup

NonTextResult = Literal["silent", "route_store"] | None

_SKIP_TYPES = frozenset({"text", "interactive"})
_MEDIA_TYPES = frozenset({"image", "audio", "video", "document"})

_NON_TEXT_FALLBACK = (
    "I can't read images or audio yet — just tell me in words what you're looking for 🙂"
)

_MEDIA_HANDOFF_LEAD_IN = (
    "I can't view images or listen to voice notes yet — let me connect you to a "
    "Kisna representative who can help with that."
)

# One acknowledgement per burst, not one per file: five voice notes in a row
# (real: a live customer did exactly this) used to get five identical
# refusals and, with the flag on, would otherwise arm five separate handoff
# timers. Same reasoning as the offers cooldown (F7).
_MEDIA_FALLBACK_COOLDOWN_SECONDS = 60

_STICKER_TEXT = "Lovely! 😊 What jewellery can I help you find today?"

_LOCATION_PINCODE_TEXT = (
    "Thanks for sharing your location! To find the nearest "
    "KISNA store, please share your PIN code and I'll search "
    "for you. 📍"
)


def handle_non_text_message(data: dict) -> NonTextResult:
    """
    Handle non-text inbound messages before classifier/agents run.

    Returns:
        None — continue normal pipeline (text/interactive)
        "silent" — ignore (reactions)
        "route_store" — run AdFlowPipeline with inbound_location set
    Sets data["bot_response"] for types that need an immediate reply.
    """
    messages = data.get("messages") or {}
    msg_type = messages.get("type", "")

    if msg_type in _SKIP_TYPES:
        return None

    if msg_type == "reaction":
        return "silent"

    user_profile = data.setdefault("user_profile", {})

    if msg_type == "location":
        loc = messages.get("location") or {}
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        if lat is not None and lng is not None:
            user_profile["service_selected"] = SL.AD_FLOW.value
            user_profile["awaiting_store_pincode"] = False
            data["inbound_location"] = {"lat": float(lat), "lng": float(lng)}
            data["classified_category"] = "store_info"
            return "route_store"
        data["bot_response"] = [{"type": "text", "text": _LOCATION_PINCODE_TEXT, "_compose": "store_pincode"}]
        user_profile["service_selected"] = SL.AD_FLOW.value
        start_store_lookup(user_profile)
        return None

    if msg_type == "sticker":
        data["bot_response"] = [{"type": "text", "text": _STICKER_TEXT, "_compose": "sticker_ack"}]
        return None

    # image, audio, video, contacts, document, unknown
    if msg_type not in _MEDIA_TYPES:
        data["bot_response"] = [
            {"type": "text", "text": _NON_TEXT_FALLBACK, "_compose": "non_text_fallback"}
        ]
        return None

    now = time.time()
    last_at = user_profile.get("media_fallback_last_at")
    try:
        in_cooldown = last_at is not None and (now - float(last_at)) < _MEDIA_FALLBACK_COOLDOWN_SECONDS
    except (TypeError, ValueError):
        in_cooldown = False
    if in_cooldown:
        # Already acknowledged this burst -- stay quiet rather than repeat
        # either the apology or a second handoff/callback offer. Returning
        # "silent" skips save_to_mongo for this turn (see main.py), so the
        # cooldown window stays anchored to the first message of the burst
        # rather than sliding on every follow-up -- fine, it only needs to
        # cover one burst, not implement a rolling window.
        return "silent"
    user_profile["media_fallback_last_at"] = now

    # Lazy import: support_handler -> service_list, a module-level import here
    # would be a cycle (same dance classifier.py already does for this call).
    from kisna_chatbot.processors.support_handler import build_expert_support_bot_response

    lead_in = {
        "type": "text",
        "text": _MEDIA_HANDOFF_LEAD_IN,
        "_compose": "non_text_handoff_lead_in",
    }
    phone_number = data.get("phone_number", "")
    data["bot_response"] = [lead_in, *build_expert_support_bot_response(phone_number, user_profile)]
    return None
