"""Store Visit Flow: store model + CSV import, cache, slots, copy, the
encrypted Flow endpoint, the submission (idempotency, event contract) and
routing. Mongo is mocked; the endpoint round trip uses an in-test RSA key
pair, exactly like tests/test_flow_data_exchange.py (no key files)."""

import asyncio
import json
import os
import statistics
import time
import unittest
from base64 import b64decode, b64encode
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP  # noqa: E402
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402
from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402

from kisna_chatbot.config.store_visit import LOOKING_FOR_OPTIONS  # noqa: E402
from kisna_chatbot.processors import store_visit_agent as sva  # noqa: E402
from kisna_chatbot.processors import store_visit_flow as svf  # noqa: E402
from kisna_chatbot.processors.flow_data_exchange import build_flow_response  # noqa: E402
from kisna_chatbot.prompts import form_copy  # noqa: E402
from kisna_chatbot.stores import cache as store_cache  # noqa: E402
from kisna_chatbot.stores import model, repo  # noqa: E402
from kisna_chatbot.utils import store_visit_slots as slots  # noqa: E402
from kisna_chatbot.utils.support_hours import IST  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _store(**over):
    s = {
        "store_id": "F203",
        "name": "INA Colony - Amritsar - Punjab",
        "address": "Shop No. 3,4, JK Tower 49, Mall Road",
        "city": "Amritsar",
        "state": "Punjab",
        "pincode": "143001",
        "phone": "",
        "open_time": "10:30",
        "close_time": "20:00",
        "weekly_off": [],
        "bookable": True,
        "active": True,
    }
    s.update(over)
    return s


STORES = [
    _store(),
    _store(store_id="D1", name="Karol Bagh - Delhi-NCR - Delhi", city="Delhi-NCR", state="Delhi",
           address="Ajmal Khan Road", pincode="110005"),
    _store(store_id="D2", name="Rajouri Garden - Delhi-NCR - Delhi", city="Delhi-NCR", state="Delhi",
           address="Main Market", pincode="110027", weekly_off=["tuesday"]),
]

# Wed 2026-09-30 09:00 IST: a normal day, well inside the store hours.
NOW = datetime(2026, 9, 30, 9, 0, tzinfo=IST)


class CacheFixture(unittest.TestCase):
    """Serve STORES from the cache without Mongo."""

    rows = STORES

    def setUp(self):
        store_cache.bust()
        self._p = patch.object(store_cache, "_load", side_effect=lambda: list(self.rows))
        self.load = self._p.start()

    def tearDown(self):
        self._p.stop()
        store_cache.bust()


# ---------------------------------------------------------------- model
class ModelTests(unittest.TestCase):
    def test_kisna_record_normalised(self):
        raw = {
            "_id": "x", "branchCode": "F203", "name": " INA Colony - Amritsar - Punjab ",
            "phone": "999", "active": True, "status": "active",
            "address": {"line1": "Shop  3,  Mall Road", "city": "amritsar", "state": "Chattisgarh", "pincode": "143001"},
            "storeHours": {d: {"from": "10:30", "to": "20:00", "status": "open"} for d in model.WEEKDAYS[:6]}
            | {"sunday": {"from": "", "to": "", "status": "close"}},
        }
        s = model.from_kisna_record(raw)
        self.assertEqual(s["store_id"], "F203")
        self.assertEqual(s["address"], "Shop 3, Mall Road")
        self.assertEqual(s["city"], "Amritsar")
        self.assertEqual(s["state"], "Chhattisgarh")
        self.assertEqual((s["open_time"], s["close_time"]), ("10:30", "20:00"))
        self.assertEqual(s["weekly_off"], ["sunday"])
        self.assertTrue(s["active"] and s["bookable"])

    def test_missing_hours_default(self):
        s = model.from_kisna_record({"branchCode": "X", "name": "n", "address": {}, "active": True})
        self.assertEqual((s["open_time"], s["close_time"], s["weekly_off"]), ("11:00", "21:00", []))

    def test_title_place_keeps_short_caps(self):
        self.assertEqual(model.title_place("delhi-NCR"), "Delhi-NCR")

    def test_seed_file_has_no_duplicates_and_all_fields(self):
        with open(os.path.join(ROOT, "data", "stores_seed.json"), encoding="utf-8") as f:
            raw = json.load(f)
        stores = [model.from_kisna_record(r) for r in raw["stores"]]
        self.assertEqual(len(stores), raw["total_count"])
        self.assertEqual(model.duplicate_report(stores), {"store_id": [], "name_city": [], "address_pincode": []})
        for s in stores:
            self.assertTrue(s["store_id"] and s["name"] and s["city"] and s["state"])
            self.assertLess(model.minutes(s["open_time"]) + 60, model.minutes(s["close_time"]) + 1)
        # No secrets carried over from the source API.
        text = json.dumps(raw)
        for banned in ("insuraceKey", "insuranceValue", "gstIn", "invoiceName"):
            self.assertNotIn(banned, text)

    def test_every_dropdown_under_whatsapp_cap(self):
        with open(os.path.join(ROOT, "data", "stores_seed.json"), encoding="utf-8") as f:
            stores = [model.from_kisna_record(r) for r in json.load(f)["stores"]]
        states = {s["state"] for s in stores}
        self.assertLessEqual(len(states), 200)
        for st in states:
            cities = {s["city"] for s in stores if s["state"] == st}
            self.assertLessEqual(len(cities), 200)
            for c in cities:
                self.assertLessEqual(sum(1 for s in stores if s["state"] == st and s["city"] == c), 200)


