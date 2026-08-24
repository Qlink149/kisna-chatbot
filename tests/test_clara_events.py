"""Contract + outbox tests for the Clara event push (-> Salesforce).

The golden-payload tests assert byte-for-byte agreement with the three curl
bodies the client sent us. If one of them fails, the contract has drifted.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.integrations import clara_events as ce  # noqa: E402

# 2026-08-21T10:30:00Z
_T_COMPLAINT = 1787308200
# 2026-08-21T11:00:00Z
_T_CALLBACK = 1787310000
# 2026-08-21T11:15:00Z
_T_VIDEO = 1787310900


class TestHelpers(unittest.TestCase):
    def test_iso_utc_renders_zulu(self):
        self.assertEqual(ce._iso_utc(_T_COMPLAINT), "2026-08-21T10:30:00Z")

    def test_ascii_dashes_normalises_typographic_dashes(self):
        self.assertEqual(
            ce._ascii_dashes("Morning — 10 AM–1 PM"), "Morning - 10 AM-1 PM"
        )
        self.assertEqual(ce._ascii_dashes("Day — 10 AM–4 PM"), "Day - 10 AM-4 PM")

    def test_ascii_dashes_leaves_slot_ids_alone(self):
        self.assertEqual(ce._ascii_dashes("10-13"), "10-13")

    def test_digits_strips_formatting(self):
        self.assertEqual(ce._digits("+91 98123-45678"), "919812345678")


class TestComplaintPayload(unittest.TestCase):
    def test_matches_client_contract(self):
        payload = ce.build_complaint_event(
            event_id="KIS-CMP-20260821-A1B2",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="Rahul Sharma",
            order_id="ORD12345",
            complaint_type="4_Returns_Related",
            issue_description="Ring arrived damaged; stone is loose.",
            occurred_at_epoch=_T_COMPLAINT,
        )
        self.assertEqual(
            payload,
            {
                "event_id": "KIS-CMP-20260821-A1B2",
                "event_type": "complaint_submitted",
                "occurred_at": "2026-08-21T10:30:00Z",
                "source": "whatsapp_chatbot",
                "brand": "kisna",
                "customer": {
                    "whatsapp_number": "919812345678",
                    "name": "Rahul Sharma",
                },
                "data": {
                    "order_id": "ORD12345",
                    "complaint_type": "4_Returns_Related",
                    "issue_description": "Ring arrived damaged; stone is loose.",
                },
            },
        )

    def test_complaint_type_passed_through_verbatim(self):
        for option_id in (
            "0_Want_to_Buy",
            "1_Order_Related",
            "2_Payment_Related",
            "3_Stores_Related",
            "4_Returns_Related",
            "5_Exchange_Buyback",
            "6_Digital_Gold",
            "7_Kisna_Points",
            "8_10_Plus_1_Monthly_Plan",
            "9_Other",
        ):
            payload = ce.build_complaint_event(
                event_id="KIS-CMP-20260821-A1B2",
                client_id="kisna",
                phone_number="919812345678",
                customer_name="X",
                order_id="",
                complaint_type=option_id,
                issue_description="",
                occurred_at_epoch=_T_COMPLAINT,
            )
            self.assertEqual(payload["data"]["complaint_type"], option_id)

    def test_missing_fields_become_empty_strings(self):
        payload = ce.build_complaint_event(
            event_id="KIS-CMP-20260821-A1B2",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="",
            order_id="",
            complaint_type="",
            issue_description="",
            occurred_at_epoch=_T_COMPLAINT,
        )
        self.assertEqual(payload["data"]["order_id"], "")
        self.assertEqual(payload["customer"]["name"], "")


class TestCallbackPayload(unittest.TestCase):
    def test_matches_client_contract(self):
        payload = ce.build_support_request_event(
            request_id="KIS-CB-20260821-A1B2",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="Rahul Sharma",
            mobile="9876543210",
            request_type="callback",
            reason="product_enquiry",
            preferred_date="2026-08-22",
            preferred_time="10-13",
            preferred_time_label="Morning — 10 AM–1 PM",
            occurred_at_epoch=_T_CALLBACK,
        )
        self.assertEqual(
            payload,
            {
                "event_id": "KIS-CB-20260821-A1B2",
                "event_type": "callback_requested",
                "occurred_at": "2026-08-21T11:00:00Z",
                "source": "whatsapp_chatbot",
                "brand": "kisna",
                "customer": {
                    "whatsapp_number": "919812345678",
                    "name": "Rahul Sharma",
                },
                "data": {
                    "request_id": "KIS-CB-20260821-A1B2",
                    "request_type": "callback",
                    "mobile": "9876543210",
                    "reason": "product_enquiry",
                    "preferred_date": "2026-08-22",
                    "preferred_time": "10-13",
                    "preferred_time_label": "Morning - 10 AM-1 PM",
                },
            },
        )

    def test_event_id_equals_request_id(self):
        payload = ce.build_support_request_event(
            request_id="KIS-CB-20260821-A1B2",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="R",
            mobile="9876543210",
            request_type="callback",
            reason="other",
            preferred_date="2026-08-22",
            preferred_time="10-13",
            preferred_time_label="Morning — 10 AM–1 PM",
            occurred_at_epoch=_T_CALLBACK,
        )
        self.assertEqual(payload["event_id"], payload["data"]["request_id"])

    def test_reason_omitted_when_blank(self):
        payload = ce.build_support_request_event(
            request_id="KIS-CB-20260821-A1B2",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="R",
            mobile="9876543210",
            request_type="callback",
            reason=None,
            preferred_date="2026-08-22",
            preferred_time="10-13",
            preferred_time_label="Morning — 10 AM–1 PM",
            occurred_at_epoch=_T_CALLBACK,
        )
        self.assertNotIn("reason", payload["data"])

    def test_saturday_slot_label(self):
        payload = ce.build_support_request_event(
            request_id="KIS-CB-20260822-9999",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="R",
            mobile="9876543210",
            request_type="callback",
            reason="order_support",
            preferred_date="2026-08-22",
            preferred_time="10-16",
            preferred_time_label="Day — 10 AM–4 PM",
            occurred_at_epoch=_T_CALLBACK,
        )
        self.assertEqual(payload["data"]["preferred_time"], "10-16")
        self.assertEqual(
            payload["data"]["preferred_time_label"], "Day - 10 AM-4 PM"
        )


class TestVideoCallPayload(unittest.TestCase):
    def test_matches_client_contract(self):
        payload = ce.build_support_request_event(
            request_id="KIS-VC-20260821-C3D4",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="Rahul Sharma",
            mobile="919812345678",
            request_type="video_call",
            reason=None,
            preferred_date="2026-08-22",
            preferred_time="13-15",
            preferred_time_label="Afternoon — 1 PM–3 PM",
            occurred_at_epoch=_T_VIDEO,
        )
        self.assertEqual(
            payload,
            {
                "event_id": "KIS-VC-20260821-C3D4",
                "event_type": "video_call_requested",
                "occurred_at": "2026-08-21T11:15:00Z",
                "source": "whatsapp_chatbot",
                "brand": "kisna",
                "customer": {
                    "whatsapp_number": "919812345678",
                    "name": "Rahul Sharma",
                },
                "data": {
                    "request_id": "KIS-VC-20260821-C3D4",
                    "request_type": "video_call",
                    "mobile": "919812345678",
                    "preferred_date": "2026-08-22",
                    "preferred_time": "13-15",
                    "preferred_time_label": "Afternoon - 1 PM-3 PM",
                },
            },
        )

    def test_reason_never_sent_even_when_supplied(self):
        payload = ce.build_support_request_event(
            request_id="KIS-VC-20260821-C3D4",
            client_id="kisna",
            phone_number="919812345678",
            customer_name="R",
            mobile="919812345678",
            request_type="video_call",
            reason="product_enquiry",
            preferred_date="2026-08-22",
            preferred_time="13-15",
            preferred_time_label="Afternoon — 1 PM–3 PM",
            occurred_at_epoch=_T_VIDEO,
        )
        self.assertNotIn("reason", payload["data"])


class TestClassification(unittest.TestCase):
    def test_success_statuses(self):
        self.assertEqual(ce._classify(200, None), "sent")
        self.assertEqual(ce._classify(201, None), "sent")
        self.assertEqual(ce._classify(202, None), "sent")

    def test_duplicate_is_success(self):
        self.assertEqual(ce._classify(409, None), "sent")

    def test_retryable(self):
        for status in (408, 425, 429, 500, 502, 503, 504):
            self.assertEqual(ce._classify(status, None), "retry", status)
        self.assertEqual(ce._classify(None, "timeout"), "retry")

    def test_permanent_client_errors(self):
        for status in (400, 401, 403, 404, 422):
            self.assertEqual(ce._classify(status, None), "permanent", status)

    def test_backoff_grows_and_is_capped(self):
        self.assertEqual(ce._retry_delay(1), 120)
        self.assertEqual(ce._retry_delay(2), 240)
        self.assertEqual(ce._retry_delay(20), ce._MAX_RETRY_DELAY)


def _closing_spawn():
    """Stand-in for _spawn that consumes the coroutine (no 'never awaited' warning)."""

    def _spawn(coro):
        coro.close()

    return _spawn


def _payload(event_id="KIS-CB-20260821-A1B2"):
    return {
        "event_id": event_id,
        "event_type": "callback_requested",
        "brand": "kisna",
        "customer": {"whatsapp_number": "919812345678", "name": "R"},
        "data": {},
    }


class TestEnqueue(unittest.TestCase):
    def setUp(self):
        os.environ["KISNA_CLARA_EVENTS_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("KISNA_CLARA_EVENTS_ENABLED", None)

    def test_disabled_writes_nothing_and_sends_nothing(self):
        os.environ["KISNA_CLARA_EVENTS_ENABLED"] = "false"
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_post", new_callable=AsyncMock
        ) as post:
            asyncio.run(ce.enqueue_event(_payload()))
        events.insert_one.assert_not_called()
        post.assert_not_awaited()

    def test_enqueue_inserts_pending_row(self):
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_spawn", side_effect=_closing_spawn()
        ) as spawn:
            asyncio.run(ce.enqueue_event(_payload()))
        events.insert_one.assert_called_once()
        doc = events.insert_one.call_args[0][0]
        self.assertEqual(doc["event_id"], "KIS-CB-20260821-A1B2")
        self.assertEqual(doc["status"], "pending")
        self.assertEqual(doc["attempts"], 0)
        self.assertEqual(doc["client_id"], "kisna")
        spawn.assert_called_once()

    def test_duplicate_event_id_does_not_send_twice(self):
        from pymongo.errors import DuplicateKeyError

        with patch.object(ce, "_events") as events, patch.object(
            ce, "_spawn", side_effect=_closing_spawn()
        ) as spawn:
            events.insert_one.side_effect = DuplicateKeyError("dup")
            asyncio.run(ce.enqueue_event(_payload()))
        spawn.assert_not_called()

    def test_mongo_failure_does_not_propagate(self):
        with patch.object(ce, "_events") as events, patch.object(ce, "_spawn", side_effect=_closing_spawn()):
            events.insert_one.side_effect = RuntimeError("mongo down")
            # Must not raise -- the customer's confirmation depends on it.
            asyncio.run(ce.enqueue_event(_payload()))

    def test_missing_event_id_is_dropped(self):
        with patch.object(ce, "_events") as events, patch.object(ce, "_spawn", side_effect=_closing_spawn()):
            asyncio.run(ce.enqueue_event({"event_type": "callback_requested"}))
        events.insert_one.assert_not_called()


class TestAttemptOnce(unittest.TestCase):
    def setUp(self):
        os.environ["KISNA_CLARA_EVENTS_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("KISNA_CLARA_EVENTS_ENABLED", None)

    def _run(self, status, body=None, error=None, attempts=0):
        doc = {
            "event_id": "KIS-CB-1",
            "event_type": "callback_requested",
            "payload": _payload(),
            "attempts": attempts,
        }
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_post", new_callable=AsyncMock, return_value=(status, body, error)
        ):
            outcome = asyncio.run(ce._attempt_once(doc))
        update = events.update_one.call_args[0][1]["$set"]
        return outcome, update

    def test_2xx_marks_sent_and_stores_response(self):
        outcome, update = self._run(200, {"id": "500xx000001"})
        self.assertEqual(outcome, "sent")
        self.assertEqual(update["status"], "sent")
        self.assertEqual(update["response"], {"id": "500xx000001"})
        self.assertIsNotNone(update["sent_at"])

    def test_409_marks_sent(self):
        outcome, update = self._run(409, {"error": "duplicate"})
        self.assertEqual(outcome, "sent")
        self.assertEqual(update["status"], "sent")

    def test_500_stays_pending_with_future_retry(self):
        outcome, update = self._run(500, "boom")
        self.assertEqual(outcome, "retry")
        self.assertEqual(update["status"], "pending")
        self.assertEqual(update["attempts"], 1)
        self.assertGreater(update["next_attempt_at"], 0)

    def test_timeout_stays_pending(self):
        outcome, update = self._run(None, None, "timeout")
        self.assertEqual(outcome, "retry")
        self.assertEqual(update["status"], "pending")
        self.assertEqual(update["last_error"], "timeout")

    def test_400_is_permanent_and_never_retried(self):
        outcome, update = self._run(400, {"error": "bad field"})
        self.assertEqual(outcome, "permanent")
        self.assertEqual(update["status"], "failed_permanent")
        self.assertNotIn("next_attempt_at", update)

    def test_exhausted_attempts_marked_failed(self):
        outcome, update = self._run(500, "boom", attempts=ce.MAX_ATTEMPTS - 1)
        self.assertEqual(outcome, "retry")
        self.assertEqual(update["status"], "failed")
        self.assertNotIn("next_attempt_at", update)


# Real response bodies captured from the client's UAT endpoint on 2026-08-24.
_UAT_CASE_OK = {
    "data": {
        "event_id": "KIS-CMP-20260824-0BF9",
        "status": "processed",
        "enq_id": "SUPP-0065022",
        "salesforce": {
            "target": "case",
            "success": True,
            "record_id": "500HF00000GuDz4YAF",
            "error": None,
        },
    },
    "status": 200,
    "message": "Event processed",
}

_UAT_LEAD_FAILED = {
    "data": {
        "event_id": "KIS-CB-20260824-478C",
        "status": "failed",
        "enq_id": "SUPP-0065023",
        "salesforce": {
            "target": "lead",
            "success": False,
            "record_id": None,
            "error": "Salesforce call failed",
        },
    },
    "status": 200,
    "message": "Event stored, Salesforce push failed",
}


class TestDownstreamStatus(unittest.TestCase):
    """Their endpoint answers 200 even when its own Salesforce push fails."""

    def test_reads_success(self):
        ok, err = ce._downstream_status(_UAT_CASE_OK)
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_reads_failure_and_reason(self):
        ok, err = ce._downstream_status(_UAT_LEAD_FAILED)
        self.assertFalse(ok)
        self.assertEqual(err, "Salesforce call failed")

    def test_falls_back_to_data_status(self):
        ok, err = ce._downstream_status({"data": {"status": "failed"}})
        self.assertFalse(ok)
        self.assertIn("failed", err)
        ok, _ = ce._downstream_status({"data": {"status": "processed"}})
        self.assertTrue(ok)

    def test_unknown_shapes_are_neutral(self):
        for body in (None, "ok", {}, {"data": "x"}, {"data": {}}):
            ok, err = ce._downstream_status(body)
            self.assertIsNone(ok, body)
            self.assertIsNone(err, body)


class TestDownstreamRecorded(unittest.TestCase):
    def setUp(self):
        os.environ["KISNA_CLARA_EVENTS_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("KISNA_CLARA_EVENTS_ENABLED", None)

    def _attempt(self, body):
        doc = {
            "event_id": "KIS-CB-1",
            "event_type": "callback_requested",
            "payload": _payload(),
            "attempts": 0,
        }
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_post", new_callable=AsyncMock, return_value=(200, body, None)
        ):
            outcome = asyncio.run(ce._attempt_once(doc))
        return outcome, events.update_one.call_args[0][1]["$set"]

    def test_downstream_failure_is_recorded_but_not_retried(self):
        outcome, update = self._attempt(_UAT_LEAD_FAILED)
        # Retrying would duplicate: the receiver is not idempotent.
        self.assertEqual(outcome, "sent")
        self.assertEqual(update["status"], "sent")
        self.assertFalse(update["downstream_ok"])
        self.assertEqual(update["downstream_error"], "Salesforce call failed")

    def test_clean_delivery_flagged_ok(self):
        outcome, update = self._attempt(_UAT_CASE_OK)
        self.assertEqual(outcome, "sent")
        self.assertTrue(update["downstream_ok"])
        self.assertIsNone(update["downstream_error"])
        self.assertEqual(
            update["response"]["data"]["salesforce"]["record_id"],
            "500HF00000GuDz4YAF",
        )


class TestSweep(unittest.TestCase):
    def setUp(self):
        os.environ["KISNA_CLARA_EVENTS_ENABLED"] = "true"

    def tearDown(self):
        os.environ.pop("KISNA_CLARA_EVENTS_ENABLED", None)

    def test_disabled_sweep_is_a_noop(self):
        os.environ["KISNA_CLARA_EVENTS_ENABLED"] = "false"
        with patch.object(ce, "_events") as events:
            self.assertEqual(asyncio.run(ce.sweep_pending()), 0)
        events.find.assert_not_called()

    def test_query_selects_only_due_rows_under_cap(self):
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_attempt_once", new_callable=AsyncMock
        ):
            events.find.return_value.sort.return_value.limit.return_value = []
            asyncio.run(ce.sweep_pending())
        query = events.find.call_args[0][0]
        self.assertEqual(query["status"], "pending")
        self.assertEqual(query["attempts"], {"$lt": ce.MAX_ATTEMPTS})
        self.assertIn("$lte", query["next_attempt_at"])

    def test_attempts_each_due_row(self):
        rows = [{"event_id": "a"}, {"event_id": "b"}]
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_attempt_once", new_callable=AsyncMock
        ) as attempt:
            events.find.return_value.sort.return_value.limit.return_value = rows
            attempted = asyncio.run(ce.sweep_pending())
        self.assertEqual(attempted, 2)
        self.assertEqual(attempt.await_count, 2)

    def test_one_bad_row_does_not_abort_the_sweep(self):
        rows = [{"event_id": "a"}, {"event_id": "b"}]
        with patch.object(ce, "_events") as events, patch.object(
            ce, "_attempt_once", new_callable=AsyncMock
        ) as attempt:
            events.find.return_value.sort.return_value.limit.return_value = rows
            attempt.side_effect = [RuntimeError("boom"), None]
            attempted = asyncio.run(ce.sweep_pending())
        self.assertEqual(attempted, 1)
        self.assertEqual(attempt.await_count, 2)


class TestConfig(unittest.TestCase):
    """Config is read lazily from os.environ, so each case patches it outright.

    Do not rely on the module-level setdefault calls here: a developer's real
    .env is already loaded by the time the full suite runs.
    """

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KISNA_CLARA_EVENTS_ENABLED", None)
            self.assertFalse(ce.is_enabled())

    def test_enabled_accepts_common_truthy_spellings(self):
        for value in ("true", "TRUE", "1", "yes", "on"):
            with patch.dict(os.environ, {"KISNA_CLARA_EVENTS_ENABLED": value}):
                self.assertTrue(ce.is_enabled(), value)

    def test_disabled_for_anything_else(self):
        for value in ("", "false", "0", "no", "off", "maybe"):
            with patch.dict(os.environ, {"KISNA_CLARA_EVENTS_ENABLED": value}):
                self.assertFalse(ce.is_enabled(), value)

    def test_base_url_falls_back_to_shared_clara_base(self):
        with patch.dict(
            os.environ,
            {
                "KISNA_CLARA_BASE_URL": "https://clara.example.com",
                "KISNA_CLARA_EVENTS_BASE_URL": "",
            },
        ):
            self.assertEqual(ce._base_url(), "https://clara.example.com")

    def test_events_base_url_overrides_and_strips_trailing_slash(self):
        with patch.dict(
            os.environ,
            {
                "KISNA_CLARA_BASE_URL": "https://clara.example.com",
                "KISNA_CLARA_EVENTS_BASE_URL": "https://events.example.com/",
            },
        ):
            self.assertEqual(ce._base_url(), "https://events.example.com")

    def test_headers_use_shared_clara_key(self):
        with patch.dict(os.environ, {"CLARA_API_KEY": "unit-test-key"}):
            headers = ce._headers()
        self.assertEqual(headers["x-clara-api-key"], "unit-test-key")
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_post_refuses_without_config(self):
        with patch.dict(
            os.environ,
            {"KISNA_CLARA_BASE_URL": "", "KISNA_CLARA_EVENTS_BASE_URL": ""},
        ):
            status, body, error = asyncio.run(ce._post({"event_id": "x"}))
        self.assertIsNone(status)
        self.assertIn("KISNA_CLARA_BASE_URL", error)
        # A missing endpoint must be retryable, not silently dropped.
        self.assertEqual(ce._classify(status, error), "retry")


if __name__ == "__main__":
    unittest.main()
