import json

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.product_formatter import webp_jpg_fallback


def _response_json(response: httpx.Response) -> dict:
    try:
        return response.json()
    except Exception:
        return {"status": "error", "status_code": response.status_code}


def _post_image(phone_number: str, url: str, caption: str = "") -> httpx.Response | dict:
    if not url or not str(url).strip():
        logger.error(
            "Skipping image send — empty URL",
            extra={"phone_number": phone_number},
        )
        return {"status": "submitted"}

    destination = f"{phone_number}"
    api_url = "https://api.gupshup.io/wa/api/v1/msg"

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    message_payload = {
        "type": "image",
        "caption": caption,
        "originalUrl": url,
        "previewUrl": url,
    }

    data = {
        "source": GUPSHUP_SOURCE,
        "destination": destination,
        "message": json.dumps(message_payload),
        "src.name": gupshup_app_name,
    }

    response = httpx.post(api_url, headers=headers, data=data)
    if response.status_code >= 400:
        logger.error(
            "Gupshup image send failed",
            extra={
                "phone_number": phone_number,
                "status_code": response.status_code,
                "response_body": response.text,
                "url": url,
            },
        )
    else:
        logger.info(
            "Response",
            extra={"phone_number": phone_number, "response": response.json()},
        )
    return response


def _send_with_jpg_retry(
    phone_number: str,
    url: str,
    caption: str = "",
) -> dict:
    result = _post_image(phone_number, url, caption)
    if isinstance(result, dict):
        return result

    if result.status_code < 400:
        return _response_json(result)

    fallback_url = webp_jpg_fallback(url or "")
    if fallback_url and fallback_url != url:
        logger.warning(
            "Retrying image send with jpg fallback",
            extra={
                "phone_number": phone_number,
                "original_url": url,
                "fallback_url": fallback_url,
            },
        )
        retry = _post_image(phone_number, fallback_url, caption)
        if isinstance(retry, dict):
            return retry
        return _response_json(retry)

    return _response_json(result)


def send_image_message(phone_number: str, bot_response: dict):
    """Sends one or more image messages to a phone number.

    If bot_response contains 'urls' (list of {url, caption}), sends each in sequence
    with a 0.4s delay between them and returns the last response.
    Otherwise falls back to single-image mode using 'url' and 'caption' keys.
    """
    logger.info(
        "Sending image message to phone number",
        extra={"phone_number": phone_number, "bot_response": bot_response},
    )

    urls = bot_response.get("urls")
    if urls:
        result: dict = {"status": "submitted"}
        for i, item in enumerate(urls):
            try:
                item_url = item.get("url") if isinstance(item, dict) else None
                item_caption = item.get("caption", "") if isinstance(item, dict) else ""
                result = _send_with_jpg_retry(
                    phone_number=phone_number,
                    url=item_url or "",
                    caption=item_caption,
                )
            except Exception as e:
                logger.error(
                    "Error sending image",
                    extra={"phone_number": phone_number, "index": i, "error": str(e)},
                )
                raise e
        return result

    try:
        return _send_with_jpg_retry(
            phone_number=phone_number,
            url=bot_response.get("url"),
            caption=bot_response.get("caption", ""),
        )
    except Exception as e:
        logger.error(
            "Error in sending image message",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise e
