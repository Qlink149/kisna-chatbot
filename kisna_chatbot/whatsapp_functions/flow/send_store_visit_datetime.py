import httpx

from kisna_chatbot.models.enums import FLowId
from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_token,
)
from kisna_chatbot.utils.logger_config import logger


def send_store_visit_datetime_flow(phone_number: str, bot_response):
    """Sends a store visit date/time booking flow to a phone number."""
    logger.info(
        "Sending store visit datetime flow to phone number",
        extra={"phone_number": phone_number},
    )
    url = f"https://partner.gupshup.io/partner/app/{gupshup_app_id}/v3/message"
    headers = {
        "Authorization": f"{gupshup_token}",
        "Content-Type": "application/json",
    }
    flow_id = FLowId.STORE_VISIT_DATETIME.value
    store_name = bot_response.get("store_name")
    data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": f"{phone_number}",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Book Your Exclusive Visit"},
            "body": {
                "text": "Book your exclusive visit to Nilkamal Sleep Nova and receive an additional 5% discount when you reserve your spot now. Our sleep consultants will guide you to your ideal comfort match.\n\nBecause you deserve the best sleep of your life."
            },
            "footer": {"text": "Managed by Nilkamal."},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_token": f"{flow_id}${store_name}",
                    "flow_id": flow_id,
                    "flow_message_version": "3",
                    "flow_action": "navigate",
                    "flow_cta": "Book Your Visit",
                },
            },
        },
    }

    try:
        response = httpx.post(url, headers=headers, json=data)
        logger.info("Response", extra={"response": response.json()})
        return response.json()
    except Exception as e:
        logger.error("Error in sending store visit datetime flow", extra={"error": e})
        raise e
