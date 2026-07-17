"""Early handling for non-text WhatsApp inbound message types."""

from typing import Literal

from kisna_chatbot.models.service_list import ServiceList as SL

NonTextResult = Literal["silent", "route_store"] | None

_SKIP_TYPES = frozenset({"text", "interactive"})

_NON_TEXT_FALLBACK = (
    "I can't read images or audio yet — just tell me in words what you're looking for 🙂"
)

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
        data["bot_response"] = [{"type": "text", "text": _LOCATION_PINCODE_TEXT}]
        user_profile["service_selected"] = SL.AD_FLOW.value
        user_profile["awaiting_store_pincode"] = True
        return None

    if msg_type == "sticker":
        data["bot_response"] = [{"type": "text", "text": _STICKER_TEXT}]
        return None

    # image, audio, video, contacts, document, unknown
    data["bot_response"] = [{"type": "text", "text": _NON_TEXT_FALLBACK}]
    return None
