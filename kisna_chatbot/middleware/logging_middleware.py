"""HTTP request/response logging middleware for Vercel and local dev."""

import json
import time
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from kisna_chatbot.utils.logger_config import (
    log_event,
    log_http_bodies_enabled,
    sanitize_for_log,
    set_request_context,
    truncate_for_log,
)

_SAFE_HEADER_KEYS = frozenset(
    {
        "content-type",
        "user-agent",
        "x-request-id",
        "x-gupshup-signature",
        "x-hub-signature-256",
    }
)


def _request_id_from_headers(request: Request) -> str:
    incoming = (
        request.headers.get("x-request-id")
        or request.headers.get("X-Request-Id")
        or ""
    ).strip()
    return incoming or str(uuid.uuid4())


def _safe_headers(request: Request) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in _SAFE_HEADER_KEYS:
            out[key] = value
        elif lower in ("host", "content-length"):
            out[key] = value
    return out


def _parse_body_preview(body: bytes) -> Any:
    if not body:
        return None
    text = truncate_for_log(
        body.decode("utf-8", errors="replace"),
    )
    try:
        return sanitize_for_log(json.loads(text))
    except json.JSONDecodeError:
        return text


class LoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request and response with timing and request_id."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        request_id = _request_id_from_headers(request)
        request.state.request_id = request_id
        set_request_context(request_id=request_id)

        body_bytes = await request.body()
        query = dict(request.query_params) if request.query_params else None

        req_extra: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "client_host": request.client.host if request.client else None,
            "headers": _safe_headers(request),
        }
        if query:
            req_extra["query"] = sanitize_for_log(query)
        if log_http_bodies_enabled() and body_bytes:
            req_extra["body"] = _parse_body_preview(body_bytes)

        log_event(
            "http_request",
            f"{request.method} {request.url.path}",
            **req_extra,
        )

        async def receive() -> dict:
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        request = Request(request.scope, receive)
        request.state.request_id = request_id
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)

        resp_extra: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        }

        if request.url.path == "/gupshup/message/kisna":
            resp_extra["webhook_ack"] = response.status_code == 200

        log_event(
            "http_response",
            f"{request.method} {request.url.path} {response.status_code}",
            **resp_extra,
        )

        response.headers["X-Request-Id"] = request_id
        return response
