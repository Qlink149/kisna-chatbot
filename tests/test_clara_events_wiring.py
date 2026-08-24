"""End-to-end wiring: agent submissions must enqueue the right Clara event.

Complements tests/test_clara_events.py (which covers payload shape and the
outbox). Here we assert the three agents actually fire, with the right event
type and the *booked* slot.
"""

import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ["KISNA_CALLBACK_FLOW_ID"] = "flow_callback_test"
os.environ["KISNA_VIDEOCALL_FLOW_ID"] = "flow_video_test"

from kisna_chatbot.processors.callback_agent import CallbackAgent  # noqa: E402
from kisna_chatbot.processors.complaint_agent import ComplaintAgent  # noqa: E402
from kisna_chatbot.utils.support_slots import (  # noqa: E402
    SLOT_CAPACITY,
    clear_capacity_overrides,
    set_capacity_overrides,
)

_IST = timezone(timedelta(hours=5, minutes=30))

_CB_ID = "kisna_chatbot.processors.callback_agent.get_callback_flow_id"
_VC_ID = "kisna_chatbot.processors.callback_agent.get_videocall_flow_id"
_CMP_ID = "kisna_chatbot.processors.complaint_agent.get_damage_complaint_flow_id"

_ENQUEUE_CB = "kisna_chatbot.processors.callback_agent.enqueue_clara_event"
_ENQUEUE_CMP = "kisna_chatbot.processors.complaint_agent.enqueue_clara_event"

_COMPLAINT_FLOW_TOKEN = "flow_complaint_test"


def _messages(flow_payload: dict) -> dict:
    return {
        "interactive": {"nfm_reply": {"response_json": json.dumps(flow_payload)}}
    }


def _support_data(flow_payload: dict) -> dict:
    return {
        "phone_number": "919812345678",
        "client_id": "kisna",
        "client_config": MagicMock(client_id="kisna"),
        "whatsapp_username": "Rahul Sharma",
        "user_profile": {"service_selected": "callback"},
        "messages": _messages(flow_payload),
    }


class TestComplaintWiring(unittest.TestCase):
    def _run(self, flow_payload, insert_side_effect=None):
        with patch(_ENQUEUE_CMP, new_callable=AsyncMock) as enqueue, patch(
            "kisna_chatbot.processors.complaint_agent.complaints"
        ) as coll, patch(
            "kisna_chatbot.processors.complaint_agent.CRMAdapter"
        ) as mock_crm, patch(
            _CMP_ID, return_value=_COMPLAINT_FLOW_TOKEN
        ):
            crm = MagicMock()
            crm.create_case = AsyncMock(return_value={"id": "CASE-1"})
            crm.aclose = AsyncMock()
            mock_crm.return_value = crm
            coll.insert_one = MagicMock(side_effect=insert_side_effect)

            data = {
                "phone_number": "919812345678",
                "client_id": "kisna",
                "client_config": MagicMock(client_id="kisna"),
                "whatsapp_username": "Rahul Sharma",
                "user_profile": {},
                "messages": _messages(flow_payload),
            }
            asyncio.run(ComplaintAgent().process(data))
        return enqueue, coll.insert_one

    def test_complaint_enqueues_event_matching_the_saved_record(self):
        enqueue, insert = self._run(
            {
                "flow_token": _COMPLAINT_FLOW_TOKEN,
                "order_id": "ORD12345",
                "complaint_type": "4_Returns_Related",
                "issue_description": "Ring arrived damaged; stone is loose.",
            }
        )

        enqueue.assert_awaited_once()
        payload = enqueue.await_args[0][0]
        saved = insert.call_args[0][0]

        self.assertEqual(payload["event_type"], "complaint_submitted")
        self.assertTrue(payload["event_id"].startswith("KIS-CMP-"))
        # The pushed id must be the one persisted, so retries stay idempotent
        # and support can find the record.
        self.assertEqual(payload["event_id"], saved["request_id"])
        self.assertTrue(payload["occurred_at"].endswith("Z"))
        self.assertEqual(payload["brand"], "kisna")
        self.assertEqual(payload["source"], "whatsapp_chatbot")
        self.assertEqual(payload["customer"]["whatsapp_number"], "919812345678")
        self.assertEqual(payload["customer"]["name"], "Rahul Sharma")
        self.assertEqual(
            payload["data"],
            {
                "order_id": "ORD12345",
                "complaint_type": "4_Returns_Related",
                "issue_description": "Ring arrived damaged; stone is loose.",
            },
        )

    def test_screen_field_names_still_produce_a_valid_event(self):
        enqueue, _ = self._run(
            {
                "flow_token": _COMPLAINT_FLOW_TOKEN,
                "screen_0_Order_ID_0": "ORD999",
                "screen_0_Issue_Description_1": "Broken clasp",
                "screen_0_complaint_type_2": "5_Exchange_Buyback",
            }
        )
        payload = enqueue.await_args[0][0]
        self.assertEqual(payload["data"]["order_id"], "ORD999")
        self.assertEqual(payload["data"]["complaint_type"], "5_Exchange_Buyback")

    def test_no_event_when_the_record_could_not_be_saved(self):
        enqueue, _ = self._run(
            {
                "flow_token": _COMPLAINT_FLOW_TOKEN,
                "order_id": "ORD1",
                "complaint_type": "9_Other",
                "issue_description": "x",
            },
            insert_side_effect=RuntimeError("mongo down"),
        )
        enqueue.assert_not_awaited()


