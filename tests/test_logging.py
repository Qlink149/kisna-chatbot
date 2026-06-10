"""Tests for structured logging infrastructure."""

import io
import json
import logging
import os

import pytest
from fastapi.testclient import TestClient

from kisna_chatbot.main import app
from kisna_chatbot.utils.logger_config import (
    JsonFormatter,
    RequestContextFilter,
    _MaxLevelFilter,
    sanitize_for_log,
    set_request_context,
)


class TestSanitizeForLog:
    def test_redacts_sensitive_keys(self):
        payload = {
            "authorization": "Bearer secret",
            "apikey": "key123",
            "nested": {"token": "tok", "safe": "ok"},
        }
        result = sanitize_for_log(payload)
        assert result["authorization"] == "***REDACTED***"
        assert result["apikey"] == "***REDACTED***"
        assert result["nested"]["token"] == "***REDACTED***"
        assert result["nested"]["safe"] == "ok"

    def test_truncates_long_strings(self):
        long_text = "x" * 10000
        result = sanitize_for_log(long_text)
        assert isinstance(result, str)
        assert len(result) < 10000
        assert "chars>" in result


class TestJsonFormatter:
    def test_single_line_on_vercel(self, monkeypatch):
        monkeypatch.setenv("VERCEL", "1")
        monkeypatch.delenv("LOG_PRETTY", raising=False)
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.request_id = "req-123"
        record.event = "test_event"
        output = formatter.format(record)
        assert "\n**************" not in output
        assert output.count("\n") == 0
        parsed = json.loads(output)
        assert parsed["request_id"] == "req-123"
        assert parsed["event"] == "test_event"

    def test_includes_context_from_record(self):
        from kisna_chatbot.utils.logger_config import (
            RequestContextFilter,
            clear_request_context,
        )

        set_request_context(request_id="ctx-abc", phone_number="919999999999")
        try:
            formatter = JsonFormatter()
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="ctx test",
                args=(),
                exc_info=None,
            )
            RequestContextFilter().filter(record)
            output = formatter.format(record)
            parsed = json.loads(output.split("\n")[0] if "\n" in output else output)
            assert parsed.get("request_id") == "ctx-abc"
            assert parsed.get("phone_number") == "919999999999"
        finally:
            clear_request_context()


def _build_routed_test_logger(stdout: io.StringIO, stderr: io.StringIO) -> logging.Logger:
    """Mirror production stdout/stderr handler routing on a test logger."""
    test_logger = logging.getLogger("kisna_chatbot_stream_routing_test")
    test_logger.handlers.clear()
    test_logger.setLevel(logging.DEBUG)
    test_logger.propagate = False

    formatter = JsonFormatter()
    context_filter = RequestContextFilter()

    stdout_handler = logging.StreamHandler(stdout)
    stdout_handler.setLevel(logging.DEBUG)
    stdout_handler.addFilter(_MaxLevelFilter(logging.WARNING))
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(context_filter)
    test_logger.addHandler(stdout_handler)

    stderr_handler = logging.StreamHandler(stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.setFormatter(formatter)
    stderr_handler.addFilter(context_filter)
    test_logger.addHandler(stderr_handler)

    return test_logger


class TestStreamRouting:
    def test_info_logs_to_stdout_not_stderr(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        test_logger = _build_routed_test_logger(stdout, stderr)

        test_logger.info("routing info test")

        assert "routing info test" in stdout.getvalue()
        assert stderr.getvalue() == ""
        parsed = json.loads(stdout.getvalue().strip())
        assert parsed["level"] == "INFO"

    def test_error_logs_to_stderr_not_stdout(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        test_logger = _build_routed_test_logger(stdout, stderr)

        test_logger.error("routing error test")

        assert stdout.getvalue() == ""
        assert "routing error test" in stderr.getvalue()
        parsed = json.loads(stderr.getvalue().strip())
        assert parsed["level"] == "ERROR"


class _LogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def log_collector():
    from kisna_chatbot.utils.logger_config import logger

    collector = _LogCollector()
    collector.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    yield collector
    logger.removeHandler(collector)


class TestLoggingMiddleware:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_ping_emits_http_request_response_with_request_id(
        self, client, log_collector
    ):
        response = client.get("/ping")

        assert response.status_code == 200
        assert "X-Request-Id" in response.headers
        request_id = response.headers["X-Request-Id"]
        assert request_id

        events = [getattr(r, "event", None) for r in log_collector.records]
        assert "http_request" in events
        assert "http_response" in events

        http_req = next(
            r for r in log_collector.records if getattr(r, "event", None) == "http_request"
        )
        assert http_req.request_id == request_id

    def test_webhook_stub_logs_request_id(self, client, log_collector):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": "123"},
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.unique-logging-test",
                                        "type": "text",
                                        "text": {"body": "hi"},
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }
        response = client.post("/gupshup/message/kisna", json=payload)

        assert response.status_code == 200
        request_id = response.headers.get("X-Request-Id")
        assert request_id

        events = [getattr(r, "event", None) for r in log_collector.records]
        assert "http_request" in events
        assert "http_response" in events

        http_req = next(
            r for r in log_collector.records if getattr(r, "event", None) == "http_request"
        )
        assert http_req.request_id == request_id
