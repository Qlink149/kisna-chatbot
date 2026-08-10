"""Tests for callback / video-call flow parsing."""

import asyncio
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
from kisna_chatbot.utils.support_slots import (  # noqa: E402
    SLOT_CAPACITY,
    clear_capacity_overrides,
    set_capacity_overrides,
)

_FLOW_ID_PATCHES = (
    "kisna_chatbot.processors.callback_agent.get_callback_flow_id",
    "kisna_chatbot.processors.callback_agent.get_videocall_flow_id",
)
_IST = timezone(timedelta(hours=5, minutes=30))


class TestCallbackAgent(unittest.TestCase):
    def setUp(self):
        set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)

    def tearDown(self):
        clear_capacity_overrides()

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
                                "preferred_time": "10-13",
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
        self.assertEqual(parsed["preferred_time"], "10-13")

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
                                "preferred_time": "13-15",
                                "request_type": "video_call",
                            }
                        )
                    }
                }
            }
            parsed = _parse_support_request_flow(messages)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["preferred_time"], "13-15")

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
            preferred_time="10-13",
            preferred_date=yesterday,
            request_type="callback",
        )
        self.assertTrue(doc["preferred_date_past"])
        self.assertEqual(doc["preferred_time_label"], "Morning — 10 AM–1 PM")

    @patch("kisna_chatbot.processors.callback_agent.callback_requests")
    @patch("kisna_chatbot.processors.callback_agent.send_customer_support_template")
    @patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test")
    @patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test")
    def test_flow_past_date_reschedules(
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
                                "preferred_time": "13-15",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        result = asyncio.run(agent.process(data))
        mock_coll.insert_one.assert_called_once()
        saved = mock_coll.insert_one.call_args[0][0]
        self.assertNotEqual(saved["preferred_date"], yesterday)
        text = result["bot_response"][0]["text"].lower()
        self.assertIn("request id", text)
        self.assertIn("full", text)
        mock_notify.assert_called()

    @patch("kisna_chatbot.processors.callback_agent.callback_requests")
    @patch("kisna_chatbot.processors.callback_agent.send_customer_support_template")
    @patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test")
    @patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test")
    def test_flow_full_slot_reschedules(
        self, _mock_cb_id, _mock_vc_id, mock_notify, mock_coll
    ):
        def slot_count(_d, sid):
            return SLOT_CAPACITY if sid == "10-13" else 0

        set_capacity_overrides(lambda _d: 1, slot_count)
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
                                "preferred_date": "2099-08-03",  # Mon
                                "preferred_time": "10-13",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        result = asyncio.run(agent.process(data))
        mock_coll.insert_one.assert_called_once()
        saved = mock_coll.insert_one.call_args[0][0]
        self.assertEqual(saved["preferred_date"], "2099-08-03")
        self.assertEqual(saved["preferred_time"], "13-15")
        text = result["bot_response"][0]["text"].lower()
        self.assertIn("full", text)
        self.assertTrue("13-15" in text or "1 pm" in text)
        mock_notify.assert_called()

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
                                "preferred_date": "2099-08-03",  # Mon
                                "preferred_time": "13-15",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        result = asyncio.run(agent.process(data))
        self.assertIn("Request ID", result["bot_response"][0]["text"])
        self.assertNotIn("full", result["bot_response"][0]["text"].lower())
        mock_coll.insert_one.assert_called_once()
        saved = mock_coll.insert_one.call_args[0][0]
        self.assertEqual(saved["preferred_date"], "2099-08-03")
        self.assertEqual(saved["preferred_time"], "13-15")
        self.assertIn("Afternoon", saved["preferred_time_label"])
        mock_notify.assert_called()


if __name__ == "__main__":
    unittest.main()
