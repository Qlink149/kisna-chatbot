"""Tests for callback / video-call flow parsing."""

import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ["KISNA_CALLBACK_FLOW_ID"] = "flow_callback_test"
os.environ["KISNA_VIDEOCALL_FLOW_ID"] = "flow_video_test"

from kisna_chatbot.processors.callback_agent import (  # noqa: E402
    CallbackAgent,
    _build_request_doc,
    _is_past_date,
    _parse_support_request_flow,
)

_FLOW_ID_PATCHES = (
    "kisna_chatbot.processors.callback_agent.get_callback_flow_id",
    "kisna_chatbot.processors.callback_agent.get_videocall_flow_id",
)
_IST = timezone(timedelta(hours=5, minutes=30))


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
                                "preferred_date": "2026-07-20",
                                "preferred_time": "10-11",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            }
            parsed = _parse_support_request_flow(messages)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["mobile"], "9876543210")
        self.assertEqual(parsed["preferred_date"], "2026-07-20")
        self.assertEqual(parsed["preferred_time"], "10-11")

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
                                "preferred_date": "2026-07-21",
                                "preferred_time": "14-15",
                                "request_type": "video_call",
                            }
                        )
                    }
                }
            }
            parsed = _parse_support_request_flow(messages)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["preferred_time"], "14-15")

    def test_past_date_flag_on_doc_builder(self):
        yesterday = (datetime.now(_IST).date() - timedelta(days=1)).isoformat()
        self.assertTrue(_is_past_date(yesterday))
        doc = _build_request_doc(
            request_id="KIS-CB-TEST",
            client_id="kisna",
            phone_number="919999999999",
            customer_name="Test",
            mobile="9876543210",
            reason="other",
            preferred_time="10-11",
            preferred_date=yesterday,
            request_type="callback",
        )
        self.assertTrue(doc["preferred_date_past"])
        self.assertEqual(doc["preferred_time_label"], "Morning — 10 AM–11 AM")

    @patch("kisna_chatbot.processors.callback_agent.callback_requests")
    @patch("kisna_chatbot.processors.callback_agent.send_customer_support_template")
    @patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test")
    @patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test")
    def test_flow_rejects_past_date(
        self, _mock_cb_id, _mock_vc_id, mock_notify, mock_coll
    ):
        mock_coll.insert_one = MagicMock()
        yesterday = (datetime.now(_IST).date() - timedelta(days=1)).isoformat()
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
                                "preferred_date": yesterday,
                                "preferred_time": "14-15",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        import asyncio

        result = asyncio.run(agent.process(data))
        self.assertIn("already passed", result["bot_response"][0]["text"].lower())
        mock_coll.insert_one.assert_not_called()
        mock_notify.assert_not_called()

    @patch("kisna_chatbot.processors.callback_agent.is_preferred_datetime_valid")
    @patch("kisna_chatbot.processors.callback_agent.callback_requests")
    @patch("kisna_chatbot.processors.callback_agent.send_customer_support_template")
    @patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test")
    @patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test")
    def test_flow_rejects_past_slot(
        self, _mock_cb_id, _mock_vc_id, mock_notify, mock_coll, mock_valid
    ):
        mock_valid.return_value = (False, "past_slot")
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
                                "preferred_date": "2099-01-01",
                                "preferred_time": "10-11",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        import asyncio

        result = asyncio.run(agent.process(data))
        self.assertIn("no longer available", result["bot_response"][0]["text"].lower())
        mock_coll.insert_one.assert_not_called()

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
                                "preferred_date": "2099-08-01",
                                "preferred_time": "14-15",
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
        saved = mock_coll.insert_one.call_args[0][0]
        self.assertEqual(saved["preferred_date"], "2099-08-01")
        self.assertEqual(saved["preferred_time"], "14-15")
        self.assertIn("Afternoon", saved["preferred_time_label"])
        mock_notify.assert_called()


if __name__ == "__main__":
    unittest.main()
