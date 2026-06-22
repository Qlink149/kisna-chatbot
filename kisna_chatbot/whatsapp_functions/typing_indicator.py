import asyncio
import httpx

from kisna_chatbot.utils.env_load import (
    gupshup_app_id,
    gupshup_token,
)
from kisna_chatbot.utils.logger_config import logger

PARTNER_BASE_URL = "https://partner.gupshup.io"


async def send_typing_indicator(message_id: str) -> None:
    """Mark an inbound WhatsApp message as read and show typing via Gupshup.

    This must use the Partner API with the inbound message id. Sending a
    notification payload through the normal message API appears as visible text.
    """
    if not message_id or not gupshup_app_id or not gupshup_token:
        logger.info(
            "Skipping WhatsApp typing indicator; missing message id or Gupshup partner config",
            extra={"message_id_present": bool(message_id)},
        )
        return

    url = f"{PARTNER_BASE_URL}/partner/app/{gupshup_app_id}/v1/event"
    headers = {
        "Authorization": gupshup_token,
        "token": gupshup_token,
        "Content-Type": "application/json",
    }
    payload = {
        "type": "message-event",
        "message": {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        },
    }

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(url, headers=headers, json=payload)
        if response.status_code >= 400:
            logger.warning(
                "WhatsApp typing indicator failed",
                extra={
                    "status_code": response.status_code,
                    "response": response.text[:500],
                },
            )
            return
        logger.info("WhatsApp typing indicator sent", extra={"status_code": response.status_code})
    except Exception as e:
        logger.warning("WhatsApp typing indicator failed", extra={"error": str(e)})


async def typing_indicator_loop(message_id: str, stop_event: asyncio.Event) -> None:
    """Send typing indicator repeatedly every 20s until stopped."""
    while not stop_event.is_set():
        await send_typing_indicator(message_id)
        try:
            # WhatsApp hides typing indicator after ~25s, so we loop every 20s
            await asyncio.wait_for(stop_event.wait(), timeout=20.0)
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error("Typing indicator loop encountered error", extra={"error": str(e)})
            break
