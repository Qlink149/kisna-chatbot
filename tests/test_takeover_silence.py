"""F12 takeover-silence fallback (handoff_sweep): an agent took a chat over
and sent nothing. 5 minutes after the customer started waiting the bot sends
the F10 fallback form, hands the chat back silently (no reconnect / rating),
keeps live_agent_required, and leaves a system note on the dashboard.

In-memory users / chat_messages (the real queries and updates run against
them), frozen time, outbound sends mocked."""

import asyncio
import copy
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

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

PHONE = "919812345678"
_IST = ZoneInfo("Asia/Kolkata")
# Tuesday 6 Oct 2026: a working day, no holiday.
T_1100 = int(datetime(2026, 10, 6, 11, 0, tzinfo=_IST).timestamp())
T_1900 = int(datetime(2026, 10, 6, 19, 0, tzinfo=_IST).timestamp())
_MISSING = object()


# ---------------------------------------------------------------- tiny fake Mongo
def _get(doc, path):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return _MISSING
        cur = cur[part]
    return cur


def _cond(val, spec):
    if not isinstance(spec, dict) or not any(k.startswith("$") for k in spec):
        return val is not _MISSING and val == spec
    for op, arg in spec.items():
        if op == "$exists":
            if (val is not _MISSING) != bool(arg):
                return False
        elif op == "$ne":
            if val is not _MISSING and val == arg:
                return False
        elif op == "$not":
            if _cond(val, arg):
                return False
        elif op in ("$lt", "$lte", "$gt", "$gte"):
            if val is _MISSING or val is None:
                return False
            if not {"$lt": val < arg, "$lte": val <= arg, "$gt": val > arg, "$gte": val >= arg}[op]:
                return False
        else:
            raise NotImplementedError(op)
    return True


def _match(doc, query):
    for k, v in query.items():
        if k == "$or":
            if not any(_match(doc, q) for q in v):
                return False
        elif not _cond(_get(doc, k), v):
            return False
    return True


def _set(doc, path, value):
    parts = path.split(".")
    for p in parts[:-1]:
        doc = doc.setdefault(p, {})
    doc[parts[-1]] = value


def _unset(doc, path):
    parts = path.split(".")
    for p in parts[:-1]:
        doc = doc.get(p, {})
    doc.pop(parts[-1], None)


class _Cursor(list):
    def limit(self, n):
        return _Cursor(self[:n])

    def sort(self, *a, **k):
        return self


class FakeColl:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor(copy.deepcopy(d) for d in self.docs if _match(d, query or {}))

    def find_one(self, query=None, projection=None, sort=None):
        rows = [d for d in self.docs if _match(d, query or {})]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda d: _get(d, key), reverse=direction < 0)
        return copy.deepcopy(rows[0]) if rows else None

    def _apply(self, d, update):
        for k, v in update.get("$set", {}).items():
            _set(d, k, v)
        for k in update.get("$unset", {}):
            _unset(d, k)
        for k, v in update.get("$inc", {}).items():
            cur = _get(d, k)
            _set(d, k, (0 if cur is _MISSING else cur) + v)

    def find_one_and_update(self, query, update):
        for d in self.docs:
            if _match(d, query):
                before = copy.deepcopy(d)
                self._apply(d, update)
                return before
        return None

    def update_one(self, query, update, upsert=False):
        for d in self.docs:
            if _match(d, query):
                self._apply(d, update)
                return MagicMock(matched_count=1)
        return MagicMock(matched_count=0)


# ---------------------------------------------------------------- harness
def _user(taken_at, *, waiting=False, **takeover_extra):
    return {
        "phone_number": PHONE,
        "client_id": "kisna",
        "language": "en",
        "last_inbound_at": taken_at,
        "live_agent_required": True,
        "live_agent_requested_at": taken_at,
        "human_takeover": {
            "active": True, "taken_by": "agent", "taken_at": taken_at,
            "tracks_silence": True, "waiting_at_start": waiting, **takeover_extra,
        },
    }


