"""Tests for callback / video-call flow parsing."""

import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_OFFERS_API", "http://localhost")
os.environ.setdefault("KISNA_STORE_API", "http://localhost")
os.environ.setdefault("KISNA_VTIGER_BASE", "http://localhost")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("GUPSHUP_WEBHOOK_SECRET", "test")
os.environ["KISNA_CALLBACK_FLOW_ID"] = "flow_callback_test"
os.environ["KISNA_VIDEOCALL_FLOW_ID"] = "flow_video_test"

from kisna_chatbot.processors.callback_agent import (  # noqa: E402
    CallbackAgent,
    _build_request_doc,
    _is_past_date,
    _parse_support_request_flow,
    parse_text_mobile,
    resolve_callback_mobile,
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


    def test_should_run_without_callback_service(self):
        """Flow submit after session cleared must still be claimed."""
        with (
            patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test"),
            patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test"),
        ):
            agent = CallbackAgent()
            data = {
                "phone_number": "919999999999",
                "user_profile": {"service_selected": ""},
                "messages": {
                    "interactive": {
                        "type": "nfm_reply",
                        "nfm_reply": {
                            "response_json": json.dumps(
                                {
                                    "flow_token": "flow_callback_test",
                                    "mobile": "9116914178",
                                    "reason": "exchange_return",
                                    "preferred_date": "2026-08-12",
                                    "preferred_time": "13-15",
                                    "request_type": "callback",
                                }
                            )
                        },
                    }
                },
            }
            self.assertTrue(agent.should_run(data))

    def test_initial_pipeline_includes_callback_agent(self):
        from kisna_chatbot.pipelines.inference_pipeline import InitialPipeline

        names = [type(p).__name__ for p in InitialPipeline().processors]
        self.assertIn("CallbackAgent", names)
        self.assertIn("ComplaintAgent", names)
        self.assertLess(names.index("CallbackAgent"), names.index("ServiceList"))
        self.assertLess(names.index("ComplaintAgent"), names.index("ServiceList"))

    def test_service_list_routes_budget_flow_when_service_cleared(self):
        """Budget Flow submit must not become the help menu."""
        from kisna_chatbot.processors.service_list import ServiceList

        processor = ServiceList()
        data = {
            "phone_number": "919999999999",
            "user_profile": {"service_selected": ""},
            "messages": {
                "interactive": {
                    "type": "nfm_reply",
                    "nfm_reply": {
                        "name": "flow",
                        "response_json": json.dumps({"budget_input": "under 30k"}),
                    },
                }
            },
        }
        result = asyncio.run(processor.process(data))
        self.assertEqual(
            result["user_profile"]["service_selected"], "product_search"
        )
        self.assertNotIn("bot_response", result)

    def test_resolve_callback_mobile_falls_back_to_whatsapp(self):
        self.assertEqual(
            resolve_callback_mobile("", "919999999999"),
            "919999999999",
        )
        self.assertEqual(
            resolve_callback_mobile("  ", "+91 99999 99999"),
            "919999999999",
        )
        self.assertEqual(
            resolve_callback_mobile("98765-43210", "919999999999"),
            "9876543210",
        )

    def test_parse_text_mobile_skip_and_digits(self):
        mobile, err = parse_text_mobile("skip", "919111111111")
        self.assertEqual(mobile, "919111111111")
        self.assertIsNone(err)
        mobile, err = parse_text_mobile("98 765 43210", "919111111111")
        self.assertEqual(mobile, "9876543210")
        self.assertIsNone(err)
        mobile, err = parse_text_mobile("call me maybe", "919111111111")
        self.assertIsNone(mobile)
        self.assertIn("digits", err.lower())

    @patch("kisna_chatbot.processors.callback_agent.callback_requests")
    @patch("kisna_chatbot.processors.callback_agent.send_customer_support_template")
    @patch(_FLOW_ID_PATCHES[1], return_value="flow_video_test")
    @patch(_FLOW_ID_PATCHES[0], return_value="flow_callback_test")
    def test_flow_blank_mobile_uses_whatsapp_number(
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
                                "mobile": "",
                                "reason": "product_enquiry",
                                "preferred_date": "2099-08-03",
                                "preferred_time": "13-15",
                                "request_type": "callback",
                            }
                        )
                    }
                }
            },
        }
        asyncio.run(agent.process(data))
        saved = mock_coll.insert_one.call_args[0][0]
        self.assertEqual(saved["mobile"], "919999999999")
        mock_notify.assert_called()
        self.assertEqual(mock_notify.call_args.kwargs["customer_phone"], "919999999999")

    def test_callback_flow_json_mobile_is_optional_digits(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for name in ("callback_request.json", "video_call_request.json"):
            spec = json.loads((root / "json" / name).read_text(encoding="utf-8"))
            children = spec["screens"][0]["layout"]["children"][0]["children"]
            mobile = next(c for c in children if c.get("name") == "mobile")
            self.assertFalse(mobile.get("required"))
            self.assertEqual(mobile.get("input-type"), "number")


if __name__ == "__main__":
    unittest.main()
