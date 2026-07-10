"""Tests for callback / video-call flow parsing."""

import json
import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")
# Force test flow IDs — .env may load real Gupshup IDs via load_dotenv().
os.environ["KISNA_CALLBACK_FLOW_ID"] = "flow_callback_test"
os.environ["KISNA_VIDEOCALL_FLOW_ID"] = "flow_video_test"

from kisna_chatbot.processors.callback_agent import (  # noqa: E402
    CallbackAgent,
    _parse_support_request_flow,
)

_FLOW_ID_PATCHES = (
    "kisna_chatbot.processors.callback_agent.get_callback_flow_id",
    "kisna_chatbot.processors.callback_agent.get_videocall_flow_id",
)


class TestCallbackAgent(unittest.TestCase):
    def test_parse_callback_flow(self):
        with (
            patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test"),
            patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test"),
        ):
            messages = {
                "interactive": {
                    "nfm_reply": {
                        "response_json": json.dumps(
                            {
                                "flow_token": "flow_callback_test",
                                "mobile": "9876543210",
                                "reason": "order_support",
                                "preferred_time": "morning",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            }
            parsed = _parse_support_request_flow(messages)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["mobile"], "9876543210")

    def test_parse_video_call_flow(self):
        with (
            patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test"),
            patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test"),
        ):
            messages = {
                "interactive": {
                    "nfm_reply": {
                        "response_json": json.dumps(
                            {
                                "flow_token": "flow_video_test",
                                "mobile": "9876543210",
                                "preferred_time": "afternoon",
                                "request_type": "video_call",
                            }
                        )
                    }
                }
            }
            parsed = _parse_support_request_flow(messages)
        self.assertIsNotNone(parsed)

    @patch("kisna_chatbot.processors.callback_agent.callback_requests")
    @patch("kisna_chatbot.processors.callback_agent.send_customer_support_template")
    @patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test")
    @patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test")
    def test_flow_submission_saves_and_confirms(
        self, _mock_cb_id, _mock_vc_id, mock_notify, mock_coll
    ):
        mock_coll.insert_one = MagicMock()
        agent = CallbackAgent()
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "client_config": MagicMock(client_id="kisna"),
            "whatsapp_username": "Test User",
            "user_profile": {"service_selected": "callback"},
            "messages": {
                "interactive": {
                    "nfm_reply": {
                        "response_json": json.dumps(
                            {
                                "flow_token": "flow_callback_test",
                                "mobile": "9876543210",
                                "reason": "product_enquiry",
                                "preferred_time": "morning",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        import asyncio

        result = asyncio.run(agent.process(data))
        self.assertIn("Request ID", result["bot_response"][0]["text"])
        mock_coll.insert_one.assert_called_once()
        mock_notify.assert_called()


if __name__ == "__main__":
    unittest.main()
