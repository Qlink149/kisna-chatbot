"""send_quickreply now checks the response status and retries transient failures,
matching send_text_message_with_retry. Before this it neither raised on a 5xx
JSON error body (treated as success) nor retried a genuine network blip -- the
confirm/quick-reply prompt at the center of the "stuck after tapping a button"
bug had none of the resilience plain text messages already had.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

import httpx  # noqa: E402

from kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply import (  # noqa: E402
    send_quickreply,
    send_quickreply_with_retry,
)

_BODY = {
    "text": "Does this sound correct?",
    "caption": "",
    "options": [{"title": "Yes, show me"}, {"title": "No, change it"}],
    "msgid": "confirm$search",
}


def _response(status_code, json_body=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {"status": "submitted"}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


class TestSendQuickreplyStatusCheck(unittest.TestCase):
    """The prerequisite bug: an error body used to look like success."""

    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_2xx_returns_body(self, post_mock):
        post_mock.return_value = _response(200, {"status": "submitted"})
        result = send_quickreply("919812345678", _BODY)
        self.assertEqual(result, {"status": "submitted"})

    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_5xx_with_json_body_now_raises_instead_of_looking_like_success(
        self, post_mock
    ):
        post_mock.return_value = _response(500, {"error": "internal"})
        with self.assertRaises(httpx.HTTPStatusError):
            send_quickreply("919812345678", _BODY)


class TestSendQuickreplyWithRetry(unittest.TestCase):
    """Patches the module's own `time` name, not `time.sleep`.

    `time.sleep` is an attribute of the shared time module: patching it there
    catches sleeps from every other thread in the process too (the
    ResponseManager worker a webhook test leaves running sleeps 0.5s in its
    outbound rate limiter), which made these call-count assertions flaky.
    """

    @patch("kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.time")
    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_succeeds_first_try_no_sleep(self, post_mock, time_mock):
        post_mock.return_value = _response(200)
        result = send_quickreply_with_retry("919812345678", _BODY)
        self.assertEqual(result, {"status": "submitted"})
        time_mock.sleep.assert_not_called()

    @patch("kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.time")
    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_retries_on_500_then_succeeds(self, post_mock, time_mock):
        post_mock.side_effect = [_response(500), _response(200)]
        result = send_quickreply_with_retry("919812345678", _BODY, max_retries=3)
        self.assertEqual(result, {"status": "submitted"})
        self.assertEqual(post_mock.call_count, 2)
        time_mock.sleep.assert_called_once_with(1)  # 2**0

    @patch("kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.time")
    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_retries_on_network_error(self, post_mock, time_mock):
        post_mock.side_effect = [
            httpx.ConnectTimeout("timed out"),
            _response(200),
        ]
        result = send_quickreply_with_retry("919812345678", _BODY, max_retries=3)
        self.assertEqual(result, {"status": "submitted"})
        self.assertEqual(post_mock.call_count, 2)

    @patch("kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.time")
    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_does_not_retry_a_client_error(self, post_mock, time_mock):
        post_mock.return_value = _response(400, {"error": "bad msgid"})
        with self.assertRaises(httpx.HTTPStatusError):
            send_quickreply_with_retry("919812345678", _BODY, max_retries=3)
        post_mock.assert_called_once()
        time_mock.sleep.assert_not_called()

    @patch("kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.time")
    @patch(
        "kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply.httpx.post"
    )
    def test_exhausts_retries_and_raises_last_error(self, post_mock, time_mock):
        post_mock.side_effect = [_response(500), _response(500), _response(500)]
        with self.assertRaises(httpx.HTTPStatusError):
            send_quickreply_with_retry("919812345678", _BODY, max_retries=3)
        self.assertEqual(post_mock.call_count, 3)
        self.assertEqual(time_mock.sleep.call_count, 2)  # not slept after the last attempt


if __name__ == "__main__":
    unittest.main()
