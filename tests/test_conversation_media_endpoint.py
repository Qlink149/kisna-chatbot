"""/system/conversation/{phone}/send and /send-media -- auth, takeover/window
guards, and (for send-media) the mime/size checks + B2 dispatch.

This repo had no endpoint test for /system/conversation/* before this file;
`send_message` (text) is covered here too as the baseline the media endpoint
must match guard-for-guard.
"""

import io
import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_UTM_ENABLED", "false")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

from kisna_chatbot.main import app  # noqa: E402
from kisna_chatbot.routes.dependencies.system_dependencies import (  # noqa: E402
    verify_session_or_api_key,
)

_CONV = "kisna_chatbot.routes.system_sub_routes.conversation"


def _fake_auth():
    return {"username": "test-admin", "role": "super_admin"}


def _user(updated_at=None):
    return {
        "phone_number": "919999999999",
        "updated_at": updated_at if updated_at is not None else int(time.time()),
    }


class ConversationApiBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[verify_session_or_api_key] = _fake_auth
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(verify_session_or_api_key, None)


class SendMessageBaselineTests(ConversationApiBase):
    """The text endpoint's guards -- send-media must match these exactly."""

    @patch(f"{_CONV}.get_user_by_phone", return_value=None)
    def test_404_no_user(self, _mock):
        res = self.client.post("/system/conversation/919999999999/send", json={"message": "hi"})
        self.assertEqual(res.status_code, 404)

    @patch(f"{_CONV}.get_takeover_status", return_value=None)
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_400_no_takeover(self, _mock_user, _mock_takeover):
        res = self.client.post("/system/conversation/919999999999/send", json={"message": "hi"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("takeover", res.json()["detail"].lower())

    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user(updated_at=int(time.time()) - 90000))
    def test_400_window_expired(self, _mock_user, _mock_takeover):
        res = self.client.post("/system/conversation/919999999999/send", json={"message": "hi"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("24-hour", res.json()["detail"])

    @patch(f"{_CONV}.pubsub.publish")
    @patch(f"{_CONV}.save_agent_message", return_value=123)
    @patch(f"{_CONV}.send_text_message")
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_200_success(self, _mock_user, _mock_takeover, mock_send, mock_save, _mock_pub):
        res = self.client.post("/system/conversation/919999999999/send", json={"message": "hi"})
        self.assertEqual(res.status_code, 200)
        mock_send.assert_called_once()
        mock_save.assert_called_once()


class SendMediaTests(ConversationApiBase):
    def _post_file(self, content=b"fake-bytes", filename="ring.jpg", content_type="image/jpeg", caption=None):
        data = {"caption": caption} if caption is not None else {}
        return self.client.post(
            "/system/conversation/919999999999/send-media",
            files={"file": (filename, io.BytesIO(content), content_type)},
            data=data,
        )

    @patch(f"{_CONV}.get_user_by_phone", return_value=None)
    def test_404_no_user(self, _mock):
        res = self._post_file()
        self.assertEqual(res.status_code, 404)

    @patch(f"{_CONV}.get_takeover_status", return_value=None)
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_400_no_takeover(self, _mock_user, _mock_takeover):
        res = self._post_file()
        self.assertEqual(res.status_code, 400)
        self.assertIn("takeover", res.json()["detail"].lower())

    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user(updated_at=int(time.time()) - 90000))
    def test_400_window_expired(self, _mock_user, _mock_takeover):
        res = self._post_file()
        self.assertEqual(res.status_code, 400)
        self.assertIn("24-hour", res.json()["detail"])

    @patch(f"{_CONV}.media_store.is_configured", return_value=False)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_503_b2_not_configured(self, _mock_user, _mock_takeover, _mock_conf):
        res = self._post_file()
        self.assertEqual(res.status_code, 503)

    @patch(f"{_CONV}.media_store.is_configured", return_value=True)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_400_disallowed_mime(self, _mock_user, _mock_takeover, _mock_conf):
        res = self._post_file(content_type="application/x-msdownload", filename="virus.exe")
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported", res.json()["detail"])

    @patch(f"{_CONV}.media_store.max_bytes", return_value=10)
    @patch(f"{_CONV}.media_store.is_configured", return_value=True)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_400_oversized(self, _mock_user, _mock_takeover, _mock_conf, _mock_max):
        res = self._post_file(content=b"x" * 100)
        self.assertEqual(res.status_code, 400)
        self.assertIn("20 MB", res.json()["detail"])

    @patch(f"{_CONV}.pubsub.publish")
    @patch(f"{_CONV}.save_agent_message", return_value=123)
    @patch(f"{_CONV}.send_image_message", return_value={"status": "submitted"})
    @patch(f"{_CONV}.media_store.presign_get", return_value="https://b2.example/signed")
    @patch(f"{_CONV}.media_store.put_bytes", return_value=True)
    @patch(f"{_CONV}.media_store.is_configured", return_value=True)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_200_image_success(
        self, _mock_user, _mock_takeover, _mock_conf, mock_put, mock_presign, mock_send, mock_save, _mock_pub
    ):
        res = self._post_file(caption="in rose gold")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["media"]["kind"], "image")
        self.assertEqual(body["media"]["url"], "https://b2.example/signed")
        mock_put.assert_called_once()
        mock_send.assert_called_once()
        send_kwargs = mock_send.call_args[0][1]
        self.assertEqual(send_kwargs["url"], "https://b2.example/signed")
        self.assertEqual(send_kwargs["caption"], "in rose gold")
        mock_save.assert_called_once()
        self.assertEqual(mock_save.call_args.kwargs["media"]["kind"], "image")

    @patch(f"{_CONV}.pubsub.publish")
    @patch(f"{_CONV}.save_agent_message", return_value=123)
    @patch(f"{_CONV}.send_file_message", return_value={"status": "submitted"})
    @patch(f"{_CONV}.media_store.presign_get", return_value="https://b2.example/signed")
    @patch(f"{_CONV}.media_store.put_bytes", return_value=True)
    @patch(f"{_CONV}.media_store.is_configured", return_value=True)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_200_document_success_uses_filename(
        self, _mock_user, _mock_takeover, _mock_conf, mock_put, mock_presign, mock_send, mock_save, _mock_pub
    ):
        res = self._post_file(content=b"%PDF-1.4", filename="quote.pdf", content_type="application/pdf")
        self.assertEqual(res.status_code, 200)
        send_kwargs = mock_send.call_args[0][1]
        self.assertEqual(send_kwargs["filename"], "quote.pdf")
        self.assertEqual(mock_save.call_args[0][1], "[Document] quote.pdf")

    @patch(f"{_CONV}.pubsub.publish")
    @patch(f"{_CONV}.save_agent_message", return_value=123)
    @patch(f"{_CONV}.send_image_message", return_value={"status": "submitted"})
    @patch(f"{_CONV}.media_store.presign_get", return_value=None)
    @patch(f"{_CONV}.media_store.put_bytes", return_value=True)
    @patch(f"{_CONV}.media_store.is_configured", return_value=True)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_502_presign_failure(
        self, _mock_user, _mock_takeover, _mock_conf, mock_put, mock_presign, mock_send, mock_save, _mock_pub
    ):
        res = self._post_file()
        self.assertEqual(res.status_code, 502)
        mock_send.assert_not_called()

    @patch(f"{_CONV}.pubsub.publish")
    @patch(f"{_CONV}.save_agent_message", return_value=123)
    @patch(f"{_CONV}.send_image_message", return_value={"status": "error", "message": "rejected"})
    @patch(f"{_CONV}.media_store.presign_get", return_value="https://b2.example/signed")
    @patch(f"{_CONV}.media_store.put_bytes", return_value=True)
    @patch(f"{_CONV}.media_store.is_configured", return_value=True)
    @patch(f"{_CONV}.get_takeover_status", return_value={"active": True})
    @patch(f"{_CONV}.get_user_by_phone", return_value=_user())
    def test_502_gupshup_soft_error(
        self, _mock_user, _mock_takeover, _mock_conf, mock_put, mock_presign, mock_send, mock_save, _mock_pub
    ):
        res = self._post_file()
        self.assertEqual(res.status_code, 502)
        mock_save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
