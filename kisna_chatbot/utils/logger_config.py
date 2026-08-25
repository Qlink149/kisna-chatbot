import json
import logging
import os
import re
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime
from threading import Lock
from typing import Any

from bson import ObjectId

from kisna_chatbot.constants import SKIP_FIELDS_LOGGER

# Request-scoped fields injected into every log record
_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_phone_number_var: ContextVar[str | None] = ContextVar("phone_number", default=None)
_client_id_var: ContextVar[str | None] = ContextVar("client_id", default=None)

_SENSITIVE_KEY_RE = re.compile(
    r"(authorization|apikey|api_key|token|password|secret|signature|credential)",
    re.IGNORECASE,
)

_REDACTED = "***REDACTED***"
_MAX_BODY_LOG_BYTES = 8192


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes", "on")


def log_http_bodies_enabled() -> bool:
    """Whether to log sanitized HTTP request/response bodies."""
    explicit = os.getenv("LOG_HTTP_BODIES", "").strip()
    if explicit:
        return _truthy_env("LOG_HTTP_BODIES")
    if _truthy_env("LOG_GUPSHUP_WEBHOOK_PAYLOAD"):
        return True
    if os.getenv("ENV_MODE", "dev").lower() != "prod":
        return True
    return False


def _resolve_log_level() -> int:
    level_name = os.getenv("LOG_LEVEL", "").strip().upper()
    if not level_name:
        level_name = "INFO" if os.getenv("VERCEL") else "DEBUG"
    return getattr(logging, level_name, logging.INFO)


def _use_pretty_json() -> bool:
    if os.getenv("VERCEL"):
        return False
    return _truthy_env("LOG_PRETTY")


def set_request_context(
    *,
    request_id: str | None = None,
    phone_number: str | None = None,
    client_id: str | None = None,
) -> None:
    """Set contextvars for the current async task / thread."""
    if request_id is not None:
        _request_id_var.set(request_id)
    if phone_number is not None:
        _phone_number_var.set(phone_number)
    if client_id is not None:
        _client_id_var.set(client_id)


def clear_request_context() -> None:
    """Reset request-scoped context (call at end of background tasks)."""
    _request_id_var.set(None)
    _phone_number_var.set(None)
    _client_id_var.set(None)


