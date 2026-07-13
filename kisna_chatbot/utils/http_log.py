"""Structured logging helpers for outbound HTTP calls."""

import time
from typing import Any
from urllib.parse import urlsplit


def format_params_for_log(params: dict[str, Any] | None) -> str:
    """Compact query-param string for log messages (no URL)."""
    if not params:
        return "(none)"
    parts: list[str] = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        key_l = str(key).lower()
        if any(s in key_l for s in ("key", "token", "secret", "password", "auth")):
            parts.append(f"{key}=***")
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "(none)"


def path_from_url(url: str) -> str:
    """Return path (+ query if present) without scheme/host."""
    try:
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            return f"{path}?{parts.query}"
        return path
    except Exception:
        return url


def log_http_request(
    service: str,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    path: str | None = None,
) -> float:
    """Log outbound HTTP request; returns perf_counter start time.

    Message shows path + query params only (no base URL).
    """
    from kisna_chatbot.utils.logger_config import log_event, sanitize_for_log

    api_path = path or path_from_url(url)
    param_str = format_params_for_log(params)
    extra: dict[str, Any] = {
        "service": service,
        "method": method,
        "path": api_path,
        "query_params": sanitize_for_log(params) if params is not None else {},
    }
    log_event(
        "http_outbound_request",
        f"{method} {api_path} | {param_str}",
        **extra,
    )
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
    path: str | None = None,
    params: dict[str, Any] | None = None,
    result_count: int | None = None,
) -> None:
    """Log outbound HTTP response or error (path + params, no base URL)."""
    from kisna_chatbot.utils.logger_config import (
        log_event,
        log_http_bodies_enabled,
        sanitize_for_log,
        truncate_for_log,
    )

    duration_ms = int((time.perf_counter() - start) * 1000)
    api_path = path or path_from_url(url)
    param_str = format_params_for_log(params)
    extra: dict[str, Any] = {
        "service": service,
        "method": method,
        "path": api_path,
        "duration_ms": duration_ms,
        "status_code": status_code,
        "query_params": sanitize_for_log(params) if params is not None else {},
    }
    if result_count is not None:
        extra["result_count"] = result_count

    if error:
        extra["error"] = error
        log_event(
            "http_outbound_error",
            f"{method} {api_path} failed ({error}) | {param_str}",
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

    count_bit = f", {result_count} items" if result_count is not None else ""
    log_event(
        "http_outbound_response",
        f"{method} {api_path} → {status_code or 'ok'} ({duration_ms}ms{count_bit}) | {param_str}",
        **extra,
    )
