"""kisna.com store sync + dashboard overrides (store visit follow-up, item 4).

Mongo is an in-memory fake that applies the same UpdateOne operations the
code sends, so the tests check what actually ends up stored.
"""

import asyncio
import copy
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.stores import model, repo  # noqa: E402
from kisna_chatbot.stores import sync as store_sync  # noqa: E402
from kisna_chatbot.utils.support_hours import IST  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = [copy.deepcopy(d) for d in (docs or [])]
        self.writes = 0

    @staticmethod
    def _match(doc, query):
        return all(doc.get(k) == v for k, v in (query or {}).items())

    def find(self, query=None, projection=None):
        return FakeCursor([copy.deepcopy(d) for d in self.docs if self._match(d, query)])

    def find_one(self, query=None, projection=None, sort=None):
        rows = [d for d in self.docs if self._match(d, query)]
        if sort:
            key, direction = sort[0]
            rows.sort(key=lambda d: d.get(key, 0), reverse=direction < 0)
        return copy.deepcopy(rows[0]) if rows else None

    def insert_one(self, doc):
        self.writes += 1
        self.docs.append(copy.deepcopy(doc))

    def find_one_and_update(self, query, update, projection=None, return_document=None):
        self.writes += 1
        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return copy.deepcopy(d)
        return None

    def bulk_write(self, ops, ordered=False):
        self.writes += 1
        for op in ops:
            q, u, upsert = op._filter, op._doc, op._upsert
            hit = next((d for d in self.docs if self._match(d, q)), None)
            if hit is None:
                if upsert:
                    new = dict(q)
                    new.update(u.get("$setOnInsert", {}))
                    new.update(u.get("$set", {}))
                    self.docs.append(new)
                continue
            hit.update(u.get("$set", {}))


class FakeCursor(list):
    def sort(self, *a, **k):
        return self


def _raw(bc, name, city="Amritsar", state="Punjab", line1="Mall Road", pincode="143001", active=True):
    hours = {d: {"from": "10:30", "to": "20:00", "status": "open"} for d in model.WEEKDAYS}
    return {
        "_id": f"id-{bc}", "branchCode": bc, "name": name, "phone": "999", "active": active,
        "status": "active" if active else "inactive",
        # The live API's nested shape (the seed file flattens these to names).
        "address": {
            "line1": line1,
            "city": {"_id": f"c-{city}", "name": city},
            "state": {"_id": f"s-{state}", "name": state},
            "pincode": pincode,
        },
        "storeHours": hours,
        "gstIn": "SHOULD-NOT-BE-STORED", "insuraceKey": "x", "invoiceName": "y",
    }


def _api(rows):
    return {"data": {"data": rows, "totalCount": len(rows)}, "status": 200}


class SyncFixture(unittest.TestCase):
    def setUp(self):
        self.stores = FakeCollection()
        self.runs = FakeCollection()
        self._p = patch.object(store_sync, "_collections", return_value=(self.stores, self.runs))
        self._p.start()
        self._bust = patch.object(store_sync.cache, "bust")
        self._bust.start()

    def tearDown(self):
        self._p.stop()
        self._bust.stop()

    def sync(self, rows=None, *, fetch=None, now=1_000_000):
        async def ok():
            return store_sync.parse_response(_api(rows))

        return asyncio.run(store_sync.run_sync(trigger="test", fetch=fetch or ok, now=now))

    def store(self, sid):
        return next(d for d in self.stores.docs if d["store_id"] == sid)


