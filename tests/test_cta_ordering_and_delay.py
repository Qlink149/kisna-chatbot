"""'Delay in collection' fix: the "See Collection" CTA must render last.

Two independent pieces:
1. handle_responses gives image_with_cta sends more buffer than other types
   before submitting the next item, since Gupshup "submitted" != WhatsApp
   "delivered" -- a lightweight interactive message can otherwise win the
   delivery race and render before a still-processing product image sent
   moments earlier, even though we sent them in the correct order.
2. _ensure_explore_more_cta_last (main.py) is a safety net for anything that
   appends to bot_response AFTER a search result already built the CTA last
   (e.g. a secondary intent's gold-rate/offers answer tacked onto the same
   turn) -- moves the CTA back to the true end of the whole turn.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

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


class TestSendDelayIsTypeAware(unittest.TestCase):
    def test_image_delay_is_longer_than_default(self):
        import kisna_chatbot.processors.response_manager as rm

        self.assertGreater(rm._IMAGE_SEND_DELAY_SECONDS, rm._DEFAULT_SEND_DELAY_SECONDS)

    def test_image_send_gets_the_longer_delay(self):
        import kisna_chatbot.processors.response_manager as rm

        rmgr = rm.ResponseManager()
        rmgr._handlers = {
            "image_with_cta": MagicMock(return_value={"status": "submitted"}),
            "cta_url": MagicMock(return_value={"status": "submitted"}),
        }
        data = {
            "phone_number": "919999999999",
            "bot_response": [
                {"type": "image_with_cta"},
                {"type": "cta_url"},
            ],
            "user_profile": {},
        }
        with patch.object(rm, "is_window_open", return_value=True), patch.object(
            rm.outbound_rate_limiter, "wait_if_needed"
        ), patch.object(rm, "time") as time_mock:
            rmgr.handle_responses(data)

        delays = [c.args[0] for c in time_mock.sleep.call_args_list]
        self.assertEqual(delays, [rm._IMAGE_SEND_DELAY_SECONDS, rm._DEFAULT_SEND_DELAY_SECONDS])

    def test_env_vars_tune_both_delays(self):
        with patch.dict(
            os.environ,
            {
                "KISNA_SEND_DELAY_SECONDS": "0.7",
                "KISNA_IMAGE_SEND_DELAY_SECONDS": "2.5",
            },
        ):
            import importlib

            import kisna_chatbot.processors.response_manager as rm

            importlib.reload(rm)
            try:
                self.assertEqual(rm._DEFAULT_SEND_DELAY_SECONDS, 0.7)
                self.assertEqual(rm._IMAGE_SEND_DELAY_SECONDS, 2.5)
            finally:
                importlib.reload(rm)  # restore module-level state for later tests


class TestEnsureExploreMoreCtaLast(unittest.TestCase):
    def setUp(self):
        from kisna_chatbot.main import _ensure_explore_more_cta_last

        self.fn = _ensure_explore_more_cta_last

    def _cta(self):
        return {
            "type": "cta_url",
            "display_text": "See Collection",
            "_compose": "search_explore_more",
        }

    def test_already_last_is_untouched(self):
        original = [{"type": "image_with_cta"}, {"type": "image_with_cta"}, self._cta()]
        data = {"bot_response": list(original)}
        self.fn(data)
        self.assertEqual(data["bot_response"], original)

    def test_moves_cta_after_a_trailing_secondary_answer(self):
        cta = self._cta()
        data = {
            "bot_response": [
                {"type": "image_with_cta", "id": "p1"},
                {"type": "image_with_cta", "id": "p2"},
                cta,
                {"type": "text", "text": "Gold rate today is...", "_compose": "gold_rate"},
            ]
        }
        self.fn(data)
        self.assertEqual(data["bot_response"][-1], cta)
        self.assertEqual(len(data["bot_response"]), 4)
        # Relative order of everything else preserved.
        self.assertEqual(data["bot_response"][0]["id"], "p1")
        self.assertEqual(data["bot_response"][1]["id"], "p2")
        self.assertEqual(data["bot_response"][2]["_compose"], "gold_rate")

    def test_no_cta_present_is_a_no_op(self):
        original = [{"type": "text", "text": "hi"}]
        data = {"bot_response": list(original)}
        self.fn(data)
        self.assertEqual(data["bot_response"], original)

    def test_missing_bot_response_does_not_raise(self):
        data = {}
        self.fn(data)  # must not raise
        self.assertNotIn("bot_response", data)

    def test_single_item_is_a_no_op(self):
        original = [self._cta()]
        data = {"bot_response": list(original)}
        self.fn(data)
        self.assertEqual(data["bot_response"], original)


if __name__ == "__main__":
    unittest.main()
