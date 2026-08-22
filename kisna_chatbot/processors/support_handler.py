"""Expert support / callback routing based on support availability."""

from __future__ import annotations

import time

from kisna_chatbot.constants import ADMINS, KIA_HANDOFF_MESSAGE
from kisna_chatbot.utils.support_hours import format_support_hours_text, get_support_status
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)

HELP_CALLBACK_POSTBACK = "help$callback"
HELP_CALLBACK_QR_MSGID = "help$callback$qr"

SUPPORT_CONTACT_MSGID = "support$contact$qr"


def build_support_contact_response(user_profile: dict) -> list[dict]:
    """Answer "what's the customer care number?" with the details, then offer.

    Asking FOR a contact number is not the same as asking to be put through.
    Handing such a user straight to an agent both fails to answer the question
    and pages a human who was never needed — so give the details first and let
    the user choose.
    """
    from kisna_chatbot.prompts.general_agent_kisna import (
        _SUPPORT_EMAIL,
        _SUPPORT_PHONE,
    )

    status = get_support_status()
    hours = format_support_hours_text()
    open_now = status["status"] == "open"

    lines = [
        "Here are our customer care details 📞",
        "",
        f"• Phone: {_SUPPORT_PHONE}",
        f"• Email: {_SUPPORT_EMAIL}",
        f"• Hours: {hours}",
    ]
    lines.append("")
    if open_now:
        lines.append(
            "Would you like me to connect you with a representative right now?"
        )
    else:
        lines.append(
            "Our team is offline at the moment — I can arrange a callback "
            "instead. Would you like that?"
        )

    user_profile["awaiting_support_connect"] = True
    return [
        {
            "type": "quickreply",
            "text": "\n".join(lines),
            "caption": "",
            "options": [
                {"title": "Yes, connect me"},
                {"title": "No, thanks"},
            ],
            "msgid": SUPPORT_CONTACT_MSGID,
            "_compose": "support_contact",
        }
    ]


def _notify_admins(customer_name: str, customer_phone: str) -> None:
    for admin in ADMINS:
        send_customer_support_template(
            phone_number=admin,
            customer_name=customer_name,
            customer_phone=customer_phone,
        )


def build_expert_support_bot_response(
    phone_number: str,
    user_profile: dict,
    *,
    now=None,
) -> list[dict]:
    """
    Build bot_response for expert / human-handoff requests.

    During open hours: flag live agent + handoff message.
    Outside hours / holiday: send callback form directly (agent = pick a slot).
    """
    status = get_support_status(now)
    customer_name = user_profile.get("username") or "Customer"

    if status["status"] == "open":
        user_profile["live_agent_requested_at"] = int(time.time())
        user_profile["live_agent_required"] = True
        _notify_admins(customer_name, phone_number)
        # Same reason as the offline branch below: untagged text is never
        # localised, so this reached every non-English customer in English.
        return [
            {
                "type": "text",
                "text": KIA_HANDOFF_MESSAGE,
                "_compose": "support_handoff",
            }
        ]

    if status["status"] == "closed_holiday":
        holiday = status.get("holiday", "a holiday")
        offline_text = (
            f"Our team is currently offline for {holiday}. 🙏\n"
            "We'll be back the next working day.\n"
            "Meanwhile, you can pick a callback slot below and we'll call you back."
        )
    else:
        hours = format_support_hours_text()
        offline_text = (
            "Our team is currently offline.\n"
            f"Support hours: {hours}.\n"
            "Meanwhile, you can pick a callback slot below and we'll call you back."
        )

    # Offline / holiday → offline message + callback form (or text capture fallback)
    from kisna_chatbot.config.gupshup import get_callback_flow_id
    from kisna_chatbot.models.service_list import ServiceList as SL
    from kisna_chatbot.processors.service_list import (
        _start_callback_text_capture,
        build_callback_flow_bot_response,
    )

    user_profile["service_selected"] = SL.CALLBACK.value
    # Tagged so localize_bot_responses mirrors it into the customer's
    # language. Untagged messages are skipped outright, so a Marathi
    # customer asking for a human was told "Our team is currently offline"
    # in English -- the one moment in the conversation they most need to
    # understand the answer.
    responses: list[dict] = [
        {"type": "text", "text": offline_text, "_compose": "support_offline"}
    ]
    if get_callback_flow_id():
        responses.append(build_callback_flow_bot_response())
    else:
        responses.extend(
            _start_callback_text_capture(user_profile, request_type="callback")
        )
    return responses
