import json
import time

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_URL
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.cta.send_cta import send_cta_url
from kisna_chatbot.whatsapp_functions.media.send_image_message import (
    send_image_message,
)

# WhatsApp interactive body limit is 1024; keep headroom for encoding.
_MAX_CTA_BODY_CHARS = 900


def _build_interactive_payload(
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str,
) -> dict:
    body = (caption or "").strip()
    if len(body) > _MAX_CTA_BODY_CHARS:
        body = body[: _MAX_CTA_BODY_CHARS - 1].rstrip() + "…"
    return {
        "type": "cta_url",
        "body": body,
        "display_text": button_title,
        "url": product_url,
        "header": {
            "type": "image",
            "image": {
                "link": image_url,
            },
        },
        "footer": "KISNA Diamond & Gold",
    }


def _gupshup_accepted(result: dict | None) -> bool:
    """True when Gupshup acknowledges the message (HTTP 200 can still be error)."""
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    if status in ("error", "failed", "failure"):
        return False
    # Submitted / enqueued / success / ok — or messageId present
    if status in ("submitted", "success", "ok", "enqueued", "processing"):
        return True
    if result.get("messageId") or result.get("id"):
        return True
    return False


def _send_image_then_buy_cta(
    phone_number: str,
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str,
) -> dict:
    """Reliable split send: plain image, then Buy CTA (no image header)."""
    image_result = send_image_message(
        phone_number=phone_number,
        bot_response={"url": image_url, "caption": caption},
    )
    time.sleep(0.35)
    # Short body — full details already in the image caption above.
    first_line = (caption or "").split("\n")[0].strip("* \n") or "View this piece"
    cta_result = send_cta_url(
        phone_number,
        {
            "text": f"{first_line}\nTap below to buy on kisna.com",
            "display_text": button_title[:20],
            "url": product_url,
        },
    )
    if _gupshup_accepted(cta_result):
        return cta_result
    if _gupshup_accepted(image_result if isinstance(image_result, dict) else None):
        return image_result if isinstance(image_result, dict) else {"status": "submitted"}
    return cta_result if isinstance(cta_result, dict) else {"status": "error"}


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
        # Still offer the Buy link so the product isn't invisible on WhatsApp.
        if product_url:
            first_line = (caption or "").split("\n")[0].strip("* \n") or "View this piece"
            return send_cta_url(
                phone_number,
                {
                    "text": f"{first_line}\n(Image unavailable — open on kisna.com)",
                    "display_text": button_title[:20],
                    "url": product_url,
                },
            )
        return {"status": "error", "message": "empty_image_url"}

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
        response = httpx.post(GUPSHUP_URL, headers=headers, data=data, timeout=30.0)
        result: dict = {}
        try:
            result = response.json()
        except Exception:
            result = {
                "status": "error",
                "status_code": response.status_code,
                "response_body": response.text[:500],
            }

        http_ok = response.status_code < 400
        if http_ok and _gupshup_accepted(result):
            logger.info(
                "Sent image_with_cta",
                extra={"phone_number": phone_number, "response": result},
            )
            return result

        logger.warning(
            "Gupshup image_with_cta rejected — falling back to image + Buy CTA",
            extra={
                "phone_number": phone_number,
                "status_code": response.status_code,
                "response": result,
                "response_body": response.text[:500] if not result else None,
            },
        )
        return _send_image_then_buy_cta(
            phone_number, image_url, caption, product_url, button_title
        )
    except Exception as exc:
        logger.warning(
            "image_with_cta send error — falling back to image + Buy CTA",
            extra={"phone_number": phone_number, "error": str(exc)},
        )
        return _send_image_then_buy_cta(
            phone_number, image_url, caption, product_url, button_title
        )


def send_image_with_cta(phone_number: str, bot_response: dict) -> dict:
    """ResponseManager entry point for image_with_cta bot_response items."""
    return send_image_with_buy_button(
        phone_number=phone_number,
        image_url=bot_response.get("url") or "",
        caption=bot_response.get("caption", ""),
        product_url=bot_response.get("cta_url") or "",
        button_title=bot_response.get("cta_title", "Buy on KISNA"),
    )
