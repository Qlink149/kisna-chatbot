"""Quick replies: the dashboard API (list / create / update / soft delete /
reorder), validation messages, the 50 cap and who-changed-what. In-memory
collection; the session dependency is overridden like StoresAdminRouteTests."""

import copy
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from pymongo.errors import DuplicateKeyError  # noqa: E402

from kisna_chatbot import quick_replies as qr  # noqa: E402


def _match(doc, query):
    for k, v in (query or {}).items():
        if isinstance(v, dict) and "$ne" in v:
            if doc.get(k) == v["$ne"]:
                return False
        elif doc.get(k) != v:
            return False
    return True


class _Cursor(list):
    def sort(self, keys):
        for key, direction in reversed(keys):
            super().sort(key=lambda d: d.get(key, 0), reverse=direction < 0)
        return self


class FakeQuickReplies:
    """Just the pymongo surface quick_replies.py uses, plus the partial unique
    index on (client_id, title_lower) for active replies."""

    def __init__(self):
        self.docs = []

    def find(self, query=None, projection=None):
        return _Cursor(copy.deepcopy(d) for d in self.docs if _match(d, query))

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query)
        if sort:
            rows.sort(sort)
        return rows[0] if rows else None

    def count_documents(self, query):
        return sum(1 for d in self.docs if _match(d, query))

    def _check_unique(self, doc, skip=None):
        if not doc.get("active"):
            return
        for d in self.docs:
            if d is not skip and d.get("active") and d["client_id"] == doc["client_id"] and d["title_lower"] == doc["title_lower"]:
                raise DuplicateKeyError("uniq_quick_reply_active_title")

    def insert_one(self, doc):
        self._check_unique(doc)
        self.docs.append(copy.deepcopy(doc))

    def update_one(self, query, update):
        for d in self.docs:
            if _match(d, query):
                new = {**d, **update.get("$set", {})}
                self._check_unique(new, skip=d)
                d.update(update.get("$set", {}))
                for k, v in update.get("$push", {}).items():
                    d.setdefault(k, []).append(v)
                return


