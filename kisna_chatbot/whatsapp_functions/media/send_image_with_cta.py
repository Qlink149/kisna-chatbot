"""Send product cards to WhatsApp.

Gupshup's interactive ``cta_url`` with an image *header* is unreliable —
API often returns HTTP 200 with ``status: error``, so cards vanish on WhatsApp
while the dashboard (which stores ``bot_response`` before send) still shows them.

We always send the proven split path: plain image + separate Buy CTA.
"""

import time

from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.cta.send_cta import send_cta_url
from kisna_chatbot.whatsapp_functions.media.send_image_message import (
    send_image_message,
)


def _gupshup_accepted(result: dict | None) -> bool:
    if not isinstance(result, dict):
        return False
    status = str(result.get("status") or "").strip().lower()
    if status in ("error", "failed", "failure"):
        return False
    if status in ("submitted", "success", "ok", "enqueued", "processing"):
        return True
    return bool(result.get("messageId") or result.get("id"))


def _build_interactive_payload(
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str,
) -> dict:
    """Kept for unit tests / payload shape docs. Not used for live sends."""
    return {
        "type": "cta_url",
        "body": (caption or "").strip(),
        "display_text": button_title,
        "url": product_url,
        "header": {
            "type": "image",
            "image": {"link": image_url},
        },
        "footer": "KISNA Diamond & Gold",
    }


def send_image_with_buy_button(
    phone_number: str,
    image_url: str,
    caption: str,
    product_url: str,
    button_title: str = "Buy on KISNA",
) -> dict:
    """Send product image, then a Buy CTA button (two WhatsApp messages)."""
    first_line = (caption or "").split("\n")[0].strip("* \n") or "View this piece"
    button = (button_title or "Buy on KISNA")[:20]

    image_result: dict | None = None
    if image_url and str(image_url).strip():
        image_result = send_image_message(
            phone_number=phone_number,
            bot_response={"url": image_url, "caption": caption},
        )
        if not _gupshup_accepted(
            image_result if isinstance(image_result, dict) else None
        ):
            logger.warning(
                "Product image send not accepted — still sending Buy CTA",
                extra={
                    "phone_number": phone_number,
                    "image_url": str(image_url)[:180],
                    "response": image_result,
                },
            )
        time.sleep(0.4)
    else:
        logger.error(
            "Product card missing image URL — sending Buy CTA only",
            extra={"phone_number": phone_number},
        )

    cta_text = (
        f"{first_line}\nTap below to buy on kisna.com"
        if image_url
        else f"{first_line}\n(Image unavailable — open on kisna.com)"
    )
    if caption and image_url and not _gupshup_accepted(
        image_result if isinstance(image_result, dict) else None
    ):
        # Image failed — put fuller caption into the CTA body so user still
        # sees price/material even without the photo.
        body = (caption or "").strip()
        if len(body) > 900:
            body = body[:899].rstrip() + "…"
        cta_text = f"{body}\n\nOpen on kisna.com:"

    if not product_url:
        return image_result if isinstance(image_result, dict) else {
            "status": "error",
            "message": "missing_product_url",
        }

    cta_result = send_cta_url(
        phone_number,
        {
            "text": cta_text,
            "display_text": button,
            "url": product_url,
        },
    )
    if _gupshup_accepted(cta_result):
        return cta_result
    if _gupshup_accepted(image_result if isinstance(image_result, dict) else None):
        return image_result  # type: ignore[return-value]
    return cta_result if isinstance(cta_result, dict) else {"status": "error"}


def send_image_with_cta(phone_number: str, bot_response: dict) -> dict:
    """ResponseManager entry point for image_with_cta bot_response items."""
    return send_image_with_buy_button(
        phone_number=phone_number,
        image_url=bot_response.get("url") or "",
        caption=bot_response.get("caption", ""),
        product_url=bot_response.get("cta_url") or "",
        button_title=bot_response.get("cta_title", "Buy on KISNA"),
    )
