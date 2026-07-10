"""Tests for callbacks dashboard API routes."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("KISNA_UTM_ENABLED", "false")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from fastapi.testclient import TestClient  # noqa: E402

from kisna_chatbot.main import app  # noqa: E402
from kisna_chatbot.routes.dependencies.system_dependencies import verify_token  # noqa: E402


def _fake_verify_token():
    return {"sub": "test-admin", "role": "super_admin"}


class TestCallbacksAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[verify_token] = _fake_verify_token
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(verify_token, None)

    @patch("kisna_chatbot.routes.system_sub_routes.callbacks.get_all_callback_requests")
    def test_list_callbacks(self, mock_list):
        mock_list.return_value = {
            "total": 1,
            "page": 1,
            "limit": 20,
            "callbacks": [
                {
                    "request_id": "KIS-CB-20260710-AB12",
                    "request_type": "callback",
                    "status": "pending",
                }
            ],
        }
        res = self.client.get("/system/callbacks?client_id=kisna")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["callbacks"][0]["request_id"], "KIS-CB-20260710-AB12")

    @patch("kisna_chatbot.routes.system_sub_routes.callbacks.update_callback_status")
    def test_patch_callback_status(self, mock_patch):
        mock_patch.return_value = {
            "request_id": "KIS-CB-20260710-AB12",
            "status": "completed",
        }
        res = self.client.patch(
            "/system/callbacks/KIS-CB-20260710-AB12?client_id=kisna",
            json={"status": "completed"},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "completed")


if __name__ == "__main__":
    unittest.main()
