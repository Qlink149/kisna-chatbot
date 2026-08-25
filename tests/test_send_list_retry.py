"""Same fix, same reasoning as test_send_quickreply_retry.py: send_list now
checks the response status and retries transient failures instead of treating
a 5xx JSON body as success and never retrying a network blip.
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

from kisna_chatbot.whatsapp_functions.list.send_list import (  # noqa: E402
    send_list,
    send_list_with_retry,
)

_BODY = {
    "body": "Choose an option",
    "msgid": "list$menu",
    "globalButtons": [{"type": "text", "title": "Menu"}],
    "items": [{"title": "Section", "options": []}],
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


class TestSendListStatusCheck(unittest.TestCase):
    @patch("kisna_chatbot.whatsapp_functions.list.send_list.httpx.post")
    def test_2xx_returns_body(self, post_mock):
        post_mock.return_value = _response(200, {"status": "submitted"})
        result = send_list("919812345678", _BODY)
        self.assertEqual(result, {"status": "submitted"})

    @patch("kisna_chatbot.whatsapp_functions.list.send_list.httpx.post")
    def test_5xx_with_json_body_now_raises_instead_of_looking_like_success(
        self, post_mock
    ):
        post_mock.return_value = _response(500, {"error": "internal"})
        with self.assertRaises(httpx.HTTPStatusError):
            send_list("919812345678", _BODY)


class TestSendListWithRetry(unittest.TestCase):
    @patch("kisna_chatbot.whatsapp_functions.list.send_list.time.sleep")
    @patch("kisna_chatbot.whatsapp_functions.list.send_list.httpx.post")
    def test_retries_on_500_then_succeeds(self, post_mock, sleep_mock):
        post_mock.side_effect = [_response(500), _response(200)]
        result = send_list_with_retry("919812345678", _BODY, max_retries=3)
        self.assertEqual(result, {"status": "submitted"})
        self.assertEqual(post_mock.call_count, 2)

    @patch("kisna_chatbot.whatsapp_functions.list.send_list.time.sleep")
    @patch("kisna_chatbot.whatsapp_functions.list.send_list.httpx.post")
    def test_does_not_retry_a_client_error(self, post_mock, sleep_mock):
        post_mock.return_value = _response(400, {"error": "bad payload"})
        with self.assertRaises(httpx.HTTPStatusError):
            send_list_with_retry("919812345678", _BODY, max_retries=3)
        post_mock.assert_called_once()

    @patch("kisna_chatbot.whatsapp_functions.list.send_list.time.sleep")
    @patch("kisna_chatbot.whatsapp_functions.list.send_list.httpx.post")
    def test_exhausts_retries_and_raises_last_error(self, post_mock, sleep_mock):
        post_mock.side_effect = [_response(500), _response(500), _response(500)]
        with self.assertRaises(httpx.HTTPStatusError):
            send_list_with_retry("919812345678", _BODY, max_retries=3)
        self.assertEqual(post_mock.call_count, 3)


if __name__ == "__main__":
    unittest.main()