# CSV import (overrides only) and the kisna.com sync: tests/test_store_sync.py


# ----------------------------------------------------------------- cache
class CacheTests(CacheFixture):
    rows = STORES + [_store(store_id="OFF", state="Goa", city="Panaji", bookable=False)]

    def test_lists_sorted_and_filtered(self):
        # _load itself filters active && bookable in Mongo; the fixture
        # includes a non-bookable row to prove the query shape matters.
        self.assertIn("Delhi", store_cache.list_states())
        self.assertEqual(store_cache.list_cities("delhi"), ["Delhi-NCR"])
        self.assertEqual([s["store_id"] for s in store_cache.list_stores("Delhi", "Delhi-NCR")], ["D1", "D2"])
        self.assertEqual(store_cache.get_store("F203")["city"], "Amritsar")
        self.assertIsNone(store_cache.get_store("nope"))

    def test_ttl_and_bust(self):
        store_cache.list_states()
        store_cache.list_states()
        self.assertEqual(self.load.call_count, 1)
        store_cache.bust()
        store_cache.list_states()
        self.assertEqual(self.load.call_count, 2)

    def test_load_query_is_active_and_bookable(self):
        self._p.stop()
        fake = MagicMock()
        fake.find.return_value.sort.return_value = []
        with patch("kisna_chatbot.database.collections.stores", fake):
            store_cache.bust()
            store_cache.list_states()
        self.assertEqual(fake.find.call_args[0][0], {"active": True, "bookable": True})
        self._p.start()


# ----------------------------------------------------------------- slots
class SlotTests(unittest.TestCase):
    def test_hourly_from_open_until_close_minus_1h(self):
        s = _store(open_time="10:30", close_time="20:00")
        ids = [x["id"] for x in slots.slots_for_date(s, "2026-10-01", NOW)]
        self.assertEqual(ids[0], "10:30")
        self.assertEqual(ids[-1], "18:30")
        self.assertEqual(len(ids), 9)

    def test_today_drops_past_and_under_two_hours(self):
        s = _store(open_time="10:30", close_time="20:00")
        ids = [x["id"] for x in slots.slots_for_date(s, "2026-09-30", NOW.replace(hour=12, minute=45))]
        # 12:45 + 2h lead = 14:45, so 14:30 is too soon and 15:30 is first.
        self.assertEqual(ids[0], "15:30")
        self.assertEqual(ids[-1], "18:30")

    def test_weekly_off_and_holiday_excluded(self):
        s = _store(weekly_off=["thursday"])
        dates = [d.isoformat() for d in slots.bookable_dates(s, NOW)]
        self.assertNotIn("2026-10-01", dates)       # Thursday off
        self.assertNotIn("2026-10-02", dates)       # Gandhi Jayanti
        self.assertEqual(len(dates), 5)
        self.assertEqual(slots.slots_for_date(s, "2026-10-01", NOW), [])
        window = slots.date_window(s, NOW)
        self.assertEqual(window["max_date"], "2026-10-06")
        self.assertIn("2026-10-01", window["unavailable_dates"])

    def test_outside_window_and_past_empty(self):
        s = _store()
        self.assertEqual(slots.slots_for_date(s, "2026-10-07", NOW), [])
        self.assertEqual(slots.slots_for_date(s, "2026-09-29", NOW), [])
        self.assertEqual(slots.slots_for_date(s, "garbage", NOW), [])

    def test_late_today_rolls_min_date_to_tomorrow(self):
        s = _store(close_time="20:00")
        late = NOW.replace(hour=18, minute=10)
        self.assertEqual(slots.date_window(s, late)["min_date"], "2026-10-01")

    def test_clock_label(self):
        self.assertEqual(slots.clock_label("18:30"), "6:30 PM")
        self.assertEqual(slots.clock_label("11:00"), "11:00 AM")
        self.assertEqual(slots.clock_label("12:00"), "12:00 PM")


