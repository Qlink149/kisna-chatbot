"""scripts/backfill_store_visit_events.py: push store visits whose Salesforce
status is "Not sent" once the event push is on; idempotent on request ID."""

import asyncio
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backfill_store_visit_events as backfill  # noqa: E402

from kisna_chatbot.processors.store_visit_agent import SOURCE, store_visit_event_from_doc  # noqa: E402


class Cursor(list):
    def sort(self, *a, **k):
        return self


class Coll:
    """Just enough of a collection: equality, $in and $type string."""

    def __init__(self, docs):
        self.docs = docs

    def _ok(self, d, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$in" in v:
                if d.get(k) not in v["$in"]:
                    return False
            elif isinstance(v, dict) and "$type" in v:
                if not isinstance(d.get(k), str):
                    return False
            elif d.get(k) != v:
                return False
        return True

    def find(self, q, projection=None):
        return Cursor([dict(d) for d in self.docs if self._ok(d, q)])


def _visit(rid, created):
    return {
        "request_id": rid, "client_id": "kisna", "source": SOURCE, "created_at": created,
        "phone_number": "919812345678", "first_name": "Priya", "last_name": "S", "email": "",
        "mobile": "919812345678", "looking_for": "gold_jewellery", "looking_for_label": "Gold Jewellery",
        "store": {"store_id": "D1", "name": "Karol Bagh", "address": "Road", "city": "Delhi-NCR",
                  "state": "Delhi", "pincode": "110005"},
        "preferred_date": "2026-10-01", "preferred_time": "11:00", "preferred_time_label": "11:00 AM",
    }


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.visits = Coll(
            [
                _visit("KIS-SV-1", 1),
                _visit("KIS-SV-2", 2),
                _visit("KIS-SV-3", 3),
                {"request_id": None, "source": "legacy", "client_id": "kisna"},  # legacy row
            ]
        )
        self.events = Coll([{"event_id": "KIS-SV-2", "status": "sent"}])

    def test_selects_only_unsent_flow_bookings(self):
        rows = backfill.find_unsent(self.visits, self.events, client_id="kisna", limit=None)
        self.assertEqual([r["request_id"] for r in rows], ["KIS-SV-1", "KIS-SV-3"])
        rows = backfill.find_unsent(self.visits, self.events, client_id="kisna", limit=1)
        self.assertEqual([r["request_id"] for r in rows], ["KIS-SV-1"])

    def _main(self, argv, *, sv_on=True, clara_on=True):
        out = io.StringIO()
        with patch("kisna_chatbot.database.collections.store_visits", self.visits), patch(
            "kisna_chatbot.database.collections.clara_events", self.events
        ), patch("kisna_chatbot.config.store_visit.store_visit_events_enabled", return_value=sv_on), patch(
            "kisna_chatbot.integrations.clara_events.is_enabled", return_value=clara_on
        ), patch.object(backfill, "push", return_value={"sent": 2}) as push, redirect_stdout(out):
            code = backfill.main(argv)
        return code, out.getvalue(), push

    def test_dry_run_lists_and_sends_nothing(self):
        code, out, push = self._main(["--dry-run"], sv_on=False, clara_on=False)
        self.assertEqual(code, 0)
        self.assertIn("2 store visit(s)", out)
        self.assertIn("KIS-SV-1", out)
        self.assertIn("KIS-SV-3", out)
        self.assertNotIn("KIS-SV-2", out)
        push.assert_not_called()

    def test_refuses_while_push_is_off(self):
        code, out, push = self._main([], sv_on=False)
        self.assertEqual(code, 2)
        self.assertIn("KISNA_STORE_VISIT_EVENTS_ENABLED", out)
        push.assert_not_called()
        code, out, push = self._main([], clara_on=False)
        self.assertEqual(code, 2)
        self.assertIn("KISNA_CLARA_EVENTS_ENABLED", out)

    def test_sends_when_on(self):
        code, _, push = self._main([])
        self.assertEqual(code, 0)
        self.assertEqual([r["request_id"] for r in push.call_args[0][0]], ["KIS-SV-1", "KIS-SV-3"])

    def test_push_enqueues_the_live_payload_keyed_on_request_id(self):
        from kisna_chatbot.integrations import clara_events as outbox

        rows = backfill.find_unsent(self.visits, self.events, client_id="kisna", limit=None)
        with patch.object(outbox, "enqueue_event", new_callable=AsyncMock) as enqueue, patch.object(
            outbox, "_events", self.events
        ):
            asyncio.run(backfill.push(rows))
        payloads = [c.args[0] for c in enqueue.call_args_list]
        self.assertEqual([p["event_id"] for p in payloads], ["KIS-SV-1", "KIS-SV-3"])
        self.assertEqual(payloads[0], store_visit_event_from_doc(rows[0]))
        self.assertEqual(payloads[0]["event_type"], "store_visit_requested")

    def test_rerun_after_send_selects_nothing(self):
        self.events.docs += [{"event_id": "KIS-SV-1", "status": "sent"}, {"event_id": "KIS-SV-3", "status": "pending"}]
        self.assertEqual(backfill.find_unsent(self.visits, self.events, client_id="kisna", limit=None), [])


if __name__ == "__main__":
    unittest.main()
