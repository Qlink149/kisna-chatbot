"""Phase 0 — Clara /filters in-process cache."""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import patch

from kisna_chatbot.integrations import clara_filters as cf


def _payload(**overrides):
    base = {
        "karat": [
            {"label": "18KT", "value": "k18", "slug": "18kt"},
            {"label": "14KT", "value": "k14", "slug": "14kt"},
        ],
        "color": [
            {"label": "Rose", "value": "c-rose", "slug": "rose"},
            {"label": "Yellow", "value": "c-yellow", "slug": "yellow"},
        ],
        "collection": [
            {
                "label": "Evil Eye Collection",
                "value": "col-evil",
                "slug": "evil-eye-collection",
            },
            {
                "label": "Tanishta Collection",
                "value": "col-tan",
                "slug": "tanishta-collection",
            },
        ],
        "gender": [
            {"label": "Women", "value": "g-women", "slug": "women"},
            {"label": "Mens", "value": "g-mens", "slug": "mens"},
            {"label": "Kids", "value": "g-kids", "slug": "kids"},
        ],
        "categories": [
            {"label": "Chain", "value": "cat-chain", "slug": "chain"},
            {"label": "Rings", "value": "cat-rings", "slug": "rings"},
        ],
        "availability": [
            {"label": "Ready To Ship", "value": "readyToShip", "slug": "ready-to-ship"},
        ],
    }
    base.update(overrides)
    return base


class ClaraFiltersCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        cf.reset_filters_cache_for_tests()

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    async def test_cold_cache_returns_none_without_snapshot_or_live(self):
        async def _fail(*_a, **_k):
            return None, None, False

        with patch.object(cf, "_load_snapshot", return_value=None), patch.object(
            cf, "_SNAPSHOT_LOADED", True
        ), patch.object(cf, "_SNAPSHOT", None), patch.object(
            cf, "_fetch_filters_live", _fail
        ):
            self.assertIsNone(await cf.get_filters())

    async def test_warm_cache_hit_is_sub_millisecond(self):
        payload = _payload()
        cf._CACHE[None] = cf._CacheEntry(
            payload=payload, etag='"abc"', fetched_at=time.time()
        )

        async def _should_not_fetch(*_a, **_k):
            raise AssertionError("fresh cache must not hit the network")

        with patch.object(cf, "_fetch_filters_live", _should_not_fetch):
            t0 = time.perf_counter()
            for _ in range(100):
                got = await cf.get_filters()
                self.assertIs(got, payload)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            self.assertLess(
                elapsed_ms,
                50,
                f"cache hits too slow: {elapsed_ms:.2f}ms for 100 calls",
            )
            per_hit = elapsed_ms / 100
            self.assertLess(per_hit, 1.0, f"per-hit {per_hit:.3f}ms not sub-ms")

    async def test_ttl_expiry_schedules_refresh_but_returns_last_good(self):
        payload = _payload()
        cf._CACHE[None] = cf._CacheEntry(
            payload=payload, etag='"old"', fetched_at=time.time() - 999999
        )
        refreshed = {"karat": [{"label": "9KT", "value": "k9", "slug": "9kt"}]}
        calls = {"n": 0}

        async def _fetch(*_a, **_k):
            calls["n"] += 1
            await asyncio.sleep(0.05)
            return refreshed, '"new"', False

        with patch.object(cf, "_fetch_filters_live", _fetch), patch.object(
            cf, "_ttl_seconds", return_value=1
        ):
            got = await cf.get_filters()
            self.assertIs(got, payload)
            await asyncio.sleep(0.15)
            self.assertGreaterEqual(calls["n"], 1)
            self.assertIs(cf._CACHE[None].payload, refreshed)

    async def test_304_refreshes_ttl_without_replacing_payload(self):
        payload = _payload()
        cf._CACHE[None] = cf._CacheEntry(
            payload=payload, etag='"etag1"', fetched_at=time.time() - 999999
        )

        async def _fetch(*_a, **_k):
            return None, '"etag1"', True

        with patch.object(cf, "_fetch_filters_live", _fetch), patch.object(
            cf, "_ttl_seconds", return_value=1
        ):
            result = await cf._refresh_entry(None)
            self.assertIs(result, payload)
            self.assertIs(cf._CACHE[None].payload, payload)
            self.assertGreater(cf._CACHE[None].fetched_at, time.time() - 2)

    async def test_fetch_failure_returns_last_good(self):
        payload = _payload()
        cf._CACHE[None] = cf._CacheEntry(
            payload=payload, etag='"x"', fetched_at=time.time() - 999999
        )

        async def _fail(*_a, **_k):
            return None, None, False

        with patch.object(cf, "_fetch_filters_live", _fail), patch.object(
            cf, "_ttl_seconds", return_value=1
        ):
            self.assertIs(await cf._refresh_entry(None), payload)

    async def test_fetch_failure_with_no_last_good_returns_none(self):
        with patch.object(cf, "_load_snapshot", return_value=None), patch.object(
            cf, "_SNAPSHOT_LOADED", True
        ), patch.object(cf, "_SNAPSHOT", None):

            async def _fail(*_a, **_k):
                return None, None, False

            with patch.object(cf, "_fetch_filters_live", _fail):
                self.assertIsNone(await cf._refresh_entry(None))

    async def test_warm_filters_cache_summary(self):
        snap = {
            "global": {"payload": _payload(), "etag": None},
            "by_category": {"cat-chain": {"payload": _payload(), "etag": None}},
        }

        async def _ok(*_a, **_k):
            return _payload(), '"e"', False

        with patch.object(cf, "_load_snapshot", return_value=snap), patch.object(
            cf, "_SNAPSHOT_LOADED", True
        ), patch.object(cf, "_fetch_filters_live", _ok):
            summary = await cf.warm_filters_cache()
            self.assertGreaterEqual(summary["warmed"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertIn("elapsed_ms", summary)


class ClaraFiltersAccessorTests(unittest.TestCase):
    def setUp(self):
        cf.reset_filters_cache_for_tests()

    def tearDown(self):
        cf.reset_filters_cache_for_tests()

    def test_accessors_safe_when_cold(self):
        with patch.object(cf, "_load_snapshot", return_value=None), patch.object(
            cf, "_SNAPSHOT_LOADED", True
        ), patch.object(cf, "_SNAPSHOT", None):
            self.assertIsNone(cf.get_category_id("chain"))
            self.assertIsNone(cf.get_karat_id(None, "18KT"))
            self.assertIsNone(cf.get_colour_id(None, "rose"))
            self.assertIsNone(cf.get_collection_id("Evil Eye"))
            self.assertEqual(cf.get_available_options(None, "karat"), [])
            self.assertFalse(cf.is_value_available(None, "karat", "18KT"))

    def test_accessors_from_warm_cache(self):
        payload = _payload()
        cf._CACHE[None] = cf._CacheEntry(payload=payload, fetched_at=time.time())
        self.assertEqual(cf.get_category_id("chain"), "cat-chain")
        self.assertEqual(cf.get_category_id("rings"), "cat-rings")
        self.assertEqual(cf.get_karat_id(None, "18KT"), "k18")
        self.assertEqual(cf.get_colour_id(None, "rose gold"), "c-rose")
        self.assertEqual(cf.get_collection_id("evil eye"), "col-evil")
        self.assertEqual(cf.get_collection_id("Tanishta"), "col-tan")
        self.assertEqual(cf.get_gender_tag_id("men"), "g-mens")
        self.assertEqual(cf.get_gender_tag_id("women"), "g-women")
        self.assertEqual(len(cf.get_available_options(None, "karat")), 2)
        self.assertTrue(cf.is_value_available(None, "karat", "18KT"))
        self.assertFalse(cf.is_value_available(None, "karat", "22KT"))

    def test_collection_fuzzy_rejects_low_score(self):
        payload = _payload()
        cf._CACHE[None] = cf._CacheEntry(payload=payload, fetched_at=time.time())
        self.assertIsNone(cf.get_collection_id("completely unrelated xyz"))

    def test_degradation_contract_filters_unavailable(self):
        with patch.object(cf, "_load_snapshot", return_value=None), patch.object(
            cf, "_SNAPSHOT_LOADED", True
        ), patch.object(cf, "_SNAPSHOT", None):
            self.assertFalse(cf.filters_available())
            self.assertIsNone(cf.get_category_id("ring"))
            self.assertIsNone(cf.get_karat_id("any", "18KT"))
            self.assertEqual(cf.get_available_options("any", "gender"), [])

    def test_committed_snapshot_loads(self):
        snap = cf._load_snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn("captured_at", snap)
        payload = (snap.get("global") or {}).get("payload")
        self.assertIsInstance(payload, dict)
        labels = {k.get("label") for k in (payload.get("karat") or [])}
        self.assertNotIn("22KT", labels)
        self.assertIn("18KT", labels)


if __name__ == "__main__":
    unittest.main()