class SyncTests(SyncFixture):
    def test_first_sync_creates_stores_with_defaults(self):
        run = self.sync([_raw("A1", "Mall Road - Amritsar - Punjab"), _raw("B1", "Sector 17", "chandigarh", "chandigarh")])
        self.assertEqual(run["status"], "ok")
        self.assertEqual(run["counts"], {"added": 2, "updated": 0, "deactivated": 0, "reactivated": 0})
        b = self.store("B1")
        self.assertEqual((b["city"], b["state"]), ("Chandigarh", "Chandigarh"))
        self.assertTrue(b["bookable"] and b["active"])
        self.assertEqual((b["open_time"], b["close_time"], b["weekly_off"]), ("10:30", "20:00", []))
        for banned in ("gstIn", "insuraceKey", "invoiceName", "_id", "storeHours"):
            self.assertNotIn(banned, b)
        self.assertEqual(len(self.runs.docs), 1)

    def test_new_store_bookable_from_config(self):
        with patch.dict(os.environ, {"KISNA_NEW_STORE_BOOKABLE_DEFAULT": "false"}):
            self.sync([_raw("A1", "Store A")])
        self.assertFalse(self.store("A1")["bookable"])

    def test_overrides_survive_a_sync_and_synced_fields_are_overwritten(self):
        self.sync([_raw("A1", "Store A")])
        a = self.store("A1")
        a.update(bookable=False, open_time="12:00", close_time="18:00", weekly_off=["tuesday"])
        run = self.sync([_raw("A1", "Store A Renamed", line1="New Road", pincode="143002")])
        a = self.store("A1")
        self.assertEqual((a["name"], a["address"], a["pincode"]), ("Store A Renamed", "New Road", "143002"))
        self.assertEqual(
            (a["bookable"], a["open_time"], a["close_time"], a["weekly_off"]),
            (False, "12:00", "18:00", ["tuesday"]),
        )
        self.assertEqual(run["counts"]["updated"], 1)
        self.assertEqual(run["changes"]["updated"], ["A1"])

    def test_removed_store_deactivated_then_reactivated_keeping_overrides(self):
        self.sync([_raw(c, f"S{c}") for c in ("A1", "A2", "A3", "A4", "A5")])
        self.store("A5").update(open_time="11:00", bookable=False)
        run = self.sync([_raw(c, f"S{c}") for c in ("A1", "A2", "A3", "A4")])
        self.assertEqual(run["counts"]["deactivated"], 1)
        self.assertFalse(self.store("A5")["active"])
        self.assertEqual(len(self.stores.docs), 5)  # never deleted
        run = self.sync([_raw(c, f"S{c}") for c in ("A1", "A2", "A3", "A4", "A5")])
        self.assertEqual(run["counts"]["reactivated"], 1)
        a5 = self.store("A5")
        self.assertTrue(a5["active"])
        self.assertEqual((a5["open_time"], a5["bookable"]), ("11:00", False))

    def test_inactive_in_api_counts_as_removed(self):
        self.sync([_raw("A1", "S1"), _raw("A2", "S2"), _raw("A3", "S3"), _raw("A4", "S4"), _raw("A5", "S5")])
        run = self.sync([_raw("A1", "S1"), _raw("A2", "S2"), _raw("A3", "S3"), _raw("A4", "S4"), _raw("A5", "S5", active=False)])
        self.assertEqual(run["counts"]["deactivated"], 1)

    def test_80_percent_guard_aborts_without_writing(self):
        self.sync([_raw(f"A{i}", f"S{i}") for i in range(10)])
        writes = self.stores.writes
        run = self.sync([_raw(f"A{i}", f"S{i}") for i in range(7)])  # 70% of 10
        self.assertEqual(run["status"], "aborted")
        self.assertIn("< 80%", run["reason"])
        self.assertEqual(self.stores.writes, writes)
        self.assertTrue(all(d["active"] for d in self.stores.docs))
        self.assertEqual(self.runs.docs[-1]["status"], "aborted")
        # 8 of 10 is allowed.
        self.assertEqual(self.sync([_raw(f"A{i}", f"S{i}") for i in range(8)])["status"], "ok")

    def test_failed_fetch_aborts(self):
        async def boom():
            raise store_sync.SyncAbort("fetch failed: ConnectTimeout")

        self.sync([_raw("A1", "S1")])
        writes = self.stores.writes
        run = self.sync(fetch=boom)
        self.assertEqual(run["status"], "aborted")
        self.assertEqual(self.stores.writes, writes)
        self.assertEqual(self.runs.docs[-1]["reason"], "fetch failed: ConnectTimeout")

    def test_malformed_responses_abort(self):
        for body in ({"data": []}, {"nope": 1}, {"data": {"data": "x"}}, {"data": {"data": [_raw("A1", "S1")], "totalCount": 50}}):
            with self.assertRaises(store_sync.SyncAbort, msg=body):
                store_sync.parse_response(body)

        async def bad():
            return store_sync.parse_response({"data": {"items": []}})

        run = self.sync(fetch=bad)
        self.assertEqual(run["status"], "aborted")
        self.assertEqual(self.stores.docs, [])

    def test_empty_response_aborts_even_on_empty_collection(self):
        run = self.sync([])
        self.assertEqual(run["status"], "aborted")

    def test_http_error_becomes_abort(self):
        import httpx

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return httpx.Response(503, request=httpx.Request("GET", "https://x"))

        with patch.object(store_sync.httpx, "AsyncClient", FakeClient):
            with self.assertRaises(store_sync.SyncAbort):
                asyncio.run(store_sync.fetch_raw())

    def test_catch_up_due_after_26_hours(self):
        self.assertTrue(store_sync.catch_up_due(now=1_000_000))  # never ran
        self.sync([_raw("A1", "S1")], now=1_000_000)
        self.assertFalse(store_sync.catch_up_due(now=1_000_000 + 25 * 3600))
        self.assertTrue(store_sync.catch_up_due(now=1_000_000 + 27 * 3600))
        # A later ABORTED run does not count as a successful sync.
        self.runs.docs.append({"status": "aborted", "started_at": 1_000_000 + 26 * 3600})
        self.assertTrue(store_sync.catch_up_due(now=1_000_000 + 27 * 3600))

    def test_restart_runs_catch_up_then_waits_for_0200(self):
        calls = []

        async def fake_run(**kw):
            calls.append(kw["trigger"])
            return {}

        async def stop(_seconds):
            raise asyncio.CancelledError

        with patch.object(store_sync, "run_sync", side_effect=fake_run), patch.object(
            store_sync, "catch_up_due", return_value=True
        ), patch.object(store_sync.asyncio, "sleep", side_effect=stop):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(store_sync.sync_loop())
        self.assertEqual(calls, ["startup_catch_up"])

    def test_next_run_is_0200_ist(self):
        self.assertEqual(store_sync.seconds_until_next_run(datetime(2026, 9, 28, 1, 0, tzinfo=IST)), 3600)
        self.assertEqual(store_sync.seconds_until_next_run(datetime(2026, 9, 28, 2, 0, tzinfo=IST)), 86400)
        self.assertEqual(store_sync.seconds_until_next_run(datetime(2026, 9, 28, 23, 0, tzinfo=IST)), 3 * 3600)

    def test_first_sync_on_empty_collection_matches_the_seed(self):
        with open(os.path.join(ROOT, "data", "stores_seed.json"), encoding="utf-8") as f:
            seed_raw = json.load(f)["stores"]
        run = self.sync(seed_raw)
        self.assertEqual(run["counts"]["added"], 170)
        seed = {s["store_id"]: s for s in (model.from_kisna_record(r) for r in seed_raw)}
        self.assertEqual(set(seed), {d["store_id"] for d in self.stores.docs})
        fields = model.SYNCED_FIELDS + ("open_time", "close_time", "weekly_off", "bookable", "active")
        for d in self.stores.docs:
            self.assertEqual({f: d[f] for f in fields}, {f: seed[d["store_id"]][f] for f in fields}, d["store_id"])


