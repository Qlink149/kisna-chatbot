import httpx

from kisna_chatbot.models.enums import FLowId
from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_token
)
from kisna_chatbot.utils.logger_config import logger


def send_damage_complaint_flow(phone_number: str):
    """Sends a damage complaint flow to a phone number."""
    logger.info(
        "Sending damage complaint flow to phone number",
        extra={"phone_number": phone_number},
    )
    url = f"https://partner.gupshup.io/partner/app/{gupshup_app_id}/v3/message"
    headers = {
        "Authorization": f"{gupshup_token}",
        "Content-Type": "application/json",
    }
    flow_id = FLowId.DAMAGE_COMPLAINT.value
    data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": f"{phone_number}",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Raise a complaint"},
            "body": {
                "text": "Please fill in the details to register your complaint."
            },
            "footer": {"text": "Kisna"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_token": flow_id,
                    "flow_id": flow_id,
                    "flow_message_version": "3",
                    "flow_action": "navigate",
                    "flow_cta": "Register Complaint",
                },
            },
        },
    }

    try:
        response = httpx.post(url, headers=headers, json=data)
        logger.info("Response", extra={"response": response.json()})
        return response.json()
    except Exception as e:
        logger.error("Error in sending damage complaint flow", extra={"error": e})
        raise e
