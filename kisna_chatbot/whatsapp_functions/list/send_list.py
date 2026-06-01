import json

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_URL
from kisna_chatbot.utils.env_load import (
    gupshup_api_key,
    gupshup_app_name,
)
from kisna_chatbot.utils.logger_config import logger


def send_list(phone_number, bot_response):
    """Send a list message to a phone number."""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    data = {
        "source": GUPSHUP_SOURCE,
        "destination": f"{phone_number}",
        "src.name": gupshup_app_name,
        "message": json.dumps(
            {
                "type": "list",
                "title": bot_response.get("title", ""),
                "body": bot_response["body"],
                "footer": bot_response.get("footer", ""),
                "msgid": bot_response["msgid"],
                "globalButtons": bot_response["globalButtons"],
                "items": bot_response["items"],
            }
        ),
    }

    try:
        response = httpx.post(GUPSHUP_URL, headers=headers, data=data)
        logger.info(
            "Response from Gupshup API for sending list",
            extra={"phone_number": phone_number, "response": response.json()},
        )
        return response.json()
    except Exception as e:
        logger.error(
            "Error while sending list",
            extra={"phone_number": phone_number, "error": e},
        )
        raise e
