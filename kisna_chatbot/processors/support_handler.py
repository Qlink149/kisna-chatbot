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
    Outside hours / holiday: offline message + Request Callback quick reply.
    """
    status = get_support_status(now)
    customer_name = user_profile.get("username") or "Customer"

    if status["status"] == "open":
        user_profile["live_agent_requested_at"] = int(time.time())
        user_profile["live_agent_required"] = True
        _notify_admins(customer_name, phone_number)
        return [{"type": "text", "text": KIA_HANDOFF_MESSAGE}]

    if status["status"] == "closed_holiday":
        holiday = status.get("holiday", "a holiday")
        text = (
            f"Our team is currently offline for {holiday}. 🙏\n"
            "We'll be back the next working day.\n"
            "Would you like to request a callback?"
        )
    else:
        hours = format_support_hours_text()
        text = (
            "Our team is currently offline.\n"
            f"Support hours: {hours}.\n"
            "Would you like to request a callback?"
        )

    return [
        {
            "type": "quickreply",
            "text": text,
            "caption": "",
            "options": [{"title": "Request Callback"}],
            "msgid": HELP_CALLBACK_QR_MSGID,
        }
    ]
