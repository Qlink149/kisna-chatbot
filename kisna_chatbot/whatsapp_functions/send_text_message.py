import json
import time

import httpx

from kisna_chatbot.config.gupshup import get_gupshup_source
from kisna_chatbot.constants import GUPSHUP_URL
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger


def _should_retry(status_code: int | None) -> bool:
    if status_code is None:
        return True
    if status_code == 429:
        return True
    if status_code >= 500:
        return True
    return False


def send_text_message(phone_number: str, bot_response: dict) -> dict:
    """
    Send a WhatsApp message via Gupshup WA API.

    Args:
        phone_number: Recipient WhatsApp number.
        bot_response: Message payload dict (e.g. {"type": "text", "text": "..."}).

    Returns:
        Parsed JSON response from Gupshup.

    Raises:
        Exception: On HTTP or network failure.
    """
    source = get_gupshup_source()
    logger.info(
        "Sending text message to phone number",
        extra={"phone_number": phone_number, "bot_response": bot_response},
    )

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    data = {
        "source": source,
        "destination": phone_number,
        "message": json.dumps(bot_response),
        "src.name": gupshup_app_name,
    }

    try:
        response = httpx.post(GUPSHUP_URL, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Text message sent",
            extra={"phone_number": phone_number, "response": result},
        )
        return result
    except Exception as e:
        logger.exception(
            "Error sending text message",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise


def send_text_message_with_retry(
    phone_number: str,
    bot_response: dict,
    max_retries: int = 3,
) -> dict:
    """
    Send text message with exponential backoff on transient failures.

    Retries on network errors, timeouts, 5xx, and 429. Does not retry other 4xx.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            result = send_text_message(phone_number, bot_response)
            logger.info(
                "Message sent",
                extra={"phone_number": phone_number, "attempt": attempt + 1},
            )
            return result
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code
            if not _should_retry(status):
                logger.error(
                    "Non-retryable HTTP error sending text message",
                    extra={
                        "phone_number": phone_number,
                        "status_code": status,
                        "attempt": attempt + 1,
                    },
                )
                raise
        except (httpx.HTTPError, httpx.TimeoutException, OSError) as e:
            last_error = e

        if attempt < max_retries - 1:
            wait_time = 2**attempt
            logger.warning(
                "Retrying text message send",
                extra={
                    "phone_number": phone_number,
                    "attempt": attempt + 1,
                    "max_retries": max_retries,
                    "wait_seconds": wait_time,
                },
            )
            time.sleep(wait_time)
        else:
            logger.error(
                "Failed to send text message after retries",
                extra={
                    "phone_number": phone_number,
                    "max_retries": max_retries,
                    "error": str(last_error),
                },
            )

    if last_error:
        raise last_error
    raise RuntimeError("send_text_message_with_retry failed without exception")