def sanitize_for_log(obj: Any, *, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys and cap large strings for logging."""
    if _depth > 12:
        return "<max depth>"

    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for key, value in obj.items():
            key_str = str(key)
            if _SENSITIVE_KEY_RE.search(key_str):
                out[key_str] = _REDACTED
            else:
                out[key_str] = sanitize_for_log(value, _depth=_depth + 1)
        return out

    if isinstance(obj, (list, tuple)):
        return [sanitize_for_log(item, _depth=_depth + 1) for item in obj]

    if isinstance(obj, (str, bytes)):
        text = obj.decode("utf-8", errors="replace") if isinstance(obj, bytes) else obj
        if len(text) > _MAX_BODY_LOG_BYTES:
            return text[:_MAX_BODY_LOG_BYTES] + f"...<{len(text)} chars>"
        return text

    if isinstance(obj, ObjectId):
        return str(obj)

    if isinstance(obj, datetime):
        return obj.isoformat()

    if hasattr(obj, "model") and hasattr(obj, "usage"):
        return {
            "model": getattr(obj, "model", None),
            "usage": getattr(obj, "usage", None),
        }

    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        return str(obj)

    return obj


def truncate_for_log(text: str, max_bytes: int = _MAX_BODY_LOG_BYTES) -> str:
    if len(text) <= max_bytes:
        return text
    return text[:max_bytes] + f"...<{len(text)} chars>"


class _MaxLevelFilter(logging.Filter):
    """Pass records at or below max_level (for stdout routing)."""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


class RequestContextFilter(logging.Filter):
    """Inject request_id, phone_number, client_id from contextvars into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        record.phone_number = _phone_number_var.get()
        record.client_id = _client_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    """JSON formatter — single-line on Vercel, pretty optional locally."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "logged_at": datetime.now().isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "function_name": record.funcName,
            "file_path": record.pathname,
            "line_number": record.lineno,
        }

        for ctx_key in ("request_id", "phone_number", "client_id"):
            ctx_val = getattr(record, ctx_key, None)
            if ctx_val is not None:
                log_data[ctx_key] = ctx_val

        extra_fields = {
            key: sanitize_for_log(value)
            for key, value in vars(record).items()
            if key not in SKIP_FIELDS_LOGGER
            and key not in ("request_id", "phone_number", "client_id")
        }
        log_data.update(extra_fields)

        def custom_serializer(obj: Any) -> str:
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.isoformat()
            if hasattr(obj, "__dict__"):
                return str(obj)
            if hasattr(obj, "model"):
                return json.dumps(
                    {
                        "model": getattr(obj, "model", None),
                        "usage": getattr(obj, "usage", None),
                    },
                    default=str,
                )
            return f"<Unserializable:{type(obj).__name__}>"

        if _use_pretty_json():
            return json.dumps(log_data, indent=2, default=custom_serializer) + "\n"

        return json.dumps(log_data, separators=(",", ":"), default=custom_serializer)


def log_event(event: str, message: str = "", level: str = "info", **fields: Any) -> None:
    """Structured log with a consistent event field."""
    log_fn = getattr(logger, level.lower(), logger.info)
    extra = {"event": event, **fields}
    if message:
        log_fn(message, extra=extra)
    else:
        log_fn(event, extra=extra)


# ── Per-turn log capture ──────────────────────────────────────────────────────
# The dashboard's "What happened" panel shows a curated handful of trace steps,
# but the app already emits ~430 structured log calls per turn carrying the real
# diagnostics (LLM model/tokens/latency, Clara HTTP params and counts, retries,
# tracebacks). This handler buffers those records per request so the panel can
# render them like a deployment log, with no changes at any call site.

_trace_logs_var: ContextVar[list | None] = ContextVar("trace_logs", default=None)

# Hard ceilings so one pathological turn cannot bloat a Mongo document.
_TRACE_LOG_MAX_ENTRIES = 400
_TRACE_LOG_HEAD = 80  # kept from the start when truncating
_TRACE_LOG_MSG_CHARS = 2000


class TraceLogBuffer(logging.Handler):
    """Buffer log records emitted during the current turn.

    Appends to a ContextVar list, so concurrent turns never mix. A no-op when
    capture has not been started for this context.
    """

    def emit(self, record: logging.LogRecord) -> None:
        buffer = _trace_logs_var.get()
        if buffer is None:
            return
        try:
            if len(buffer) >= _TRACE_LOG_MAX_ENTRIES:
                # Keep the head (how the turn started) and a sliding tail (how it
                # ended); the middle is the least informative part of a long turn.
                del buffer[_TRACE_LOG_HEAD]
            buffer.append(_record_to_entry(record))
        except Exception:  # never let logging break the request
            pass


def _record_to_entry(record: logging.LogRecord) -> dict:
    """Flatten a LogRecord the same way JsonFormatter does, minus serialisation."""
    entry: dict[str, Any] = {
        "level": record.levelname,
        "message": truncate_for_log(record.getMessage(), _TRACE_LOG_MSG_CHARS),
        "logger": record.name,
        "module": record.module,
        "func": record.funcName,
        "line": record.lineno,
        "created": record.created,
    }

    extra = {
        key: sanitize_for_log(value)
        for key, value in vars(record).items()
        if key not in SKIP_FIELDS_LOGGER
        and key not in ("request_id", "phone_number", "client_id", "taskName")
    }
    if extra:
        entry["extra"] = extra

    if record.exc_info:
        try:
            entry["exception"] = truncate_for_log(
                "".join(traceback.format_exception(*record.exc_info)), 4000
            )
        except Exception:
            pass

    return entry


def begin_trace_capture() -> None:
    """Start buffering log records for this turn."""
    _trace_logs_var.set([])


def get_trace_logs() -> list:
    """Records captured so far for this turn (empty when capture is off)."""
    return list(_trace_logs_var.get() or [])


def end_trace_capture() -> None:
    """Stop buffering and release the records."""
    _trace_logs_var.set(None)


class SingletonLogger:
    """A singleton logger to ensure only one instance is created."""

    _instance = None
    _lock = Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls, *args, **kwargs)
                cls._instance._initialize_logger()
            return cls._instance

    def _initialize_logger(self) -> None:
        log_file_path = "logs/app.log"
        if not os.getenv("VERCEL"):
            os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

        self.logger = logging.getLogger("kisna_chatbot")
        self.logger.setLevel(_resolve_log_level())
        self.logger.propagate = False

        if not self.logger.handlers:
            context_filter = RequestContextFilter()
            formatter = JsonFormatter()

            stdout_handler = logging.StreamHandler(sys.stdout)
            stdout_handler.setLevel(logging.DEBUG)
            stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))
            stdout_handler.setFormatter(formatter)
            stdout_handler.addFilter(context_filter)
            self.logger.addHandler(stdout_handler)

            stderr_handler = logging.StreamHandler(sys.stderr)
            stderr_handler.setLevel(logging.ERROR)
            stderr_handler.setFormatter(formatter)
            stderr_handler.addFilter(context_filter)
            self.logger.addHandler(stderr_handler)

            # Captures every record for the in-flight turn so the dashboard can
            # show a full log, not just the curated trace steps.
            trace_handler = TraceLogBuffer()
            trace_handler.setLevel(logging.DEBUG)
            trace_handler.addFilter(context_filter)
            self.logger.addHandler(trace_handler)

            if os.getenv("LOG_TO_FILE", "").lower() in ("1", "true", "yes"):
                file_handler = logging.FileHandler(filename=log_file_path, mode="a")
                file_handler.setLevel(logging.DEBUG)
                file_handler.setFormatter(formatter)
                file_handler.addFilter(context_filter)
                self.logger.addHandler(file_handler)


logger = SingletonLogger().logger
