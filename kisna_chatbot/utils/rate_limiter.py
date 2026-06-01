"""
Per-recipient outbound rate limiting for Gupshup WhatsApp sends.

Uses in-memory timestamps; suitable for single-worker deployments.
For multiple uvicorn workers, use a shared store (e.g. Redis).
"""

import time

from kisna_chatbot.utils.logger_config import logger


class OutboundRateLimiter:
    """Enforce minimum interval between outbound messages per phone number."""

    def __init__(self, min_interval: float = 0.5) -> None:
        self._min_interval = min_interval
        self._last_sent: dict[str, float] = {}

    def wait_if_needed(self, phone_number: str) -> bool:
        """
        Sleep until min_interval has elapsed since the last send to this number.

        Returns:
            True if throttling was applied, False otherwise.
        """
        now = time.monotonic()
        last = self._last_sent.get(phone_number)
        if last is not None:
            elapsed = now - last
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                logger.warning(
                    "Outbound rate limit: delaying send",
                    extra={
                        "phone_number": phone_number,
                        "wait_seconds": round(wait_time, 3),
                    },
                )
                time.sleep(wait_time)
                self._last_sent[phone_number] = time.monotonic()
                return True

        self._last_sent[phone_number] = time.monotonic()
        return False


outbound_rate_limiter = OutboundRateLimiter(min_interval=0.5)
