import json
import time

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_URL
from kisna_chatbot.utils.env_load import (
    gupshup_api_key,
    gupshup_app_name,
)
from kisna_chatbot.utils.logger_config import logger


def _should_retry(status_code):
    if status_code is None:
        return True
    if status_code == 429:
        return True
    if status_code >= 500:
        return True
    return False


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
        response.raise_for_status()
        result = response.json()
        logger.info(
            "Response from Gupshup API for sending list",
            extra={"phone_number": phone_number, "response": result},
        )
        return result
    except Exception as e:
        logger.error(
            "Error while sending list",
            extra={"phone_number": phone_number, "error": e},
        )
        raise e


def send_list_with_retry(phone_number, bot_response, max_retries: int = 3):
    """
    Send a list message with exponential backoff on transient failures.

    Retries on network errors, timeouts, 5xx, and 429. Does not retry other 4xx.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries):
        try:
            return send_list(phone_number, bot_response)
        except httpx.HTTPStatusError as e:
            last_error = e
            status = e.response.status_code
            if not _should_retry(status):
                logger.error(
                    "Non-retryable HTTP error sending list",
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
                "Retrying list send",
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
                "Failed to send list after retries",
                extra={
                    "phone_number": phone_number,
                    "max_retries": max_retries,
                    "error": str(last_error),
                },
            )

    if last_error:
        raise last_error
    raise RuntimeError("send_list_with_retry failed without exception")
