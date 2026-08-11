"""Send product cards to WhatsApp.

Preferred shape is ONE message: image header + caption + inline Buy button.
Gupshup can return HTTP 200 with ``status: error`` for that interactive card,
so a rejection falls back to the split path (plain image, then Buy CTA) rather
than letting the product vanish on WhatsApp.
"""

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


def _gupshup_accepted(result: dict | None) -> bool:
    """True when Gupshup acknowledges the message (HTTP 200 can still be error)."""
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    if status in ("error", "failed", "failure"):
        return False
    if status in ("submitted", "success", "ok", "enqueued", "processing"):
        return True
    return bool(result.get("messageId") or result.get("id"))


def _clamp_body(caption: str) -> str:
    body = (caption or "").strip()
    if len(body) > _MAX_CTA_BODY_CHARS:
        body = body[: _MAX_CTA_BODY_CHARS - 1].rstrip() + "…"
    return body


def _build_interactive_payload(
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str,
) -> dict:
    return {
        "type": "cta_url",
        "body": _clamp_body(caption),
        "display_text": button_title,
        "url": product_url,
        "header": {
            "type": "image",
            "image": {"link": image_url},
        },
        "footer": "KISNA Diamond & Gold",
    }


def _send_image_then_buy_cta(
    phone_number: str,
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str,
) -> dict:
    """Fallback: plain image, then a Buy CTA without an image header."""
    button = (button_title or "Buy on KISNA")[:20]
    first_line = (caption or "").split("\n")[0].strip("* \n") or "View this piece"

    image_result: dict | None = None
    if image_url and str(image_url).strip():
        image_result = send_image_message(
            phone_number=phone_number,
            bot_response={"url": image_url, "caption": caption},
        )
        if not _gupshup_accepted(image_result):
            logger.warning(
                "Product image send not accepted — still sending Buy CTA",
                extra={
                    "phone_number": phone_number,
                    "image_url": str(image_url)[:180],
                    "response": image_result,
                },
            )
        time.sleep(0.4)

    if _gupshup_accepted(image_result):
        # Photo + details already delivered; the CTA only needs the button.
        cta_text = f"{first_line}\nTap below to buy on kisna.com"
    else:
        # No photo reached the user — carry price/material in the CTA body.
        cta_text = f"{_clamp_body(caption) or first_line}\n\nOpen on kisna.com:"

    if not product_url:
        return image_result or {"status": "error", "message": "missing_product_url"}

    cta_result = send_cta_url(
        phone_number,
        {"text": cta_text, "display_text": button, "url": product_url},
    )
    if _gupshup_accepted(cta_result):
        return cta_result
    if _gupshup_accepted(image_result):
        return image_result  # type: ignore[return-value]
    return cta_result if isinstance(cta_result, dict) else {"status": "error"}


def send_image_with_buy_button(
    phone_number: str,
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str = "Buy on KISNA",
) -> dict:
    """Send one product card: image + caption + inline Buy button."""
    button = (button_title or "Buy on KISNA")[:20]

    if not image_url or not str(image_url).strip():
        logger.error(
            "Product card missing image URL — sending Buy CTA only",
            extra={"phone_number": phone_number},
        )
        if not product_url:
            return {"status": "error", "message": "empty_image_url"}
        first_line = (caption or "").split("\n")[0].strip("* \n") or "View this piece"
        return send_cta_url(
            phone_number,
            {
                "text": f"{first_line}\n(Image unavailable — open on kisna.com)",
                "display_text": button,
                "url": product_url,
            },
        )

    if not product_url:
        return send_image_message(
            phone_number=phone_number,
            bot_response={"url": image_url, "caption": caption},
        )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }
    data = {
        "message": json.dumps(
            _build_interactive_payload(image_url, caption, product_url, button)
        ),
        "source": GUPSHUP_SOURCE,
        "destination": f"{phone_number}",
        "src.name": gupshup_app_name,
    }

    try:
        response = httpx.post(GUPSHUP_URL, headers=headers, data=data, timeout=30.0)
        try:
            result: dict = response.json()
        except Exception:
            result = {
                "status": "error",
                "status_code": response.status_code,
                "response_body": response.text[:500],
            }

        if response.status_code < 400 and _gupshup_accepted(result):
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
            },
        )
    except Exception as exc:
        logger.warning(
            "image_with_cta send error — falling back to image + Buy CTA",
            extra={"phone_number": phone_number, "error": str(exc)},
        )

    return _send_image_then_buy_cta(
        phone_number, image_url, caption, product_url, button
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
