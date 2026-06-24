import httpx

from kisna_chatbot.config.gupshup import get_budget_flow_id
from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_token,
)
from kisna_chatbot.utils.logger_config import logger


def send_budget_input_flow(phone_number: str):
    """Sends the budget custom-input Flow to a phone number."""
    flow_id = get_budget_flow_id()
    if not flow_id:
        logger.warning(
            "KISNA_BUDGET_FLOW_ID not set — skipping budget flow send",
            extra={"phone_number": phone_number},
        )
        return None

    logger.info(
        "Sending budget input flow to phone number",
        extra={"phone_number": phone_number},
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
            "header": {"type": "text", "text": "Set Your Budget"},
            "body": {
                "text": "Tell us your budget and we'll find the perfect jewellery for you. ✨"
            },
            "footer": {"text": "Kisna"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_token": flow_id,
                    "flow_id": flow_id,
                    "flow_message_version": "3",
                    "flow_action": "navigate",
                    "flow_cta": "Enter Budget",
                },
            },
        },
    }

    try:
        response = httpx.post(url, headers=headers, json=data, timeout=30)
        body = response.json()
        logger.info(
            "Budget input flow API response",
            extra={"status_code": response.status_code, "body": body},
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Gupshup flow send failed: HTTP {response.status_code} — {body}"
            )
        return body
    except Exception as e:
        logger.error(
            "Error sending budget input flow",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise
