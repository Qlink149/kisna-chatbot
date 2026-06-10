import json

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_URL
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.media.send_image_message import (
    send_image_message,
)


def _build_interactive_payload(
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str,
) -> dict:
    return {
        "type": "interactive",
        "interactive": {
            "type": "cta_url",
            "header": {
                "type": "image",
                "image": {"link": image_url},
            },
            "body": {"text": caption},
            "action": {
                "name": "cta_url",
                "parameters": {
                    "display_text": button_title,
                    "url": product_url,
                },
            },
        },
    }


def send_image_with_buy_button(
    phone_number: str,
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str = "Buy on KISNA",
) -> dict:
    """Send a WhatsApp image with an inline Buy CTA button."""
    if not image_url or not str(image_url).strip():
        logger.error(
            "Skipping image_with_cta send — empty image URL",
            extra={"phone_number": phone_number},
        )
        return {"status": "submitted"}

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }
    message_payload = _build_interactive_payload(
        image_url, caption, product_url, button_title
    )
    data = {
        "message": json.dumps(message_payload),
        "source": GUPSHUP_SOURCE,
        "destination": f"{phone_number}",
        "src.name": gupshup_app_name,
    }

    try:
        response = httpx.post(GUPSHUP_URL, headers=headers, data=data)
        if response.status_code >= 400:
            logger.warning(
                "Gupshup image_with_cta send failed — falling back to plain image",
                extra={
                    "phone_number": phone_number,
                    "status_code": response.status_code,
                    "response_body": response.text,
                },
            )
            return send_image_message(
                phone_number=phone_number,
                bot_response={"url": image_url, "caption": caption},
            )
        result = response.json()
        logger.info(
            "Sent image_with_cta",
            extra={"phone_number": phone_number, "response": result},
        )
        return result
    except Exception as exc:
        logger.warning(
            "image_with_cta send error — falling back to plain image",
            extra={"phone_number": phone_number, "error": str(exc)},
        )
        return send_image_message(
            phone_number=phone_number,
            bot_response={"url": image_url, "caption": caption},
        )


def send_image_with_cta(phone_number: str, bot_response: dict) -> dict:
    """ResponseManager entry point for image_with_cta bot_response items."""
    return send_image_with_buy_button(
        phone_number=phone_number,
        image_url=bot_response["url"],
        caption=bot_response.get("caption", ""),
        product_url=bot_response["cta_url"],
        button_title=bot_response.get("cta_title", "Buy on KISNA"),
    )
