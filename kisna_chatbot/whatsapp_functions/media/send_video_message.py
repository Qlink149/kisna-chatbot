import json

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger


def send_video_message(phone_number: str, bot_response: dict):
    """Sends a video message to a phone number.

    bot_response must contain key: url, caption (optional). Same shape as
    send_audio_message.py -- Gupshup's msg API takes a "type" discriminator
    and a fetchable url, no separate video-specific fields.
    """
    logger.info(
        "Sending video message to phone number",
        extra={"phone_number": phone_number, "bot_response": bot_response},
    )
    destination = f"{phone_number}"
    url = "https://api.gupshup.io/wa/api/v1/msg"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    message_payload = {
        "type": "video",
        "url": bot_response.get("url"),
        "caption": bot_response.get("caption", ""),
    }

    data = {
        "source": GUPSHUP_SOURCE,
        "destination": destination,
        "message": json.dumps(message_payload),
        "src.name": gupshup_app_name,
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        logger.info(
            "Response",
            extra={
                "phone_number": phone_number,
                "response": response.json(),
            },
        )
        return response.json()
    except Exception as e:
        logger.error(
            "Error in sending video message",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise e
