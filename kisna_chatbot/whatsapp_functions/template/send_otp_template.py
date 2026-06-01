import json
import os

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_TEMPLATE_URL
from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_app_name,
    gupshup_token,
)
from kisna_chatbot.utils.logger_config import logger

# Replace with Kisna Gupshup OTP template ID when configured
_DEFAULT_OTP_TEMPLATE_ID = "782fa1ad-6005-499c-adee-db25ac82e368"
OTP_TEMPLATE_ID = os.getenv("GUPSHUP_OTP_TEMPLATE_ID", _DEFAULT_OTP_TEMPLATE_ID)


def send_otp_template(phone_number: str, otp_code: str) -> dict:
    """
    Send an OTP authentication template via Gupshup partner template API.

    Args:
        phone_number: Recipient WhatsApp number.
        otp_code: One-time password to include in template params.

    Returns:
        Parsed JSON response from Gupshup.

    Raises:
        Exception: On HTTP or network failure.
    """
    logger.info(
        "Sending OTP template",
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
        "template": json.dumps(
            {
                "id": OTP_TEMPLATE_ID,
                "params": [otp_code, otp_code],
            }
        ),
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "OTP template sent",
            extra={"phone_number": phone_number, "response": result},
        )
        return result
    except Exception as e:
        logger.exception(
            "Error sending OTP template",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise
