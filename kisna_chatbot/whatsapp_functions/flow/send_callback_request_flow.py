import httpx
from datetime import datetime, timedelta, timezone

from kisna_chatbot.config.gupshup import get_callback_flow_id
from kisna_chatbot.utils.env_load import gupshup_app_id, gupshup_token
from kisna_chatbot.utils.logger_config import logger

_IST = timezone(timedelta(hours=5, minutes=30))


def send_callback_request_flow(phone_number: str):
    """Sends the callback request WhatsApp Flow."""
    flow_id = get_callback_flow_id()
    if not flow_id:
        logger.warning(
            "KISNA_CALLBACK_FLOW_ID not set — skipping callback flow send",
            extra={"phone_number": phone_number},
        )
        return None

    min_date = datetime.now(_IST).date().isoformat()
    logger.info(
        "Sending callback request flow",
        extra={"phone_number": phone_number, "min_date": min_date},
    )
    url = f"https://partner.gupshup.io/partner/app/{gupshup_app_id}/v3/message"
    headers = {
        "Authorization": f"{gupshup_token}",
        "Content-Type": "application/json",
    }
    data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": f"{phone_number}",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Callback Request"},
            "body": {"text": "Please share your details and we'll call you back."},
            "footer": {"text": "Kisna"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_token": flow_id,
                    "flow_id": flow_id,
                    "flow_message_version": "3",
                    "flow_action": "data_exchange",
                    "flow_cta": "Request Callback",
                    "flow_action_payload": {
                        "screen": "CALLBACK_REQUEST",
                        "data": {"min_date": min_date},
                    },
                },
            },
        },
    }

    try:
        response = httpx.post(url, headers=headers, json=data, timeout=30)
        body = response.json()
        logger.info(
            "Callback request flow API response",
            extra={"status_code": response.status_code, "body": body},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Gupshup flow send failed: HTTP {response.status_code} — {body}"
            )
        return body
    except Exception as e:
        logger.error(
            "Error sending callback request flow",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise
