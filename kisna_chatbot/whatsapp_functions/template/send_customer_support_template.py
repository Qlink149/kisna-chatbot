import json

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE
from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_app_name,
    gupshup_token,
)
from kisna_chatbot.utils.logger_config import logger

# Replace with Kisna Gupshup template ID when configured
TEMPLATE_ID = "c7c34ecc-8021-451d-ba88-5a43c04911a5"


def send_customer_support_template(phone_number: str, customer_name: str, customer_phone: str):
    """Sends the customer_support_1 template to notify support about a customer request."""
    logger.info(
        "Sending customer support template",
        extra={"phone_number": phone_number, "customer_name": customer_name},
    )
    url = f"https://partner.gupshup.io/partner/app/{gupshup_app_id}/template/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "token": gupshup_token,
    }
    data = {
        "source": GUPSHUP_SOURCE,
        "destination": phone_number,
        "src.name": gupshup_app_name,
        "template": json.dumps({
            "id": TEMPLATE_ID,
            "params": [customer_name, customer_phone],
        }),
        "message": json.dumps({
            "type": "text",
            "text": (
                f"Customer Name: {customer_name}\n"
                f"Phone Number: {customer_phone}\n\n"
                "A customer has requested to speak with a support representative. "
                "Please connect at the earliest."
            ),
        }),
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        logger.info(
            "Customer support template sent",
            extra={"phone_number": phone_number, "response": response.json()},
        )
        return response.json()
    except Exception as e:
        logger.error(
            "Error sending customer support template",
            extra={"phone_number": phone_number, "error": e},
        )
        raise e
