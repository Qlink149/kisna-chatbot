"""Inbound rate limiting: the 40/60s cap and the once-per-window notice.

Regression context: at the old 10/60s limit, a customer moving through the
guided product-search wizard (category -> gender -> budget -> fulfillment ->
confirm -> yes) could generate 10+ inbound messages within a minute and have
their final tap silently dropped -- no reply, nothing saved, no trace. The fix
raises the cap and, for whoever still trips it, replaces the silent drop with
one friendly notice instead of nothing.
"""

import os
import time
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.utils import rate_limiter as rl  # noqa: E402


class TestInboundRateLimit(unittest.TestCase):
    def setUp(self):
        rl._INBOUND_COUNTS.clear()
        rl._LAST_NOTIFIED.clear()

    def test_limit_is_40(self):
        self.assertEqual(rl.INBOUND_RATE_LIMIT, 40)

    def test_a_guided_wizard_burst_of_10_is_never_limited(self):
        # The exact scenario that used to trip the old 10/60s cap.
        for _ in range(10):
            self.assertFalse(rl.is_rate_limited("919999999999"))

    def test_allows_exactly_the_limit_then_blocks(self):
        phone = "919999999998"
        for _ in range(rl.INBOUND_RATE_LIMIT):
            self.assertFalse(rl.is_rate_limited(phone))
        self.assertTrue(rl.is_rate_limited(phone))

    def test_window_expiry_frees_up_slots(self):
        phone = "919999999997"
        now = time.time()
        # Fill the window with timestamps already outside INBOUND_RATE_WINDOW.
        rl._INBOUND_COUNTS[phone] = __import__("collections").deque(
            now - rl.INBOUND_RATE_WINDOW - 1 for _ in range(rl.INBOUND_RATE_LIMIT)
        )
        self.assertFalse(rl.is_rate_limited(phone))

    def test_phones_are_independent(self):
        for _ in range(rl.INBOUND_RATE_LIMIT):
            rl.is_rate_limited("919999999996")
        self.assertFalse(rl.is_rate_limited("919999999995"))


class TestRateLimitNotifyCooldown(unittest.TestCase):
    def setUp(self):
        rl._LAST_NOTIFIED.clear()

    def test_first_call_notifies(self):
        self.assertTrue(rl.should_notify_rate_limited("919999999994"))

    def test_repeat_within_cooldown_is_suppressed(self):
        phone = "919999999993"
        self.assertTrue(rl.should_notify_rate_limited(phone))
        # A burst of drops right after must not each fire their own notice.
        self.assertFalse(rl.should_notify_rate_limited(phone))
        self.assertFalse(rl.should_notify_rate_limited(phone))

    def test_notifies_again_after_cooldown_elapses(self):
        phone = "919999999992"
        rl._LAST_NOTIFIED[phone] = time.time() - rl.RATE_LIMIT_NOTIFY_COOLDOWN - 1
        self.assertTrue(rl.should_notify_rate_limited(phone))

    def test_phones_are_independent(self):
        rl.should_notify_rate_limited("919999999991")
        self.assertTrue(rl.should_notify_rate_limited("919999999990"))


class TestRateLimitDropSendsNotice(unittest.IsolatedAsyncioTestCase):
    """The main.py hook: on drop, send once; on repeat drop, stay silent."""

    async def test_dropped_message_triggers_one_text_send(self):
        import kisna_chatbot.main as main_mod

        with patch.object(
            main_mod, "is_rate_limited", return_value=True
        ), patch.object(
            main_mod, "should_notify_rate_limited", return_value=True
        ), patch(
            "kisna_chatbot.whatsapp_functions.send_text_message.send_text_message_with_retry"
        ) as send_mock:
            request_data = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": "919116914178",
                                            "id": "wamid.test123",
                                            "type": "interactive",
                                        }
                                    ],
                                    "contacts": [],
                                }
                            }
                        ]
                    }
                ]
            }
            await main_mod.process_message(request_data)

        send_mock.assert_called_once()
        args, _ = send_mock.call_args
        self.assertEqual(args[0], "919116914178")
        self.assertIn("moving fast", args[1]["text"])

    async def test_dropped_message_stays_silent_within_cooldown(self):
        import kisna_chatbot.main as main_mod

        with patch.object(
            main_mod, "is_rate_limited", return_value=True
        ), patch.object(
            main_mod, "should_notify_rate_limited", return_value=False
        ), patch(
            "kisna_chatbot.whatsapp_functions.send_text_message.send_text_message_with_retry"
        ) as send_mock:
            request_data = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": "919116914178",
                                            "id": "wamid.test456",
                                            "type": "interactive",
                                        }
                                    ],
                                    "contacts": [],
                                }
                            }
                        ]
                    }
                ]
            }
            await main_mod.process_message(request_data)

        send_mock.assert_not_called()

    async def test_a_gupshup_send_failure_does_not_crash_the_handler(self):
        import kisna_chatbot.main as main_mod

        with patch.object(
            main_mod, "is_rate_limited", return_value=True
        ), patch.object(
            main_mod, "should_notify_rate_limited", return_value=True
        ), patch(
            "kisna_chatbot.whatsapp_functions.send_text_message.send_text_message_with_retry",
            side_effect=RuntimeError("gupshup down"),
        ):
            request_data = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": "919116914178",
                                            "id": "wamid.test789",
                                            "type": "interactive",
                                        }
                                    ],
                                    "contacts": [],
                                }
                            }
                        ]
                    }
                ]
            }
            # Must not raise.
            await main_mod.process_message(request_data)


if __name__ == "__main__":
    unittest.main()
