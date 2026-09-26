"""Handoff-fallback sweep (F10 callback fallback + F11 stale-takeover
auto-expiry) — sweep selection and idempotency. Mirrors
tests/test_reengagement.py: Mongo collections and outbound sends are mocked,
so this runs with no network and no DB. Unconditional -- no on/off flag."""

import asyncio
import os
import time
import unittest
from unittest.mock import ANY, AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.processors import handoff_sweep as hs  # noqa: E402

_NOW = int(time.time())


def _handoff_profile(**over):
    p = {
        "phone_number": "919812345678",
        "client_id": "kisna",
        "language": "en",
        "live_agent_required": True,
        "live_agent_requested_at": _NOW - 400,
    }
    p.update(over)
    return p


def _takeover_profile(**over):
    p = {
        "phone_number": "919812345678",
        "client_id": "kisna",
        "human_takeover": {"active": True, "taken_at": _NOW - 13 * 3600},
    }
    p.update(over)
    return p


class OpportunisticTriggerTests(unittest.TestCase):
    def test_opportunistic_trigger_schedules_a_sweep(self) -> None:
        async def _run():
            with patch.object(hs, "sweep_handoff") as sweep:
                hs.trigger_opportunistic_sweep()
                await asyncio.sleep(0)
                sweep.assert_called_once()

        asyncio.run(_run())


class CallbackFallbackSweepTests(unittest.TestCase):
    def _sweep(self, candidates, *, pending_callback=None):
        find = MagicMock()
        find.sort.return_value.limit.return_value = candidates
        with patch.object(hs.users, "find", return_value=find), patch.object(
            hs.users, "find_one_and_update"
        ) as armed, patch.object(
            hs.callback_requests, "find_one", return_value=pending_callback
        ), patch.object(
            hs, "compose", new_callable=AsyncMock, side_effect=lambda key, text, **k: text
        ), patch.object(
            # These cases test episode logic, not the working-hours gate.
            hs, "_working_delay_elapsed", return_value=True
        ), patch.object(
            hs, "send_text_message_with_retry"
        ) as send_text, patch.object(
            hs, "send_callback_request_flow"
        ) as send_flow, patch.object(
            hs, "save_agent_message"
        ), patch.object(
            hs.users, "find", return_value=find
        ):
            armed.return_value = {"phone_number": "919812345678"}  # arm succeeds
            sent = asyncio.run(hs._sweep_callback_fallback(25))
        return sent, send_text, send_flow, armed

    def test_pending_handoff_gets_callback_fallback(self):
        sent, send_text, send_flow, armed = self._sweep([_handoff_profile()])
        self.assertEqual(sent, 1)
        send_text.assert_called_once()
        send_flow.assert_called_once_with("919812345678")
        # Idempotency filter: marker absent, or older than THIS episode's request.
        filter_arg = armed.call_args[0][0]
        self.assertEqual(
            filter_arg["$or"],
            [
                {"handoff_callback_sent_at": {"$exists": False}},
                {"handoff_callback_sent_at": {"$lt": _NOW - 400}},
            ],
        )

    def test_arm_race_lost_sends_nothing(self):
        # find_one_and_update returning None means someone else already armed it.
        find = MagicMock()
        find.sort.return_value.limit.return_value = [_handoff_profile()]
        with patch.object(hs.users, "find", return_value=find), patch.object(
            hs.users, "find_one_and_update", return_value=None
        ), patch.object(hs, "send_text_message_with_retry") as send_text:
            sent = asyncio.run(hs._sweep_callback_fallback(25))
        self.assertEqual(sent, 0)
        send_text.assert_not_called()

    def test_already_booked_callback_sends_nothing_but_stays_armed(self):
        booked = {"preferred_date": "2026-09-10", "status": "pending"}
        sent, send_text, send_flow, armed = self._sweep(
            [_handoff_profile()], pending_callback=booked
        )
        self.assertEqual(sent, 0)
        send_text.assert_not_called()
        send_flow.assert_not_called()
        armed.assert_called_once()  # still armed, so it's never re-checked

    def test_query_requires_no_active_takeover_and_no_prior_send(self):
        find = MagicMock()
        find.sort.return_value.limit.return_value = []
        with patch.object(hs.users, "find", return_value=find) as find_mock:
            asyncio.run(hs._sweep_callback_fallback(25))
        query = find_mock.call_args[0][0]
        self.assertEqual(query["live_agent_required"], True)
        self.assertEqual(query["human_takeover.active"], {"$ne": True})
        self.assertNotIn("handoff_callback_sent_at", query)

    def test_query_uses_or_with_expr(self):
        find = MagicMock()
        find.sort.return_value.limit.return_value = []
        with patch.object(hs.users, "find", return_value=find) as find_mock:
            asyncio.run(hs._sweep_callback_fallback(25))
        query = find_mock.call_args[0][0]
        self.assertEqual(
            query["$or"],
            [
                {"handoff_callback_sent_at": {"$exists": False}},
                {"$expr": {"$lt": ["$handoff_callback_sent_at", "$live_agent_requested_at"]}},
            ],
        )
        # A request must exist: the range filter on it is still there.
        self.assertIn("$lte", query["live_agent_requested_at"])


