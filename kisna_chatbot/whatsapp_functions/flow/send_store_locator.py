import httpx

from kisna_chatbot.models.enums import FLowId
from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_token
)
from kisna_chatbot.utils.logger_config import logger


def send_store_locator_flow(phone_number: str, name: str = "there"):
    """Sends a store locator flow to a phone number."""
    logger.info(
        "Sending store locator flow to phone number",
        extra={"phone_number": phone_number},
    )
    url = f"https://partner.gupshup.io/partner/app/{gupshup_app_id}/v3/message"
    headers = {
        "Authorization": f"{gupshup_token}",
        "Content-Type": "application/json",
    }
    flow_id = FLowId.STORE_LOCATOR.value
    data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": f"{phone_number}",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Hello"},
            "body": {
                "text": (
                    f"Dear {name}, thank you for your interest in visiting us. \n"
                    "Could you please provide your area pincode? \n\n"
                    "I would be happy to share the location details of our nearest branch "
                    "and assist in scheduling your visit."
                )
            },
            "footer": {"text": "Managed by Nilkamal."},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_token": flow_id,
                    "flow_id": flow_id,
                    "flow_message_version": "3",
                    "flow_action": "navigate",
                    "flow_cta": "Find Store",
                },
            },
        },
    }

    try:
        response = httpx.post(url, headers=headers, json=data)
        logger.info("Response", extra={"response": response.json()})
        return response.json()
    except Exception as e:
        logger.error("Error in sending store locator flow", extra={"error": e})
        raise e
