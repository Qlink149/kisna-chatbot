"""Win-back / re-engagement nudge — sweep selection, guards, and copy.

Mirrors tests/test_clara_events.py: the Mongo collection and the outbound send
are mocked, so this runs with no network and no DB.
"""

import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.processors import reengagement as re  # noqa: E402
from kisna_chatbot.prompts.kisna_knowledge_base import (  # noqa: E402
    build_dropoff_message,
)

_NOW = int(time.time())
_HOUR = 3600


def _profile(**over):
    p = {
        "phone_number": "919812345678",
        "client_id": "kisna",
        "language": "en",
        "last_message_at": _NOW - 4 * _HOUR,
    }
    p.update(over)
    return p


class _EnabledCase(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {"KISNA_REENGAGE_ENABLED": "true"})
        self._env.start()
        self.addCleanup(self._env.stop)


class SkipReasonTests(_EnabledCase):
    def test_due_user_has_no_skip_reason(self):
        self.assertIsNone(re._skip_reason(_profile(), _NOW))

    def test_not_idle_enough(self):
        p = _profile(last_message_at=_NOW - 1 * _HOUR)
        self.assertEqual(re._skip_reason(p, _NOW), "not_idle_enough")

    def test_not_selected_when_last_inbound_23_5h_despite_recent_last_message(self):
        # Idle enough by last_message_at (4h), but the customer's last inbound
        # was 23.5h ago: Meta would reject the send (131047), so skip.
        p = _profile(last_inbound_at=_NOW - int(23.5 * _HOUR))
        self.assertEqual(re._skip_reason(p, _NOW), "window_closed")

    def test_window_closed_when_too_old(self):
        p = _profile(last_message_at=_NOW - 40 * _HOUR)
        self.assertEqual(re._skip_reason(p, _NOW), "window_closed")

    def test_opted_out(self):
        self.assertEqual(
            re._skip_reason(_profile(reengage_opted_out=True), _NOW), "opted_out"
        )

    def test_already_nudged_this_lull(self):
        p = _profile(reengage_last_sent_at=_NOW - 2 * _HOUR)  # after last_message_at
        self.assertEqual(re._skip_reason(p, _NOW), "already_nudged_this_lull")

    def test_cooldown_between_lulls(self):
        # Spoke again (last_message_at recent) but a nudge went out 2 days ago.
        p = _profile(
            last_message_at=_NOW - 4 * _HOUR,
            reengage_last_sent_at=_NOW - 5 * _HOUR,
        )
        # sent_at is before last_message_at -> not "this lull"; still inside 7d.
        self.assertEqual(re._skip_reason(p, _NOW), "cooldown")

    def test_missing_timestamp(self):
        p = _profile()
        del p["last_message_at"]
        self.assertEqual(re._skip_reason(p, _NOW), "no_last_message_at")


class SweepTests(_EnabledCase):
    def _sweep(self, candidates, *, takeover=None):
        find = MagicMock()
        find.sort.return_value.limit.return_value = candidates
        with patch.object(re.users, "find", return_value=find), patch.object(
            re.users, "update_one"
        ) as update_one, patch.object(
            re, "get_takeover_status", return_value=takeover
        ), patch.object(
            re, "compose", new_callable=AsyncMock, side_effect=lambda key, text, **k: text
        ), patch.object(
            re, "send_text_message_with_retry"
        ) as send, patch.object(
            re, "save_agent_message"
        ):
            sent = asyncio.run(re.sweep_reengagement())
        return sent, send, update_one

    def test_due_user_gets_one_nudge(self):
        sent, send, update_one = self._sweep([_profile()])
        self.assertEqual(sent, 1)
        send.assert_called_once()
        phone, payload = send.call_args[0]
        self.assertEqual(phone, "919812345678")
        self.assertEqual(payload["type"], "text")
        self.assertTrue(payload["text"])
        set_doc = update_one.call_args[0][1]["$set"]
        self.assertIn("reengage_last_sent_at", set_doc)
        self.assertIn("reengage_last_line", set_doc)

    def test_human_takeover_blocks_the_nudge(self):
        sent, send, _ = self._sweep([_profile()], takeover={"active": True})
        self.assertEqual(sent, 0)
        send.assert_not_called()

    def test_opted_out_user_is_not_sent(self):
        sent, send, _ = self._sweep([_profile(reengage_opted_out=True)])
        self.assertEqual(sent, 0)
        send.assert_not_called()

    def test_sibling_brand_user_is_never_nudged(self):
        # The copy is KISNA-specific — an "nkl" user must not receive it even if
        # the query somehow returns them.
        sent, send, _ = self._sweep([_profile(client_id="nkl")])
        self.assertEqual(sent, 0)
        send.assert_not_called()

    def test_disabled_flag_is_a_noop(self):
        self._env.stop()  # drop KISNA_REENGAGE_ENABLED
        try:
            with patch.object(re.users, "find") as find, patch.object(
                re, "send_text_message_with_retry"
            ) as send:
                sent = asyncio.run(re.sweep_reengagement())
            self.assertEqual(sent, 0)
            find.assert_not_called()
            send.assert_not_called()
        finally:
            self._env.start()


class DropoffCopyTests(unittest.TestCase):
    """KB v2.1: the nudge is the client's drop-off broadcast, never paraphrased."""

    def test_build_returns_todays_dropoff_message(self):
        text, idx = re.build_reengagement_message(_profile())
        self.assertEqual(text, build_dropoff_message())
        self.assertEqual(idx, 0)

    def test_english_is_sent_verbatim_and_never_narrated(self):
        async def _run():
            with patch.object(re, "compose", new_callable=AsyncMock) as comp:
                text, _ = await re.compose_reengagement(_profile(language="en"))
            comp.assert_not_awaited()
            self.assertEqual(text, build_dropoff_message())

        asyncio.run(_run())
        self.assertFalse(hasattr(re, "narrate"))

    def test_other_languages_get_faithful_compose_with_pins(self):
        async def _run():
            with patch.object(
                re, "compose", new_callable=AsyncMock, side_effect=lambda key, text, **k: text
            ) as comp:
                text, _ = await re.compose_reengagement(_profile(language="hi-Latn"))
            kwargs = comp.await_args.kwargs
            self.assertEqual(kwargs["language"], "hi-Latn")
            self.assertIn("https://www.kisna.com/pages/jewellery-offers", kwargs["pin"])
            self.assertIn("35%", kwargs["pin"])
            self.assertEqual(text, build_dropoff_message())

        asyncio.run(_run())

    def test_compose_failure_falls_back_to_english_message(self):
        async def _run():
            with patch.object(re, "compose", new_callable=AsyncMock, return_value=""):
                text, _ = await re.compose_reengagement(_profile(language="ta"))
            self.assertEqual(text, build_dropoff_message())

        asyncio.run(_run())


class OptOutWiringTests(unittest.TestCase):
    def test_unsubscribe_sets_reengage_opted_out(self):
        from kisna_chatbot.processors.classifier import _unsubscribe

        data = {"user_profile": {"language": "en"}}
        _unsubscribe(data)
        self.assertTrue(data["user_profile"]["reengage_opted_out"])


if __name__ == "__main__":
    unittest.main()