# ------------------------------------------------------------------ copy
class CopyTests(unittest.TestCase):
    def test_preform_is_client_text(self):
        self.assertEqual(
            form_copy.STORE_VISIT_PREFORM,
            "Would you like to schedule a store visit? 💎\n"
            "Please share your details below, and our jewellery expert will get in "
            "touch with you to assist with your visit. ✨",
        )
        self.assertLessEqual(len(form_copy.STORE_VISIT_PREFORM), 1024)

    def test_confirmation_is_client_text(self):
        sched = form_copy.format_visit_scheduled_for("2026-09-29", "11:00")
        self.assertEqual(sched, "29 September 2026 · 11:00 AM")
        text = form_copy.store_visit_confirmation(
            "KIS-SV-20260928-AB12", "INA Colony - Amritsar - Punjab, Mall Road, Amritsar 143001", sched
        )
        self.assertEqual(
            text.split("\n"),
            [
                "Your appointment is confirmed! 📍✨",
                "Request ID: KIS-SV-20260928-AB12",
                "Store: INA Colony - Amritsar - Punjab, Mall Road, Amritsar 143001",
                "Scheduled for: 29 September 2026 · 11:00 AM",
                "Our store jewellery expert will get in touch with you shortly to assist with your visit.",
                "We appreciate your patience and look forward to welcoming you. 💎",
                "Thank you for choosing Kisna Diamond & Gold! 💙",
            ],
        )

    def test_pins_cover_id_store_address_date_time(self):
        pins = form_copy.store_visit_pins("KIS-SV-1", "Store A", "Addr 1", "1 October 2026 · 6:30 PM")
        for p in ("KIS-SV-1", "Store A", "Addr 1", "1 October 2026", "6:30 PM"):
            self.assertIn(p, pins)


# ------------------------------------------------------------ data_exchange
def _req(step=None, screen="SV_DETAILS", action="data_exchange", **data):
    if step:
        data["step"] = step
    return {"action": action, "screen": screen, "data": data, "flow_token": "sv:123:abcd", "version": "3.0"}


DETAILS = {"first_name": "Priya", "last_name": "", "email": "p@example.com", "phone": "919812345678",
           "looking_for": "diamond_jewellery"}


