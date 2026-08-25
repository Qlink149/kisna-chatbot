import json
import time

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_URL
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger


def _should_retry(status_code):
    if status_code is None:
        return True
    if status_code == 429:
        return True
    if status_code >= 500:
        return True
    return False


def send_quickreply(phone_number, bot_response):
    """Send quick reply to the user."""
    logger.info(
        "Sending postcall quick reply to phone number",
        extra={"phone_number": phone_number},
    )

    destination = f"{phone_number}"
    url = GUPSHUP_URL

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    data = {
        "message": json.dumps(
            {
                "type": "quick_reply",
                "content": {
                    "type": "text",
                    "text": bot_response["text"],
                    "caption": bot_response["caption"],
                },
                "options": bot_response["options"],
                "msgid": bot_response["msgid"],
            }
        ),
        "source": GUPSHUP_SOURCE,
        "destination": destination,
        "src.name": gupshup_app_name,
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Response",
            extra={
                "phone_number": phone_number,
                "response": result,
            },
        )
        return result
    except Exception as e:
        logger.error(
            "Error while sending postcall quick reply",
            extra={"phone_number": phone_number, "error": e},
        )
        raise e


def send_quickreply_with_retry(phone_number, bot_response, max_retries: int = 3):
    """
    Send a quick-reply message with exponential backoff on transient failures.

    Retries on network errors, timeouts, 5xx, and 429. Does not retry other 4xx.
    Mirrors send_text_message_with_retry so the confirm/quick-reply prompts get
    the same resilience as plain text messages.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return send_quickreply(phone_number, bot_response)
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code
            if not _should_retry(status):
                logger.error(
                    "Non-retryable HTTP error sending quick reply",
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
                "Retrying quick reply send",
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
                "Failed to send quick reply after retries",
                extra={
                    "phone_number": phone_number,
                    "max_retries": max_retries,
                    "error": str(last_error),
                },
            )

    if last_error:
        raise last_error
    raise RuntimeError("send_quickreply_with_retry failed without exception")
