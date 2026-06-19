"""Send vendor_notification UTILITY template via Gupshup Partner API."""

import json
import os

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_TEMPLATE_URL
from kisna_chatbot.utils.env_load import gupshup_app_id, gupshup_app_name, gupshup_token
from kisna_chatbot.utils.logger_config import logger

VENDOR_NOTIFICATION_TEMPLATE_ID = (
    os.getenv("VENDOR_NOTIFICATION_TEMPLATE_ID") or ""
).strip()


def normalize_phone_number(phone_number: str) -> str:
    """Strip + and spaces; Gupshup expects E.164 without +."""
    return phone_number.strip().replace("+", "").replace(" ", "")


def send_vendor_notification_template(phone_number: str) -> dict | None:
    """
    Send the vendor_notification template to a phone number.

    Returns Gupshup JSON response, or None if template ID is not configured.
    """
    if not VENDOR_NOTIFICATION_TEMPLATE_ID:
        logger.warning(
            "VENDOR_NOTIFICATION_TEMPLATE_ID not set — skipping vendor notification",
            extra={"phone_number": phone_number},
        )
        return None

    destination = normalize_phone_number(phone_number)
    logger.info(
        "Sending vendor notification template",
        extra={"phone_number": destination},
    )

    url = GUPSHUP_TEMPLATE_URL.format(app_id=gupshup_app_id)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "token": gupshup_token,
    }
    data = {
        "source": GUPSHUP_SOURCE,
        "destination": destination,
        "src.name": gupshup_app_name,
        "template": json.dumps(
            {"id": VENDOR_NOTIFICATION_TEMPLATE_ID, "params": []}
        ),
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Vendor notification template sent",
            extra={"phone_number": destination, "response": result},
        )
        return result
    except Exception as e:
        logger.exception(
            "Error sending vendor notification template",
            extra={"phone_number": destination, "error": str(e)},
        )
        raise