class DataExchangeTests(CacheFixture):
    def test_details_to_store_screen_with_states(self):
        r = svf.build_store_visit_response(_req("details", **DETAILS), now=NOW)
        self.assertEqual(r["screen"], "SV_STORE")
        self.assertEqual([o["id"] for o in r["data"]["states"]], ["Delhi", "Punjab"])
        self.assertFalse(r["data"]["cities_visible"])
        self.assertEqual(r["data"]["first_name"], "Priya")

    def test_details_validation(self):
        for bad, err in (
            ({"first_name": ""}, svf.ERR_FIRST_NAME),
            ({"email": "not-an-email"}, svf.ERR_EMAIL),
            ({"phone": "12"}, svf.ERR_PHONE),
            ({"looking_for": "silver"}, svf.ERR_LOOKING_FOR),
        ):
            r = svf.build_store_visit_response(_req("details", **{**DETAILS, **bad}), now=NOW)
            self.assertEqual(r["screen"], "SV_DETAILS")
            self.assertEqual(r["data"]["details_error"], err)

    def test_phone_is_optional(self):
        r = svf.build_store_visit_response(_req("details", **{**DETAILS, "phone": ""}), now=NOW)
        self.assertEqual(r["screen"], "SV_STORE")
        with open(os.path.join(ROOT, "json", "store_visit.json"), encoding="utf-8") as f:
            flow = json.load(f)
        fields = flow["screens"][0]["layout"]["children"][0]["children"]
        phone = next(c for c in fields if c.get("name") == "phone")
        self.assertFalse(phone["required"])

    def test_state_then_city_then_store(self):
        r = svf.build_store_visit_response(_req("state", "SV_STORE", state="Delhi", **DETAILS), now=NOW)
        self.assertEqual([o["id"] for o in r["data"]["cities"]], ["Delhi-NCR"])
        self.assertTrue(r["data"]["cities_visible"])
        r = svf.build_store_visit_response(
            _req("city", "SV_STORE", state="Delhi", city="Delhi-NCR", **DETAILS), now=NOW
        )
        stores = r["data"]["stores"]
        self.assertEqual([s["title"] for s in stores], ["Karol Bagh", "Rajouri Garden"])
        self.assertIn("110005", stores[0]["description"])
        self.assertTrue(r["data"]["stores_visible"])
        self.assertEqual(r["data"]["init_values"], {"state": "Delhi", "city": "Delhi-NCR"})
        r = svf.build_store_visit_response(
            _req("store", "SV_STORE", state="Delhi", city="Delhi-NCR", store_id="D2", **DETAILS), now=NOW
        )
        self.assertEqual(r["screen"], "SV_DATETIME")
        d = r["data"]
        self.assertEqual((d["min_date"], d["max_date"]), ("2026-09-30", "2026-10-06"))
        self.assertIn("2026-10-06", d["unavailable_dates"])  # Tuesday off
        self.assertIn("2026-10-02", d["unavailable_dates"])  # holiday
        self.assertEqual(d["time_slots"][0]["id"], "11:30")   # 09:00 + 2h lead
        self.assertEqual(d["store_name"], "Rajouri Garden - Delhi-NCR - Delhi")
        self.assertEqual(d["init_values"], {"preferred_date": "2026-09-30"})

    def test_date_change_refreshes_slots(self):
        r = svf.build_store_visit_response(
            _req("date", "SV_DATETIME", store_id="F203", preferred_date="2026-10-01", **DETAILS), now=NOW
        )
        self.assertEqual(r["data"]["time_slots"][0]["id"], "10:30")
        self.assertEqual(r["data"]["slot_error"], "")
        r = svf.build_store_visit_response(
            _req("date", "SV_DATETIME", store_id="F203", preferred_date="2026-10-02", **DETAILS), now=NOW
        )
        self.assertEqual(r["data"]["slot_error"], svf.ERR_NO_SLOTS)
        self.assertFalse(r["data"]["time_slots"][0]["enabled"])

    def test_unknown_store_and_placeholder(self):
        r = svf.build_store_visit_response(_req("store", "SV_STORE", store_id="_none", **DETAILS), now=NOW)
        self.assertEqual(r["data"]["store_error"], svf.ERR_PICK_STORE)
        r = svf.build_store_visit_response(_req("store", "SV_STORE", store_id="GONE", **DETAILS), now=NOW)
        self.assertEqual(r["data"]["store_error"], svf.ERR_STORE_GONE)

    def test_malformed_and_unknown_step(self):
        r = svf.build_store_visit_response({"action": "data_exchange", "screen": "SV_DETAILS", "data": "junk"})
        self.assertEqual(r["screen"], "SV_DETAILS")
        self.assertEqual(r["data"]["details_error"], svf.ERR_GENERIC)
        r = svf.build_store_visit_response(_req("teleport", "SV_STORE"))
        self.assertEqual(r["screen"], "SV_STORE")
        self.assertEqual(r["data"]["store_error"], svf.ERR_GENERIC)

    def test_handler_exception_is_contained(self):
        with patch.object(svf, "_route", side_effect=RuntimeError("boom")):
            r = svf.build_store_visit_response(_req("details", **DETAILS))
        self.assertEqual(r["data"]["details_error"], svf.ERR_GENERIC)

    def test_init_and_back(self):
        r = svf.build_store_visit_response({"action": "INIT", "flow_token": "sv:1:2"})
        self.assertEqual(r["screen"], "SV_DETAILS")
        self.assertEqual(len(r["data"]["looking_for_options"]), len(LOOKING_FOR_OPTIONS))
        r = svf.build_store_visit_response({"action": "BACK", "screen": "SV_DATETIME", "data": DETAILS})
        self.assertEqual(r["screen"], "SV_STORE")

    def test_zero_store_state_is_hidden(self):
        self.rows = [_store(), _store(store_id="G", state="Goa", city="Panaji", bookable=False)]
        store_cache.bust()
        # _load returns only bookable rows in production; emulate that.
        self.load.side_effect = lambda: [s for s in self.rows if s["bookable"] and s["active"]]
        self.assertEqual(store_cache.list_states(), ["Punjab"])

    def test_dropdown_cap(self):
        many = [_store(store_id=f"S{i}", city=f"City{i:03d}") for i in range(250)]
        self.load.side_effect = lambda: many
        store_cache.bust()
        r = svf.build_store_visit_response(_req("state", "SV_STORE", state="Punjab", **DETAILS), now=NOW)
        self.assertEqual(len(r["data"]["cities"]), 200)

    def test_router_sends_store_visit_to_its_handler_and_keeps_callback(self):
        r = build_flow_response(_req("details", **DETAILS))
        self.assertEqual(r["screen"], "SV_STORE")
        self.assertEqual(build_flow_response({"action": "ping"}), {"data": {"status": "active"}})
        from kisna_chatbot.utils.support_slots import (
            clear_capacity_overrides,
            set_capacity_overrides,
        )

        set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)
        try:
            cb = build_flow_response({"action": "INIT", "screen": "CALLBACK_REQUEST", "flow_token": "x"})
        finally:
            clear_capacity_overrides()
        self.assertEqual(cb["screen"], "CALLBACK_REQUEST")

    def test_title_and_description_limits(self):
        long = _store(name="A Very Long Area Name That Goes On And On - Amritsar - Punjab")
        self.assertLessEqual(len(svf.store_title(long)), 30)