class QuickRepliesApiTests(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from kisna_chatbot.routes.dependencies.system_dependencies import verify_session
        from kisna_chatbot.routes.system_sub_routes import quick_replies as route

        self.col = FakeQuickReplies()
        self._p = patch.object(qr, "_collection", lambda collection=None: self.col)
        self._p.start()
        self.user = "agent1"
        app = FastAPI()
        app.include_router(route.router)
        app.dependency_overrides[verify_session] = lambda: {"username": self.user, "role": "agent"}
        self.client = TestClient(app)

    def tearDown(self):
        self._p.stop()

    def _create(self, title="Store hours", body="Hi {name}, our stores open at 10:30 AM."):
        return self.client.post("/quick-replies", json={"title": title, "body": body})

    # --- list / create -------------------------------------------------------
    def test_create_then_list_in_order(self):
        for t in ("Store hours", "Delivery time", "Return policy"):
            self.assertEqual(self._create(title=t).status_code, 201)
        resp = self.client.get("/quick-replies")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual([r["title"] for r in body["data"]], ["Store hours", "Delivery time", "Return policy"])
        self.assertEqual([r["sort_order"] for r in body["data"]], [0, 1, 2])
        self.assertEqual((body["total"], body["max"]), (3, 50))
        self.assertEqual(set(body["data"][0]), set(qr._PUBLIC_FIELDS))

    def test_create_trims_and_records_who(self):
        item = self._create(title="  Store hours  ", body="  Open 10:30 AM.  ").json()
        self.assertEqual((item["title"], item["body"]), ("Store hours", "Open 10:30 AM."))
        self.assertEqual((item["created_by"], item["updated_by"]), ("agent1", "agent1"))
        self.assertEqual(self.col.docs[0]["history"][0]["action"], "create")
        self.assertEqual(self.col.docs[0]["history"][0]["by"], "agent1")

    def test_validation_messages(self):
        cases = [
            ({"title": "", "body": "x"}, "Title is required"),
            ({"title": "   ", "body": "x"}, "Title is required"),
            ({"title": "x" * 41, "body": "x"}, "Title must be 40 characters or fewer (got 41)"),
            ({"title": "ok", "body": ""}, "Message is required"),
            ({"title": "ok", "body": "x" * 1025}, "Message must be 1,024 characters or fewer (got 1,025)"),
            ({}, "Title is required; Message is required"),
        ]
        for payload, message in cases:
            with self.subTest(payload=str(payload)[:40]):
                resp = self.client.post("/quick-replies", json=payload)
                self.assertEqual(resp.status_code, 422)
                self.assertEqual(resp.json()["detail"], message)
        self.assertEqual(self._create(title="x" * 40, body="y" * 1024).status_code, 201)  # limits inclusive

    def test_duplicate_title_is_case_insensitive(self):
        self._create(title="Store hours")
        resp = self._create(title="STORE HOURS")
        self.assertEqual(resp.status_code, 422)
        self.assertEqual(resp.json()["detail"], "A quick reply titled “STORE HOURS” already exists")

    def test_at_most_50_active(self):
        for i in range(50):
            self.assertEqual(self._create(title=f"Reply {i}").status_code, 201)
        resp = self._create(title="Reply 50")
        self.assertEqual(resp.status_code, 422)
        self.assertIn("at most 50 quick replies", resp.json()["detail"])

    def test_unknown_fields_are_refused(self):
        self.assertEqual(self.client.post("/quick-replies", json={"title": "a", "body": "b", "active": False}).status_code, 422)

    # --- update ----------------------------------------------------------------
    def test_update_records_the_editor_and_fields(self):
        rid = self._create().json()["id"]
        self.user = "agent2"
        resp = self.client.patch(f"/quick-replies/{rid}", json={"body": "New text"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()["body"], resp.json()["updated_by"], resp.json()["created_by"]), ("New text", "agent2", "agent1"))
        last = self.col.docs[0]["history"][-1]
        self.assertEqual((last["action"], last["by"], last["fields"]), ("update", "agent2", ["body"]))

    def test_update_validation_duplicate_and_404(self):
        self._create(title="Store hours")
        rid = self._create(title="Delivery").json()["id"]
        self.assertEqual(self.client.patch(f"/quick-replies/{rid}", json={"title": "store hours"}).status_code, 422)
        self.assertEqual(self.client.patch(f"/quick-replies/{rid}", json={"title": ""}).json()["detail"], "Title is required")
        self.assertEqual(self.client.patch(f"/quick-replies/{rid}", json={}).json()["detail"], "Nothing to update")
        self.assertEqual(self.client.patch("/quick-replies/nope", json={"body": "x"}).status_code, 404)
        # Renaming to its own title with different case is allowed.
        self.assertEqual(self.client.patch(f"/quick-replies/{rid}", json={"title": "DELIVERY"}).status_code, 200)

    # --- delete ----------------------------------------------------------------
    def test_soft_delete_hides_it_and_frees_the_title(self):
        rid = self._create(title="Store hours").json()["id"]
        resp = self.client.delete(f"/quick-replies/{rid}")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(self.client.get("/quick-replies").json()["total"], 0)
        doc = self.col.docs[0]
        self.assertEqual((doc["active"], doc["deleted_by"]), (False, "agent1"))
        self.assertEqual(self.client.delete(f"/quick-replies/{rid}").status_code, 404)
        self.assertEqual(self._create(title="Store hours").status_code, 201)

    # --- reorder ---------------------------------------------------------------
    def test_reorder(self):
        ids = [self._create(title=t).json()["id"] for t in ("A", "B", "C")]
        resp = self.client.put("/quick-replies/order", json={"ids": [ids[2], ids[0], ids[1]]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([r["title"] for r in resp.json()["data"]], ["C", "A", "B"])
        self.assertEqual([r["title"] for r in self.client.get("/quick-replies").json()["data"]], ["C", "A", "B"])

    def test_reorder_must_list_every_reply_once(self):
        ids = [self._create(title=t).json()["id"] for t in ("A", "B")]
        for bad in ([ids[0]], [ids[0], ids[0]], [ids[0], ids[1], "x"], []):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.put("/quick-replies/order", json={"ids": bad}).status_code, 422)

    def test_new_reply_goes_last_after_reorder(self):
        ids = [self._create(title=t).json()["id"] for t in ("A", "B")]
        self.client.put("/quick-replies/order", json={"ids": [ids[1], ids[0]]})
        self._create(title="C")
        self.assertEqual([r["title"] for r in self.client.get("/quick-replies").json()["data"]], ["B", "A", "C"])


class MountTests(unittest.TestCase):
    """Served under /system and behind the dashboard session."""

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from kisna_chatbot.routes import system

        self._p = patch.object(qr, "_collection", lambda collection=None: FakeQuickReplies())
        self._p.start()
        self.app = FastAPI()
        self.app.include_router(system.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self._p.stop()

    def test_needs_a_session(self):
        self.assertIn(self.client.get("/system/quick-replies").status_code, (401, 403))

    def test_mounted_under_system(self):
        from kisna_chatbot.routes.dependencies.system_dependencies import verify_session

        self.app.dependency_overrides[verify_session] = lambda: {"username": "agent1", "role": "agent"}
        resp = self.client.get("/system/quick-replies")
        self.assertEqual((resp.status_code, resp.json()["total"]), (200, 0))


if __name__ == "__main__":
    unittest.main()
