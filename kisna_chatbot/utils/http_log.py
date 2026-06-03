"""Structured logging helpers for outbound HTTP calls."""

import time
from typing import Any

from kisna_chatbot.utils.logger_config import (
    log_event,
    log_http_bodies_enabled,
    sanitize_for_log,
    truncate_for_log,
)


def log_http_request(
    service: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> float:
    """Log outbound HTTP request; returns perf_counter start time."""
    extra: dict[str, Any] = {
        "service": service,
        "method": method,
        "url": url,
    }
    if params is not None:
        extra["params"] = sanitize_for_log(params)
    log_event("http_outbound_request", f"{method} {url}", **extra)
    return time.perf_counter()


def log_http_response(
    service: str,
    method: str,
    url: str,
    *,
    start: float,
    status_code: int | None = None,
    body_preview: Any = None,
    error: str | None = None,
) -> None:
    """Log outbound HTTP response or error."""
    duration_ms = int((time.perf_counter() - start) * 1000)
    extra: dict[str, Any] = {
        "service": service,
        "method": method,
        "url": url,
        "duration_ms": duration_ms,
        "status_code": status_code,
    }
    if error:
        extra["error"] = error
        log_event(
            "http_outbound_error",
            f"{method} {url} failed",
            level="error",
            **extra,
        )
        return

    if body_preview is not None and log_http_bodies_enabled():
        extra["body_preview"] = sanitize_for_log(body_preview)
    elif body_preview is not None:
        if isinstance(body_preview, (dict, list)):
            if isinstance(body_preview, list):
                extra["body_items"] = len(body_preview)
            else:
                extra["body_keys"] = list(body_preview.keys())[:20]
        else:
            extra["body_preview"] = truncate_for_log(str(body_preview), max_bytes=500)

    log_event(
        "http_outbound_response",
        f"{method} {url} {status_code or 'ok'}",
        **extra,
    )
