"""
Send KISNA welcome WhatsApp template via Gupshup Partner API.

MANUAL STEP — Gupshup dashboard:
The registered welcome template (KISNA_WELCOME_TEMPLATE_ID) must be updated
in the Gupshup dashboard to match KIA's first message. Code cannot change
approved template text — only the template ID is referenced here.

Suggested dashboard copy:
  💎 Welcome to Kisna!
  I'm KIA, your trusted jewellery assistant. Whether you're looking for the perfect piece,
  exploring our latest collections, checking today's offers, tracking an order, or need support,
  I'm here to make your shopping experience simple and enjoyable.
  What would you like to do today?
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
