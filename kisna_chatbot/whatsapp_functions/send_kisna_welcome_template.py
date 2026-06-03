"""
Send KISNA welcome WhatsApp template via Gupshup Partner API.

Gupshup dashboard template text (for submission):
Welcome to KISNA Diamond & Gold! 💎
Explore certified rings, earrings, necklaces & more.
Reply Hi to get started.
"""

import json
import os

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_TEMPLATE_URL
from kisna_chatbot.utils.env_load import gupshup_app_id, gupshup_app_name, gupshup_token
from kisna_chatbot.utils.logger_config import logger

KISNA_WELCOME_TEMPLATE_ID = (os.getenv("KISNA_WELCOME_TEMPLATE_ID") or "").strip()


def send_kisna_welcome_template(phone_number: str) -> dict | None:
    """
    Send the KISNA welcome template to a new user.

    Returns Gupshup JSON response, or None if template ID is not configured.
    """
    if not KISNA_WELCOME_TEMPLATE_ID:
        logger.warning(
            "KISNA_WELCOME_TEMPLATE_ID not set — skipping welcome template",
            extra={"phone_number": phone_number},
        )
        return None

    logger.info(
        "Sending KISNA welcome template",
        extra={"phone_number": phone_number},
    )

    url = GUPSHUP_TEMPLATE_URL.format(app_id=gupshup_app_id)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "token": gupshup_token,
    }
    data = {
        "source": GUPSHUP_SOURCE,
        "destination": phone_number,
        "src.name": gupshup_app_name,
        "template": json.dumps({"id": KISNA_WELCOME_TEMPLATE_ID, "params": []}),
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "KISNA welcome template sent",
            extra={"phone_number": phone_number, "response": result},
        )
        return result
    except Exception as e:
        logger.exception(
            "Error sending KISNA welcome template",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        return None
