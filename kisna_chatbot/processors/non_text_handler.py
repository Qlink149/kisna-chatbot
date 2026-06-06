"""Early handling for non-text WhatsApp inbound message types."""

from typing import Literal

from kisna_chatbot.models.enums import QuickReplyId
from kisna_chatbot.models.service_list import ServiceList as SL

NonTextResult = Literal["silent", "route_store"] | None

_SKIP_TYPES = frozenset({"text", "interactive"})

_IMAGE_TEXT = (
    "Thanks for sharing! I can't view images yet, but I'd love "
    "to help you find jewellery you'll love. 💎\n"
    "Tell me what you're looking for — rings, earrings, necklaces?"
)

_AUDIO_VIDEO_TEXT = (
    "I can't listen to voice notes yet — please type your "
    "question and I'll help you right away! 🙏"
)

_STICKER_TEXT = "Lovely! 😊 What jewellery can I help you find today?"

_CONTACTS_DOCUMENT_TEXT = (
    "Thanks! I can only help with jewellery browsing, orders, "
    "and store queries. What can I help you with today?"
)

_UNKNOWN_TEXT = (
    "I'm not sure how to handle that! Type your question "
    "or tap below to explore. 💎"
)


def _quick_reply(
    text: str,
    options: list[dict],
    *,
    msgid: str = QuickReplyId.NON_TEXT_BROWSE.value,
) -> dict:
    return {
        "type": "quickreply",
        "text": text,
        "caption": "",
        "options": options,
        "msgid": msgid,
    }


def _browse_offers_menu_options() -> list[dict]:
    return [
        {"title": "Browse Jewellery"},
        {"title": "View Offers"},
        {"title": "Open Menu"},
    ]


def _browse_menu_options() -> list[dict]:
    return [
        {"title": "Browse Jewellery"},
        {"title": "Open Menu"},
    ]


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
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    "Thanks for sharing your location! To find the nearest "
                    "KISNA store, please share your PIN code and I'll search "
                    "for you. 📍"
                ),
            }
        ]
        user_profile["service_selected"] = SL.AD_FLOW.value
        user_profile["awaiting_store_pincode"] = True
        return None

    if msg_type == "image":
        data["bot_response"] = [
            _quick_reply(_IMAGE_TEXT, _browse_offers_menu_options()),
        ]
        return None

    if msg_type in ("audio", "video"):
        data["bot_response"] = [
            _quick_reply(_AUDIO_VIDEO_TEXT, _browse_menu_options()),
        ]
        return None

    if msg_type == "sticker":
        data["bot_response"] = [
            _quick_reply(_STICKER_TEXT, _browse_offers_menu_options()),
        ]
        return None

    if msg_type in ("contacts", "document"):
        data["bot_response"] = [
            _quick_reply(_CONTACTS_DOCUMENT_TEXT, _browse_menu_options()),
        ]
        return None

    data["bot_response"] = [
        _quick_reply(_UNKNOWN_TEXT, _browse_menu_options()),
    ]
    return None