# ------------------------------------------------ encrypted endpoint round trip
def _key_pair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    return key, pem


def _encrypt(key, payload):
    aes_key, iv = os.urandom(16), os.urandom(16)
    enc_key = key.public_key().encrypt(
        aes_key, OAEP(mgf=MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    enc = Cipher(algorithms.AES(aes_key), modes.GCM(iv)).encryptor()
    ct = enc.update(json.dumps(payload).encode()) + enc.finalize() + enc.tag
    body = {
        "encrypted_flow_data": b64encode(ct).decode(),
        "encrypted_aes_key": b64encode(enc_key).decode(),
        "initial_vector": b64encode(iv).decode(),
    }
    return body, aes_key, iv


def _decrypt_response(text, aes_key, iv):
    flipped = bytes(b ^ 0xFF for b in iv)
    return json.loads(AESGCM(aes_key).decrypt(flipped, b64decode(text), None))


class EncryptedEndpointTests(CacheFixture):
    @classmethod
    def setUpClass(cls):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from kisna_chatbot.routes import whatsapp_flows

        cls.key, pem = _key_pair()
        cls._env = patch.dict(os.environ, {"KISNA_FLOW_PRIVATE_KEY": pem, "KISNA_FLOW_PRIVATE_KEY_B64": ""})
        cls._env.start()
        app = FastAPI()
        app.include_router(whatsapp_flows.router)
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls._env.stop()

    def _post(self, payload):
        body, aes_key, iv = _encrypt(self.key, payload)
        resp = self.client.post("/whatsapp/flows/data-exchange", json=body)
        return resp, aes_key, iv

    def test_ping(self):
        resp, k, iv = self._post({"action": "ping", "version": "3.0"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(_decrypt_response(resp.text, k, iv), {"data": {"status": "active"}})

    def test_full_walk_encrypted(self):
        steps = [
            _req("details", **DETAILS),
            _req("state", "SV_STORE", state="Delhi", **DETAILS),
            _req("city", "SV_STORE", state="Delhi", city="Delhi-NCR", **DETAILS),
            _req("store", "SV_STORE", state="Delhi", city="Delhi-NCR", store_id="D1", **DETAILS),
            _req("date", "SV_DATETIME", store_id="D1", preferred_date="2026-12-01", **DETAILS),
        ]
        screens = []
        for payload in steps:
            resp, k, iv = self._post(payload)
            self.assertEqual(resp.status_code, 200, resp.text)
            screens.append(_decrypt_response(resp.text, k, iv)["screen"])
        self.assertEqual(screens, ["SV_STORE", "SV_STORE", "SV_STORE", "SV_DATETIME", "SV_DATETIME"])

    def test_bad_ciphertext_is_421(self):
        body, _, _ = _encrypt(self.key, {"action": "ping"})
        body["encrypted_flow_data"] = b64encode(b"x" * 40).decode()
        self.assertEqual(self.client.post("/whatsapp/flows/data-exchange", json=body).status_code, 421)

    def test_malformed_body_is_400(self):
        resp = self.client.post("/whatsapp/flows/data-exchange", content=b"not json")
        self.assertEqual(resp.status_code, 400)

    def test_p95_latency(self):
        """p95 over 200 calls, cache warm and busted before every call (Mongo
        mocked, so this is our code, not the network).

        The store-visit handler itself is asserted tightly. The full encrypted
        round trip is dominated by flow_endpoint_crypto re-parsing the RSA
        private key from PEM on EVERY request (~100-300 ms here, for every
        Flow, callback included). That layer is out of scope for this change,
        so the round trip gets only a loose bound, well inside Meta's 10 s."""
        payload = _req("city", "SV_STORE", state="Delhi", city="Delhi-NCR", **DETAILS)
        p95 = lambda xs: statistics.quantiles(xs, n=20)[18]  # noqa: E731

        def handler_only(bust):
            times = []
            for _ in range(200):
                if bust:
                    store_cache.bust()
                t = time.perf_counter()
                svf.build_store_visit_response(payload)
                times.append((time.perf_counter() - t) * 1000)
            return p95(times)

        def round_trip():
            times = []
            for _ in range(200):
                t = time.perf_counter()
                resp, _, _ = self._post(payload)
                times.append((time.perf_counter() - t) * 1000)
                self.assertEqual(resp.status_code, 200)
            return p95(times)

        warm, cold, full = handler_only(False), handler_only(True), round_trip()
        print(
            f"\n[store-visit] handler p95 warm={warm:.2f}ms cold={cold:.2f}ms; "
            f"encrypted round trip p95={full:.0f}ms (200 calls each)"
        )
        self.assertLess(warm, 20)
        self.assertLess(cold, 20)
        self.assertLess(full, 2000)


# ----------------------------------------------------------------- submission
def _submission(**over):
    payload = {
        "flow_token": "sv:123:abcd",
        "request_type": "store_visit",
        **DETAILS,
        "store_id": "D1",
        "preferred_date": "2026-10-01",
        "preferred_time": "10:30",
    }
    payload.update(over)
    return {
        "phone_number": "919812345678",
        "client_id": "kisna",
        "whatsapp_username": "Priya",
        "user_profile": {"language": "en"},
        "messages": {"interactive": {"nfm_reply": {"response_json": json.dumps(payload)}}},
    }


class SubmissionTests(CacheFixture):
    def _run(self, data, *, existing=None, insert_side_effect=None, events=True):
        col = MagicMock()
        col.find_one.return_value = existing
        col.insert_one.side_effect = insert_side_effect
        with patch.object(sva, "store_visits", col), patch.object(
            sva, "enqueue_clara_event", new_callable=AsyncMock
        ) as enqueue, patch.object(
            sva, "store_visit_events_enabled", return_value=events
        ), patch.object(sva, "is_slot_bookable", wraps=lambda s, d, t: slots.is_slot_bookable(s, d, t, NOW)):
            out = asyncio.run(sva.StoreVisitAgent().process(data))
        return out, col, enqueue

    def test_books_saves_pushes_and_confirms(self):
        out, col, enqueue = self._run(_submission())
        doc = col.insert_one.call_args[0][0]
        self.assertRegex(doc["request_id"], r"^KIS-SV-\d{8}-[0-9A-F]{4}$")
        self.assertEqual(doc["flow_token"], "sv:123:abcd")
        self.assertEqual(doc["status"], "new")
        self.assertEqual(doc["store"]["store_id"], "D1")
        self.assertEqual(doc["store"]["pincode"], "110005")
        self.assertEqual(doc["preferred_time_label"], "10:30 AM")
        self.assertEqual(doc["source"], sva.SOURCE)
        event = enqueue.call_args[0][0]
        self.assertEqual(event["event_type"], "store_visit_requested")
        self.assertEqual(event["event_id"], doc["request_id"])
        self.assertEqual(event["data"]["store_name"], "Karol Bagh - Delhi-NCR - Delhi")
        self.assertEqual(event["data"]["mobile"], "919812345678")
        text = out["bot_response"][0]["text"]
        self.assertIn(doc["request_id"], text)
        self.assertIn("Scheduled for: 1 October 2026 · 10:30 AM", text)
        self.assertIn("Store: Karol Bagh - Delhi-NCR - Delhi, Ajmal Khan Road, Delhi-NCR 110005", text)
        self.assertEqual(out["bot_response"][0]["_compose"], "store_visit_confirmed")

    def test_blank_phone_books_with_the_whatsapp_number(self):
        _, col, enqueue = self._run(_submission(phone=""))
        doc = col.insert_one.call_args[0][0]
        self.assertEqual(doc["mobile"], "919812345678")
        self.assertEqual(enqueue.call_args[0][0]["data"]["mobile"], "919812345678")

    def test_event_push_off_by_flag(self):
        _, col, enqueue = self._run(_submission(), events=False)
        col.insert_one.assert_called_once()
        enqueue.assert_not_called()

    def test_resubmit_same_token_replays_confirmation(self):
        existing = {
            "request_id": "KIS-SV-20260930-AAAA",
            "store": {"name": "Karol Bagh", "address": "Road", "city": "Delhi-NCR", "pincode": "110005"},
            "preferred_date": "2026-10-01",
            "preferred_time": "10:30",
        }
        out, col, enqueue = self._run(_submission(), existing=existing)
        col.insert_one.assert_not_called()
        enqueue.assert_not_called()
        self.assertIn("KIS-SV-20260930-AAAA", out["bot_response"][0]["text"])

    def test_race_on_unique_token_replays(self):
        existing = {
            "request_id": "KIS-SV-20260930-BBBB",
            "store": {"name": "Karol Bagh", "address": "Road", "city": "Delhi-NCR", "pincode": "110005"},
            "preferred_date": "2026-10-01",
            "preferred_time": "10:30",
        }
        col_calls = {"n": 0}

        def find_one(*a, **k):
            col_calls["n"] += 1
            return None if col_calls["n"] == 1 else existing

        col = MagicMock()
        col.find_one.side_effect = find_one
        col.insert_one.side_effect = DuplicateKeyError("dup")
        with patch.object(sva, "store_visits", col), patch.object(
            sva, "enqueue_clara_event", new_callable=AsyncMock
        ) as enqueue, patch.object(sva, "is_slot_bookable", return_value=True):
            out = asyncio.run(sva.StoreVisitAgent().process(_submission()))
        enqueue.assert_not_called()
        self.assertIn("KIS-SV-20260930-BBBB", out["bot_response"][0]["text"])

    def test_stale_slot_rejected_with_form_again(self):
        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": "123"}):
            out, col, _ = self._run(_submission(preferred_date="2026-10-02"))
        col.insert_one.assert_not_called()
        self.assertEqual(out["bot_response"][0]["text"], sva._REJECT_SLOT)
        self.assertEqual(out["bot_response"][1]["flow"], "store_visit")

    def test_unknown_store_rejected(self):
        out, col, _ = self._run(_submission(store_id="GONE"))
        col.insert_one.assert_not_called()
        self.assertEqual(out["bot_response"][0]["text"], sva._REJECT_STORE)

    def test_other_flows_ignored(self):
        data = _submission()
        data["messages"]["interactive"]["nfm_reply"]["response_json"] = json.dumps(
            {"flow_token": "999", "mobile": "1"}
        )
        self.assertFalse(sva.StoreVisitAgent().should_run(data))


# --------------------------------------------------------------- the offer
class OfferTests(CacheFixture):
    def test_form_with_locator_line_when_available(self):
        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": "123"}):
            items = sva.build_store_visit_bot_response({"username": "Priya"})
        self.assertEqual(items[0]["type"], "flow")
        self.assertEqual(items[0]["flow"], "store_visit")
        self.assertEqual(items[0]["text"], form_copy.STORE_VISIT_PREFORM)
        self.assertIn("kisna.com/store", items[1]["text"])

    def test_locator_only_when_flow_unset_or_no_stores(self):
        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": ""}):
            items = sva.build_store_visit_bot_response({})
        self.assertEqual([i["type"] for i in items], ["text"])
        self.load.side_effect = lambda: []
        store_cache.bust()
        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": "123"}):
            items = sva.build_store_visit_bot_response({})
        self.assertEqual([i["type"] for i in items], ["text"])
        self.assertNotIn("pincode", items[0]["text"].lower())

    def test_sender_prefills_and_uses_unique_token(self):
        from kisna_chatbot.whatsapp_functions.flow import send_store_visit_flow as sender

        resp = MagicMock(status_code=200)
        resp.json.return_value = {"ok": True}
        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": "123"}), patch.object(
            sender.httpx, "post", return_value=resp
        ) as post:
            sender.send_store_visit_flow("919812345678", "Body", first_name="Priya")
            sender.send_store_visit_flow("919812345678", "Body", first_name="Priya")
        p1 = post.call_args_list[0].kwargs["json"]["interactive"]
        p2 = post.call_args_list[1].kwargs["json"]["interactive"]
        params = p1["action"]["parameters"]
        self.assertEqual(p1["body"]["text"], "Body")
        self.assertEqual(params["flow_id"], "123")
        self.assertTrue(params["flow_token"].startswith("sv:123:"))
        self.assertNotEqual(params["flow_token"], p2["action"]["parameters"]["flow_token"])
        self.assertEqual(params["flow_action_payload"]["screen"], "SV_DETAILS")
        self.assertEqual(params["flow_action_payload"]["data"]["first_name"], "Priya")
        self.assertEqual(params["flow_action_payload"]["data"]["phone"], "919812345678")

    def test_sender_returns_none_without_stores(self):
        from kisna_chatbot.whatsapp_functions.flow import send_store_visit_flow as sender

        self.load.side_effect = lambda: []
        store_cache.bust()
        with patch.dict(os.environ, {"KISNA_STORE_VISIT_FLOW_ID": "123"}), patch.object(
            sender.httpx, "post"
        ) as post:
            self.assertIsNone(sender.send_store_visit_flow("919812345678"))
        post.assert_not_called()


# ---------------------------------------------------------------- routing
class RoutingTests(unittest.TestCase):
    def test_override_regex(self):
        from kisna_chatbot.processors.classifier import _programmatic_intent_override

        for msg in (
            "book a store visit",
            "I want to visit your store",
            "store near me",
            "nearest Kisna store",
            "can I see this in store",
            "appointment at the showroom",
            "dukaan kahan hai",
            "store visit karna hai",
        ):
            self.assertEqual(_programmatic_intent_override(msg), ("store_visit", 0.93), msg)
        for msg in (
            "store in Pune",
            "Mumbai me store hai kya",
            "nearest store 400001",
            "do you have diamond rings",
            "call me back to book a visit",
        ):
            self.assertNotEqual((_programmatic_intent_override(msg) or ("",))[0], "store_visit", msg)

    PICKUP = (
        "Can I pick it up from a store?",
        "store pickup available?",
        "can I collect my order from the store",
        "deliver it to the Kisna store near me",
        "Is in-store delivery available?",
        "can I pick up my online order at the showroom",
        "can you deliver to a store instead of home",
        "buy online and collect in store?",
        "store se pickup kar sakte hai?",
        "order store pe deliver ho sakta hai?",
        "kya main store se order le sakti hoon",
        "online order karke dukaan se le lu?",
    )
    VISIT = (
        "I want to see it in the store before buying",
        "visit the store to try it on",
        "book a store visit",
        "showroom visit book karo",
    )

    def test_store_pickup_is_general_never_the_form(self):
        from kisna_chatbot.processors.classifier import (
            _programmatic_intent_fallback,
            _programmatic_intent_override,
        )

        for msg in self.PICKUP:
            self.assertEqual(_programmatic_intent_override(msg), ("general", 0.93), msg)
            self.assertEqual(_programmatic_intent_fallback(msg)[0], "general", msg)
        for msg in self.VISIT:
            self.assertEqual(_programmatic_intent_override(msg), ("store_visit", 0.93), msg)
        for msg in ("pick a ring for me", "I will pick one up later"):
            self.assertIsNone(_programmatic_intent_override(msg), msg)

    def test_general_agent_pickup_answer_gets_store_locator_button(self):
        from kisna_chatbot.ai.types import GeneralAgentResult, ProviderName
        from kisna_chatbot.processors.general_agent import GeneralAgent

        def run(query, text):
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": query}},
                "user_profile": {"service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.general_agent.run_general_agent",
                new_callable=AsyncMock,
                return_value=GeneralAgentResult(
                    message_text=text, live_agent_requested=False,
                    provider=ProviderName.OPENAI, model="test-model",
                ),
            ):
                return asyncio.run(GeneralAgent().process(data))["bot_response"]

        out = run(
            "Can I pick it up from a store?",
            'Absolutely! Choose "In-Store Delivery" at checkout. Stores: kisna.com/store',
        )
        self.assertNotIn("kisna.com/store", out[0]["text"])
        cta = out[-1]
        self.assertEqual((cta["type"], cta["display_text"]), ("cta_url", "Find a Store"))
        self.assertIn("kisna.com/store", cta["url"])
        self.assertEqual(cta["_compose"], "store_pickup_cta")
        other = run("what is your return policy?", "Returns within 7 days.")
        self.assertNotIn("cta_url", [r.get("type") for r in other])

    def test_json_flow_screens_and_payload_keys(self):
        with open(os.path.join(ROOT, "json", "store_visit.json"), encoding="utf-8") as f:
            flow = json.load(f)
        self.assertEqual(flow["version"], "7.0")
        self.assertEqual([s["id"] for s in flow["screens"]], ["SV_DETAILS", "SV_STORE", "SV_DATETIME"])
        text = json.dumps(flow)
        for key in ("first_name", "looking_for", "store_id", "preferred_date", "preferred_time"):
            self.assertIn("${form.%s}" % key if key != "store_id" else "${data.store_id}", text)
        self.assertTrue(flow["screens"][2]["terminal"])
        # Meta rejects component-level init-value in v7.0 (validated on the
        # draft): prefills go through each Form's dynamic init-values.
        self.assertNotIn('"init-value"', text)
        for screen in flow["screens"]:
            form = screen["layout"]["children"][0]
            self.assertEqual(form["init-values"], "${data.init_values}")
            self.assertIn("init_values", screen["data"])

    def test_screens_send_init_values(self):
        d = svf.details_screen_data("Priya", "919812345678")
        self.assertEqual(d["init_values"], {"first_name": "Priya", "phone": "919812345678"})
        self.assertEqual(svf.details_screen_data()["init_values"], {})


if __name__ == "__main__":
    unittest.main()