# ------------------------------------------------------------- CSV / API
class OverrideCsvTests(unittest.TestCase):
    def setUp(self):
        self.col = FakeCollection(
            [
                {"store_id": "S1", "name": "Andheri West", "address": "Link Road", "city": "Mumbai",
                 "state": "Maharashtra", "pincode": "400053", "phone": "", "open_time": "10:30",
                 "close_time": "20:00", "weekly_off": [], "bookable": True, "active": True},
                {"store_id": "S2", "name": "Bandra", "address": "Hill Road", "city": "Mumbai",
                 "state": "Maharashtra", "pincode": "400050", "phone": "", "open_time": "10:30",
                 "close_time": "20:00", "weekly_off": [], "bookable": True, "active": True},
            ]
        )
        self._bust = patch.object(repo.cache, "bust")
        self._bust.start()

    def tearDown(self):
        self._bust.stop()

    def test_overrides_only_file_applies(self):
        csv_text = "store_id,bookable,open_time,close_time,weekly_off\nS1,false,12:00,18:00,tue;sun\nS2,,,,\n"
        result = repo.import_csv(csv_text, collection=self.col)
        self.assertTrue(result["ok"], result)
        s1 = self.col.docs[0]
        self.assertEqual(
            (s1["bookable"], s1["open_time"], s1["close_time"], s1["hours_overridden"], s1["weekly_off"]),
            (False, "12:00", "18:00", True, ["tuesday", "sunday"]),
        )
        self.assertEqual(result["updated"], 1)

    def test_shown_default_hours_do_not_pin(self):
        # 11:00-21:00 is what the dashboard shows for a store it hasn't set,
        # so sending it back changes nothing about the hours.
        csv_text = "store_id,open_time,close_time,weekly_off\nS1,11:00,21:00,sun\n"
        self.assertTrue(repo.import_csv(csv_text, collection=self.col)["ok"])
        s1 = self.col.docs[0]
        self.assertNotIn("hours_overridden", s1)
        self.assertEqual((s1["open_time"], s1["weekly_off"]), ("10:30", ["sunday"]))  # kisna.com value kept

    def test_downloaded_csv_reuploads_cleanly(self):
        text = repo.to_csv(self.col.docs)
        self.assertIn(",11:00,21:00,", text)  # the hours that set slots, not kisna.com's
        result = repo.import_csv(text, collection=self.col)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["updated"], 0)

    def test_dashboard_shows_the_hours_that_set_slots(self):
        shown = {s["store_id"]: s for s in repo.list_all(collection=self.col)}
        self.assertEqual(
            (shown["S1"]["open_time"], shown["S1"]["close_time"], shown["S1"]["hours_overridden"]),
            ("11:00", "21:00", False),
        )
        doc, errors = repo.set_overrides(
            "S1", {"open_time": "11:00", "close_time": "21:00", "weekly_off": ["tue"]}, collection=self.col
        )
        self.assertEqual(errors, [])
        self.assertFalse(doc["hours_overridden"])  # the edit form resends the shown hours
        doc, _ = repo.set_overrides("S1", {"open_time": "10:00", "close_time": "21:00"}, collection=self.col)
        self.assertEqual((doc["open_time"], doc["close_time"], doc["hours_overridden"]), ("10:00", "21:00", True))

    def test_changed_name_or_address_rejected_with_row_error(self):
        text = repo.to_csv(self.col.docs).replace("Hill Road", "Hill Road Shop 2").replace("Andheri West", "Andheri W")
        result = repo.import_csv(text, collection=self.col)
        self.assertFalse(result["ok"])
        rows = {e["row"]: e["error"] for e in result["errors"]}
        self.assertIn("name", rows[2])
        self.assertIn("can't be changed here", rows[2])
        self.assertIn("address", rows[3])
        self.assertEqual(self.col.writes, 0)  # whole file rejected

    def test_active_column_is_sync_owned(self):
        text = repo.to_csv(self.col.docs).replace("true,true", "true,false", 1)
        result = repo.import_csv(text, collection=self.col)
        self.assertFalse(result["ok"])
        self.assertIn("active is set by the kisna.com sync", result["errors"][0]["error"])

    def test_unknown_store_and_bad_values_rejected(self):
        csv_text = "store_id,open_time,close_time,weekly_off\nNEW1,11:00,21:00,\nS1,25:00,21:00,funday\nS2,20:30,21:00,\n"
        result = repo.import_csv(csv_text, collection=self.col)
        self.assertFalse(result["ok"])
        errs = {e["row"]: e["error"] for e in result["errors"]}
        self.assertIn("not found", errs[2])
        self.assertIn("open_time", errs[3])
        self.assertIn("weekday", errs[3])
        self.assertIn("at least 1 hour", errs[4])

    def test_header_checks(self):
        self.assertFalse(repo.import_csv("name,city\nx,y\n", collection=self.col)["ok"])
        self.assertIn("no override column", repo.import_csv("store_id,name\nS1,x\n", collection=self.col)["errors"][0]["error"])
        self.assertIn("unknown column", repo.import_csv("store_id,bookable,gst\nS1,true,x\n", collection=self.col)["errors"][0]["error"])

    def test_set_overrides_only_touches_override_fields(self):
        doc, errors = repo.set_overrides("S1", {"open_time": "09:30", "weekly_off": ["mon"]}, by="agent1", collection=self.col)
        self.assertEqual(errors, [])
        self.assertEqual((doc["open_time"], doc["weekly_off"], doc["overrides_updated_by"]), ("09:30", ["monday"], "agent1"))
        _, errors = repo.set_overrides("S1", {"close_time": "09:45"}, collection=self.col)
        self.assertTrue(errors)