class SilenceTestBase(unittest.TestCase):
    def setUp(self):
        self.users = FakeColl()
        self.chat = FakeColl()
        self.flow = MagicMock(return_value={"status": "submitted"})
        self.text = MagicMock(return_value={"status": "submitted"})
        self.note = MagicMock(return_value=(0, "note-id"))
        self.publish = AsyncMock()
        self.pending = None
        self.now = T_1100
        patches = [
            patch.object(hs, "users", self.users),
            patch.object(hs, "chat_messages", self.chat),
            patch.object(hs.callback_requests, "find_one", side_effect=lambda q: self.pending),
            patch.object(hs, "send_callback_request_flow", self.flow),
            patch.object(hs, "send_text_message_with_retry", self.text),
            patch.object(hs, "save_agent_message", MagicMock(return_value=(0, None))),
            patch.object(hs, "save_system_note", self.note),
            patch.object(hs.pubsub, "publish", self.publish),
            patch.object(hs.time, "time", side_effect=lambda: float(self.now)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def sweep(self, at):
        self.now = at
        return asyncio.run(hs._sweep_takeover_silence(25))

    def customer_says(self, at, text="hello?"):
        self.chat.docs.append({"phone": PHONE, "client_id": "kisna", "role": "user", "content": text, "ts": at})

    @property
    def takeover(self):
        return self.users.docs[0]["human_takeover"]


# ---------------------------------------------------------------- tests
class TimingTests(SilenceTestBase):
    def test_4_59_no_fire_5_00_fires(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        self.assertEqual(self.sweep(T_1100 + 299), 0)
        self.flow.assert_not_called()
        self.assertTrue(self.takeover["active"])
        self.assertEqual(self.sweep(T_1100 + 300), 1)
        self.flow.assert_called_once_with(PHONE, hs._FALLBACK_TEXT)

    def test_agent_message_at_3_00_never_fires(self):
        self.users.docs.append(_user(T_1100, waiting=True, agent_replied_at=T_1100 + 180))
        for at in (T_1100 + 300, T_1100 + 3600):
            self.assertEqual(self.sweep(at), 0)
        self.flow.assert_not_called()
        self.assertTrue(self.takeover["active"])

    def test_system_messages_alone_do_not_count_as_a_reply(self):
        # The takeover line is saved by save_agent_message without from_agent,
        # so agent_replied_at is never set; only that field counts.
        self.users.docs.append(_user(T_1100, waiting=True))
        self.chat.docs.append({"phone": PHONE, "client_id": "kisna", "role": "assistant",
                               "content": "You are now connected to a live support agent. Please hold on.", "ts": T_1100})
        self.assertEqual(self.sweep(T_1100 + 300), 1)

    def test_no_waiting_customer_never_fires(self):
        self.users.docs.append(_user(T_1100, waiting=False))
        for at in (T_1100 + 300, T_1100 + 4 * 3600):
            self.assertEqual(self.sweep(at), 0)
        self.flow.assert_not_called()

    def test_customer_writes_at_10_into_quiet_takeover_fires_at_15(self):
        self.users.docs.append(_user(T_1100, waiting=False))
        self.customer_says(T_1100 + 600)
        self.assertEqual(self.sweep(T_1100 + 899), 0)
        self.assertEqual(self.sweep(T_1100 + 900), 1)
        self.flow.assert_called_once()


class OutcomeTests(SilenceTestBase):
    def test_release_is_silent_and_keeps_the_queue_flag(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        self.sweep(T_1100 + 300)
        user = self.users.docs[0]
        self.assertFalse(user["human_takeover"]["active"])
        self.assertEqual(user["human_takeover"]["released_by"], "silence_fallback")
        self.assertEqual(user["human_takeover"]["silence_fallback_sent_at"], T_1100 + 300)
        self.assertTrue(user["live_agent_required"])
        self.assertNotIn("handoff_callback_sent_at", user)
        self.assertNotIn("awaiting_rating", user)
        # Exactly one WhatsApp message: the callback form. No reconnect line, no rating.
        self.flow.assert_called_once()
        self.text.assert_not_called()
        self.note.assert_called_once_with(PHONE, hs.SILENCE_NOTE, "kisna")
        self.assertEqual(hs.SILENCE_NOTE, "No agent reply in 5 min, callback form sent, chat returned to bot.")
        self.publish.assert_awaited_with(PHONE, {"type": "release", "phone_number": PHONE})

    def test_pending_callback_today_no_form_but_released(self):
        self.pending = {"status": "pending", "preferred_date": "2026-10-06"}
        self.users.docs.append(_user(T_1100, waiting=True))
        self.assertEqual(self.sweep(T_1100 + 300), 1)
        self.flow.assert_not_called()
        self.text.assert_not_called()
        self.assertFalse(self.takeover["active"])
        self.assertFalse(self.takeover["silence_form_sent"])
        self.note.assert_called_once_with(PHONE, hs.SILENCE_NOTE_BOOKED, "kisna")

    def test_fires_once_across_repeated_sweeps(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        results = [self.sweep(T_1100 + 300 + 60 * i) for i in range(5)]
        self.assertEqual(results, [1, 0, 0, 0, 0])
        self.flow.assert_called_once()

    def test_new_takeover_gets_a_new_clock(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        self.sweep(T_1100 + 300)
        # Agent takes over again at 11:30: set_takeover replaces the subdocument.
        self.users.docs[0]["human_takeover"] = _user(T_1100 + 1800, waiting=True)["human_takeover"]
        self.assertEqual(self.sweep(T_1100 + 1800 + 299), 0)
        self.assertEqual(self.sweep(T_1100 + 1800 + 300), 1)
        self.assertEqual(self.flow.call_count, 2)

    def test_after_hours_variant_at_19_00(self):
        self.users.docs.append(_user(T_1900, waiting=True))
        self.sweep(T_1900 + 300)
        self.flow.assert_called_once_with(PHONE, hs.CALLBACK_PREFORM)

    def test_in_hours_variant_at_11_00(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        self.sweep(T_1100 + 300)
        self.flow.assert_called_once_with(PHONE, hs._FALLBACK_TEXT)

    def test_takeover_from_before_the_deploy_is_ignored(self):
        user = _user(T_1100, waiting=True)
        user["human_takeover"].pop("tracks_silence")
        self.users.docs.append(user)
        self.assertEqual(self.sweep(T_1100 + 3600), 0)
        self.flow.assert_not_called()


class AgentReplyRaceTests(SilenceTestBase):
    """An agent reply landing at 4:59 -- after the sweep picked the chat --
    must stop the apology."""

    def _agent_replies_now(self):
        self.users.docs[0]["human_takeover"]["agent_replied_at"] = self.now

    def test_reply_between_selection_and_claim(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        selected = self.users.find({})[0]  # the sweep's (stale) copy
        self._agent_replies_now()
        self.now = T_1100 + 300
        self.assertFalse(asyncio.run(hs._process_one_silent_takeover(selected, self.now)))
        self.flow.assert_not_called()
        self.assertTrue(self.takeover["active"])

    def test_reply_between_claim_and_send(self):
        self.users.docs.append(_user(T_1100, waiting=True))

        def reply_then_no_booking(_q):
            self._agent_replies_now()  # lands after the claim, before the send
            return None

        with patch.object(hs.callback_requests, "find_one", side_effect=reply_then_no_booking):
            self.assertEqual(self.sweep(T_1100 + 300), 0)
        self.flow.assert_not_called()
        self.text.assert_not_called()
        self.note.assert_not_called()
        self.assertTrue(self.takeover["active"])
        self.assertNotIn("silence_claim_at", self.takeover)
        self.assertNotIn("silence_fallback_attempts", self.takeover)
        # And it never fires later either.
        self.assertEqual(self.sweep(T_1100 + 900), 0)
        self.flow.assert_not_called()


class FailureTests(SilenceTestBase):
    def test_send_failure_keeps_takeover_and_retries_at_most_3_times(self):
        self.flow.side_effect = RuntimeError("Gupshup 500")
        self.text.side_effect = RuntimeError("Gupshup 500")
        self.users.docs.append(_user(T_1100, waiting=True))
        for i in range(5):
            self.assertEqual(self.sweep(T_1100 + 300 + 60 * i), 0)
        self.assertTrue(self.takeover["active"])
        self.assertNotIn("silence_fallback_sent_at", self.takeover)
        self.assertEqual(self.takeover["silence_fallback_attempts"], 3)
        self.assertEqual(self.flow.call_count, 3)
        self.note.assert_not_called()

    def test_closed_window_is_a_failure_not_a_release(self):
        user = _user(T_1100, waiting=True)
        user["last_inbound_at"] = T_1100 - 25 * 3600
        self.users.docs.append(user)
        self.assertEqual(self.sweep(T_1100 + 300), 0)
        self.flow.assert_not_called()
        self.assertTrue(self.takeover["active"])
        self.assertEqual(self.takeover["silence_fallback_attempts"], 1)

    def test_retry_succeeds_on_next_sweep(self):
        self.flow.side_effect = [RuntimeError("Gupshup 500"), {"status": "submitted"}]
        self.text.side_effect = RuntimeError("Gupshup 500")
        self.users.docs.append(_user(T_1100, waiting=True))
        self.assertEqual(self.sweep(T_1100 + 300), 0)
        self.assertEqual(self.sweep(T_1100 + 360), 1)
        self.assertFalse(self.takeover["active"])


class F10InteractionTests(SilenceTestBase):
    """F10 must not send a second form to the chat F12 just released (its
    live_agent_required is still set), but must for a NEW request."""

    def _f10(self, at):
        self.now = at
        with patch.object(hs, "_fallback_kind", return_value=hs.FALLBACK):
            return asyncio.run(hs._process_one_handoff(copy.deepcopy(self.users.docs[0]), at))

    def test_no_second_form_from_f10(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        self.sweep(T_1100 + 300)
        self.assertFalse(hs._eligible_for_fallback(self.users.docs[0]))
        self.assertFalse(self._f10(T_1100 + 900))
        self.flow.assert_called_once()

    def test_new_request_after_release_is_eligible_again(self):
        self.users.docs.append(_user(T_1100, waiting=True))
        self.sweep(T_1100 + 300)
        self.users.docs[0]["live_agent_requested_at"] = T_1100 + 1200  # customer asks again
        self.assertTrue(hs._eligible_for_fallback(self.users.docs[0]))

    def test_f10_query_excludes_the_released_chat(self):
        query = {}
        find = MagicMock()
        find.sort.return_value.limit.return_value = []
        with patch.object(hs.users, "find", return_value=find) as find_mock:
            asyncio.run(hs._sweep_callback_fallback(25))
            query = find_mock.call_args[0][0]
        self.assertIn("$nor", query)


class AgentReplyMarkerTests(unittest.TestCase):
    def test_only_agent_typed_messages_set_agent_replied_at(self):
        from kisna_chatbot.database import db_utils

        with patch.object(db_utils, "users") as users, patch.object(db_utils, "dual_write_chat_entries", return_value=["id"]):
            db_utils.save_agent_message(PHONE, "You are now connected to a live support agent. Please hold on.")
            self.assertEqual(users.update_one.call_count, 1)  # chat_history push only
            db_utils.save_agent_message(PHONE, "Hi, how can I help?", from_agent=True)
            self.assertEqual(users.update_one.call_count, 3)
            filt, upd = users.update_one.call_args[0]
            self.assertEqual(filt["human_takeover.active"], True)
            self.assertEqual(filt["human_takeover.agent_replied_at"], {"$exists": False})
            self.assertIn("human_takeover.agent_replied_at", upd["$set"])

    def test_customer_waiting_at_takeover(self):
        from kisna_chatbot.database.db_utils import customer_waiting_at_takeover as w

        self.assertTrue(w({"live_agent_required": True}))
        self.assertTrue(w({"chat_history": [{"role": "assistant"}, {"role": "user"}]}))
        self.assertFalse(w({"chat_history": [{"role": "user"}, {"role": "assistant"}]}))
        self.assertFalse(w({}))

    def test_set_takeover_records_waiting_and_tracking(self):
        from kisna_chatbot.database import db_utils

        with patch.object(db_utils, "users") as users:
            db_utils.set_takeover(PHONE, True, waiting=True)
        takeover = users.update_one.call_args[0][1]["$set"]["human_takeover"]
        self.assertTrue(takeover["tracks_silence"])
        self.assertTrue(takeover["waiting_at_start"])


class ReleasedChatGetsBotReplyTests(unittest.TestCase):
    def test_next_customer_message_runs_the_bot(self):
        from kisna_chatbot import main as main_mod

        released = {"active": False, "released_by": "silence_fallback", "silence_fallback_sent_at": T_1100 + 300}
        request_data = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "850788844795304"},
            "contacts": [{"profile": {"name": "Test"}}],
            "messages": [{"from": PHONE, "id": "wamid.silence.test", "type": "text", "text": {"body": "hello?"}}],
        }}]}]}

        async def _run():
            with (
                patch.object(main_mod, "mark_inbound_processed", return_value=True),
                patch.object(main_mod, "get_takeover_status", return_value=released),
                patch.object(main_mod, "save_user_message_silent") as silent,
                patch.object(main_mod, "UserRegistration") as reg_cls,
                patch.object(main_mod, "InitialPipeline") as initial,
                patch.object(main_mod, "save_to_mongo"),
                patch.object(main_mod, "save_response_time"),
                patch.object(main_mod.ResponseManager, "handle_responses"),
            ):
                # Past the takeover gate the first step is UserRegistration:
                # reaching it means the bot pipeline runs. Stop there.
                class _ReachedPipeline(Exception):
                    pass

                reg = MagicMock()
                reg.process = AsyncMock(side_effect=_ReachedPipeline)
                reg_cls.return_value = reg
                try:
                    await main_mod.process_message(request_data, app_state=None)
                except _ReachedPipeline:
                    pass
                initial.assert_not_called()
                silent.assert_not_called()
                reg.process.assert_awaited()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
