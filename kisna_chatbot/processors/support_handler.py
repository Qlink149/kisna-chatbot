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
    Outside hours / holiday: send callback form directly (agent = pick a slot).
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
    responses: list[dict] = [{"type": "text", "text": offline_text}]
    if get_callback_flow_id():
        responses.append(build_callback_flow_bot_response())
    else:
        responses.extend(
            _start_callback_text_capture(user_profile, request_type="callback")
        )
    return responses