class TestSupportRequestWiring(unittest.TestCase):
    def setUp(self):
        set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)

    def tearDown(self):
        clear_capacity_overrides()

    def _run(self, flow_payload):
        with patch(_ENQUEUE_CB, new_callable=AsyncMock) as enqueue, patch(
            "kisna_chatbot.processors.callback_agent.callback_requests"
        ) as coll, patch(
            "kisna_chatbot.processors.callback_agent.send_customer_support_template"
        ), patch(
            _CB_ID, return_value="flow_callback_test"
        ), patch(
            _VC_ID, return_value="flow_video_test"
        ):
            coll.insert_one = MagicMock()
            result = asyncio.run(CallbackAgent().process(_support_data(flow_payload)))
        return enqueue, coll.insert_one, result

    def test_callback_enqueues_callback_requested(self):
        enqueue, insert, _ = self._run(
            {
                "flow_token": "flow_callback_test",
                "mobile": "9876543210",
                "reason": "product_enquiry",
                "preferred_date": "2099-08-03",  # a Monday
                "preferred_time": "10-13",
                "request_type": "callback",
            }
        )
        enqueue.assert_awaited_once()
        payload = enqueue.await_args[0][0]
        saved = insert.call_args[0][0]

        self.assertEqual(payload["event_type"], "callback_requested")
        self.assertEqual(payload["event_id"], saved["request_id"])
        self.assertTrue(payload["event_id"].startswith("KIS-CB-"))
        self.assertEqual(payload["data"]["request_id"], payload["event_id"])
        self.assertEqual(payload["data"]["request_type"], "callback")
        self.assertEqual(payload["data"]["mobile"], "9876543210")
        self.assertEqual(payload["data"]["reason"], "product_enquiry")
        self.assertEqual(payload["data"]["preferred_date"], "2099-08-03")
        self.assertEqual(payload["data"]["preferred_time"], "10-13")
        self.assertEqual(
            payload["data"]["preferred_time_label"], "Morning - 10 AM-1 PM"
        )

    def test_video_call_enqueues_video_event_without_reason(self):
        enqueue, _, _ = self._run(
            {
                "flow_token": "flow_video_test",
                "mobile": "",
                "preferred_date": "2099-08-03",
                "preferred_time": "13-15",
                "request_type": "video_call",
            }
        )
        enqueue.assert_awaited_once()
        payload = enqueue.await_args[0][0]

        self.assertEqual(payload["event_type"], "video_call_requested")
        self.assertTrue(payload["event_id"].startswith("KIS-VC-"))
        self.assertEqual(payload["data"]["request_type"], "video_call")
        self.assertNotIn("reason", payload["data"])
        # A blank mobile falls back to the WhatsApp number.
        self.assertEqual(payload["data"]["mobile"], "919812345678")

    def test_pushes_the_booked_slot_not_the_requested_one(self):
        def slot_count(_d, sid):
            return SLOT_CAPACITY if sid == "10-13" else 0

        set_capacity_overrides(lambda _d: 1, slot_count)
        enqueue, insert, result = self._run(
            {
                "flow_token": "flow_callback_test",
                "mobile": "9876543210",
                "reason": "order_support",
                "preferred_date": "2099-08-03",
                "preferred_time": "10-13",  # full -> auto-assigned to 13-15
                "request_type": "callback",
            }
        )
        payload = enqueue.await_args[0][0]
        saved = insert.call_args[0][0]

        self.assertEqual(saved["preferred_time"], "13-15")
        self.assertEqual(payload["data"]["preferred_time"], "13-15")
        self.assertEqual(
            payload["data"]["preferred_time_label"], "Afternoon - 1 PM-3 PM"
        )
        # What we push must match what the customer was told.
        self.assertIn("full", result["bot_response"][0]["text"].lower())

    def test_rejected_request_is_never_pushed(self):
        # Everything full across the whole lookahead window.
        set_capacity_overrides(lambda _d: 999, lambda _d, _s: 999)
        enqueue, insert, result = self._run(
            {
                "flow_token": "flow_callback_test",
                "mobile": "9876543210",
                "reason": "other",
                "preferred_date": "2099-08-03",
                "preferred_time": "10-13",
                "request_type": "callback",
            }
        )
        enqueue.assert_not_awaited()
        insert.assert_not_called()
        self.assertIn("booked", result["bot_response"][0]["text"].lower())


class TestTextPathWiring(unittest.TestCase):
    """The text fallback must push exactly like the flow path."""

    def setUp(self):
        set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)

    def tearDown(self):
        clear_capacity_overrides()

    def test_text_capture_enqueues_event(self):
        future = (datetime.now(_IST).date() + timedelta(days=400)).isoformat()
        data = {
            "phone_number": "919812345678",
            "client_id": "kisna",
            "client_config": MagicMock(client_id="kisna"),
            "whatsapp_username": "Rahul Sharma",
            "user_profile": {
                "service_selected": "callback",
                "callback_capture_step": 4,
                "callback_draft": {
                    "request_type": "callback",
                    "mobile": "9876543210",
                    "reason": "store_assistance",
                    "preferred_date": future,
                },
            },
            "messages": {"text": {"body": "10-13"}},
        }
        with patch(_ENQUEUE_CB, new_callable=AsyncMock) as enqueue, patch(
            "kisna_chatbot.processors.callback_agent.callback_requests"
        ) as coll, patch(
            "kisna_chatbot.processors.callback_agent.send_customer_support_template"
        ), patch(
            _CB_ID, return_value=""
        ), patch(
            _VC_ID, return_value=""
        ):
            coll.insert_one = MagicMock()
            asyncio.run(CallbackAgent().process(data))

        enqueue.assert_awaited_once()
        payload = enqueue.await_args[0][0]
        self.assertEqual(payload["event_type"], "callback_requested")
        self.assertEqual(payload["data"]["reason"], "store_assistance")
        self.assertEqual(payload["data"]["mobile"], "9876543210")


if __name__ == "__main__":
    unittest.main()