class StoresAdminRouteTests(unittest.TestCase):
    """The dashboard API refuses synced fields and gates "Sync now" to admins."""

    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from kisna_chatbot.routes.dependencies.system_dependencies import verify_session
        from kisna_chatbot.routes.system_sub_routes import stores_admin

        cls.role = "super_admin"
        app = FastAPI()
        app.include_router(stores_admin.router)
        app.dependency_overrides[verify_session] = lambda: {"username": "agent1", "role": cls.role}
        cls.client = TestClient(app)
        cls.module = stores_admin

    def test_patch_rejects_synced_fields(self):
        resp = self.client.patch("/stores/S1", json={"name": "New name"})
        self.assertEqual(resp.status_code, 422)
        resp = self.client.patch("/stores/S1", json={"active": False})
        self.assertEqual(resp.status_code, 422)

    def test_patch_override_passes_through(self):
        with patch.object(self.module.repo, "set_overrides", return_value=({"store_id": "S1", "bookable": False}, [])) as so:
            resp = self.client.patch("/stores/S1", json={"bookable": False})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(so.call_args[0][1], {"bookable": False})
        self.assertEqual(so.call_args.kwargs["by"], "agent1")

    def test_sync_now_admin_only(self):
        async def fake_run(**kw):
            return {"status": "ok", "trigger": kw["trigger"]}

        with patch("kisna_chatbot.stores.sync.run_sync", side_effect=fake_run):
            type(self).role = "viewer"
            self.assertEqual(self.client.post("/stores/sync").status_code, 403)
            type(self).role = "super_admin"
            resp = self.client.post("/stores/sync")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["trigger"], "manual:agent1")


if __name__ == "__main__":
    unittest.main()