class EpisodeEligibilityTests(unittest.TestCase):
    """The fallback is once per handoff EPISODE, not once per customer."""

    T = _NOW - 10_000

    def _run(self, profile):
        find = MagicMock()
        find.sort.return_value.limit.return_value = [profile]
        with patch.object(hs.users, "find", return_value=find), patch.object(
            hs.users, "find_one_and_update", return_value={"phone_number": "919812345678"}
        ) as armed, patch.object(
            hs.callback_requests, "find_one", return_value=None
        ), patch.object(
            hs, "compose", new_callable=AsyncMock, side_effect=lambda key, text, **k: text
        ), patch.object(
            # These cases test episode logic, not the working-hours gate.
            hs, "_working_delay_elapsed", return_value=True
        ), patch.object(
            hs, "send_text_message_with_retry"
        ) as send_text, patch.object(
            hs, "send_callback_request_flow"
        ), patch.object(hs, "save_agent_message"):
            sent = asyncio.run(hs._sweep_callback_fallback(25))
        return sent, send_text, armed

    def test_episode1_fires_and_arms(self):
        sent, send_text, armed = self._run(
            _handoff_profile(live_agent_requested_at=self.T)
        )
        self.assertEqual(sent, 1)
        send_text.assert_called_once()
        self.assertEqual(armed.call_args[0][1], {"$set": {"handoff_callback_sent_at": ANY}})

    def test_episode2_same_user_fires_again(self):
        # Episode 1 fired at T+300; a NEW request came in at T+3600. This is
        # the case that was permanently excluded before the fix.
        profile = _handoff_profile(
            live_agent_requested_at=self.T + 3600,
            handoff_callback_sent_at=self.T + 300,
        )
        self.assertTrue(hs._eligible_for_fallback(profile))
        sent, send_text, armed = self._run(profile)
        self.assertEqual(sent, 1)
        send_text.assert_called_once()
        self.assertIn(
            {"handoff_callback_sent_at": {"$lt": self.T + 3600}},
            armed.call_args[0][0]["$or"],
        )

    def test_marker_newer_than_request_does_not_refire(self):
        profile = _handoff_profile(
            live_agent_requested_at=self.T,
            handoff_callback_sent_at=self.T + 300,
        )
        self.assertFalse(hs._eligible_for_fallback(profile))
        sent, send_text, armed = self._run(profile)
        self.assertEqual(sent, 0)
        send_text.assert_not_called()
        armed.assert_not_called()

    def test_stale_marker_without_request_not_eligible(self):
        profile = _handoff_profile(handoff_callback_sent_at=self.T)
        profile.pop("live_agent_requested_at")
        self.assertFalse(hs._eligible_for_fallback(profile))
        sent, send_text, armed = self._run(profile)
        self.assertEqual(sent, 0)
        armed.assert_not_called()

    def test_malformed_marker_is_not_eligible(self):
        profile = _handoff_profile(handoff_callback_sent_at="garbage")
        self.assertFalse(hs._eligible_for_fallback(profile))


class StaleTakeoverSweepTests(unittest.TestCase):
    def _sweep(self, candidates):
        find = MagicMock()
        find.limit.return_value = candidates
        with patch.object(hs.users, "find", return_value=find), patch.object(
            hs, "set_takeover"
        ) as set_takeover, patch.object(hs.users, "update_one") as update_one:
            expired = asyncio.run(hs._sweep_stale_takeovers(25))
        return expired, set_takeover, update_one

    def test_stale_takeover_is_expired(self):
        expired, set_takeover, update_one = self._sweep([_takeover_profile()])
        self.assertEqual(expired, 1)
        set_takeover.assert_called_once_with("919812345678", False, "kisna")
        # handoff_callback_sent_at must be cleared so a future handoff can re-arm.
        unset = update_one.call_args[0][1]["$unset"]
        self.assertIn("handoff_callback_sent_at", unset)

    def test_query_only_matches_active_and_past_ttl(self):
        find = MagicMock()
        find.limit.return_value = []
        with patch.object(hs.users, "find", return_value=find) as find_mock:
            asyncio.run(hs._sweep_stale_takeovers(25))
        query = find_mock.call_args[0][0]
        self.assertEqual(query["human_takeover.active"], True)
        self.assertIn("$lte", query["human_takeover.taken_at"])


if __name__ == "__main__":
    unittest.main()
