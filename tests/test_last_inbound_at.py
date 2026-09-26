"""last_inbound_at: the WhatsApp-window clock, moved only by a customer inbound.

Prod, Sept 2026: every Meta 131047 ("more than 24 hours since the customer
last replied") came from a send gated on a clock that non-inbound writes also
refresh. These tests pin which writes may move last_inbound_at.
Mongo is mocked -- no network, no DB.
"""

import os
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot import main  # noqa: E402
from kisna_chatbot.database import db_utils  # noqa: E402

_PHONE = "919812345678"


def _turn_data(*, inbound_at=None, profile_extra=None):
    profile = {"phone_number": _PHONE, "chat_history": []}
    profile.update(profile_extra or {})
    data = {
        "phone_number": _PHONE,
        "client_id": "kisna",
        "messages": {"type": "text", "text": {"body": "hi"}, "from": _PHONE},
        "bot_response": [{"type": "text", "text": "Hello"}],
        "user_profile": profile,
    }
    if inbound_at is not None:
        data["_inbound_at"] = inbound_at
    return data


def _save(data):
    with patch.object(db_utils.users, "find_one_and_update", return_value={}) as fau, patch.object(
        db_utils, "dual_write_chat_entries"
    ):
        db_utils.save_to_mongo(data)
    return fau.call_args[0][1]


class SaveToMongoTests(unittest.TestCase):
    def test_customer_inbound_turn_updates_both(self):
        inbound = int(time.time()) - 5
        update = _save(_turn_data(inbound_at=inbound))
        self.assertIn("last_message_at", update["$set"])
        self.assertEqual(update["$max"], {"last_inbound_at": inbound})

    def test_bot_persisted_turn_without_inbound_does_not_move_last_inbound_at(self):
        stale = int(time.time()) - 30 * 3600
        update = _save(_turn_data(profile_extra={"last_inbound_at": stale}))
        self.assertIn("last_message_at", update["$set"])
        self.assertNotIn("last_inbound_at", update["$set"])
        self.assertNotIn("$max", update)

    def test_in_memory_value_is_never_set_back(self):
        # Even with an inbound this turn, the profile's copy goes via $max only.
        inbound = int(time.time())
        update = _save(_turn_data(inbound_at=inbound, profile_extra={"last_inbound_at": inbound}))
        self.assertNotIn("last_inbound_at", update["$set"])


class TouchLastMessageAtTests(unittest.TestCase):
    def test_silent_inbound_updates_both(self):
        with patch.object(db_utils.users, "update_one") as update_one:
            db_utils.touch_last_message_at(_PHONE, "kisna", inbound_at=1_700_000_000)
        update = update_one.call_args[0][1]
        self.assertIn("last_message_at", update["$set"])
        self.assertEqual(update["$max"], {"last_inbound_at": 1_700_000_000})

    def test_without_inbound_at_leaves_it_alone(self):
        with patch.object(db_utils.users, "update_one") as update_one:
            db_utils.touch_last_message_at(_PHONE, "kisna")
        self.assertNotIn("$max", update_one.call_args[0][1])


class AgentWritesTests(unittest.TestCase):
    def test_agent_message_does_not_touch_window_clock(self):
        with patch.object(db_utils.users, "update_one") as update_one, patch.object(
            db_utils, "dual_write_chat_entries", create=True
        ), patch.object(db_utils, "_insert_chat_message", create=True):
            db_utils.save_agent_message(_PHONE, "hello from agent", "kisna")
        for call in update_one.call_args_list:
            update = call[0][1]
            for op in update.values():
                if isinstance(op, dict):
                    self.assertNotIn("last_inbound_at", op)
                    self.assertNotIn("last_message_at", op)


class InboundEpochTests(unittest.TestCase):
    def test_uses_payload_timestamp(self):
        now = int(time.time())
        self.assertEqual(main._inbound_epoch({"timestamp": str(now - 120)}), now - 120)

    def test_future_timestamp_capped_at_now(self):
        now = int(time.time())
        self.assertLessEqual(main._inbound_epoch({"timestamp": str(now + 3600)}), now + 1)

    def test_missing_or_bad_timestamp_is_now(self):
        now = int(time.time())
        self.assertGreaterEqual(main._inbound_epoch({}), now)
        self.assertGreaterEqual(main._inbound_epoch({"timestamp": "x"}), now)

    def test_stamp_inbound_moves_in_memory_profile_forward_only(self):
        data = {"user_profile": {"last_inbound_at": 200}, "_inbound_at": 100}
        main._stamp_inbound(data)
        self.assertEqual(data["user_profile"]["last_inbound_at"], 200)
        data["_inbound_at"] = 300
        main._stamp_inbound(data)
        self.assertEqual(data["user_profile"]["last_inbound_at"], 300)


class WindowClosedStatusLogTests(unittest.TestCase):
    def test_131047_logged_as_warning_with_last4_and_no_raise(self):
        event = {
            "statuses": [
                {
                    "id": "wamid.x",
                    "status": "failed",
                    "recipient_id": "917229017787",
                    "errors": [{"code": 131047, "title": "Re-engagement message"}],
                }
            ]
        }
        with patch.object(main, "logger", MagicMock()) as log:
            main._log_whatsapp_status_failures(event)
        log.error.assert_not_called()
        log.warning.assert_called_once()
        extra = log.warning.call_args.kwargs["extra"]
        self.assertEqual(extra["recipient_last4"], "7787")
        self.assertNotIn("917229017787", str(log.warning.call_args))

    def test_other_failures_still_error(self):
        event = {"statuses": [{"status": "failed", "errors": [{"code": 131053}]}]}
        with patch.object(main, "logger", MagicMock()) as log:
            main._log_whatsapp_status_failures(event)
        log.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
