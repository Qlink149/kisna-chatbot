"""Tests for IST support slot filtering and capacity."""

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.utils.support_hours import SUPPORT_HOLIDAYS  # noqa: E402
from kisna_chatbot.utils.support_slots import (  # noqa: E402
    DAILY_MAX,
    SLOT_CAPACITY,
    available_slots_for_date,
    clear_capacity_overrides,
    find_next_available,
    is_preferred_datetime_valid,
    is_slot_still_bookable,
    normalize_slot_id,
    resolve_booking_slot,
    screen_data_for_date,
    set_capacity_overrides,
)

_IST = timezone(timedelta(hours=5, minutes=30))


class TestSupportSlots(unittest.TestCase):
    def setUp(self):
        self._holidays_backup = dict(SUPPORT_HOLIDAYS)
        SUPPORT_HOLIDAYS.clear()
        set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)

    def tearDown(self):
        clear_capacity_overrides()
        SUPPORT_HOLIDAYS.clear()
        SUPPORT_HOLIDAYS.update(self._holidays_backup)

    def test_weekday_slots_after_1315(self):
        # Mon 2026-07-13
        now = datetime(2026, 7, 13, 13, 15, tzinfo=_IST)
        slots = available_slots_for_date("2026-07-13", now=now)
        ids = [s["id"] for s in slots]
        self.assertEqual(ids, ["15-18"])
        self.assertFalse(is_slot_still_bookable("2026-07-13", "13-15", now=now))
        self.assertTrue(is_slot_still_bookable("2026-07-13", "15-18", now=now))

    def test_future_weekday_three_slots(self):
        now = datetime(2026, 7, 13, 13, 15, tzinfo=_IST)
        # Mon 2026-07-20
        slots = available_slots_for_date("2026-07-20", now=now)
        self.assertEqual([s["id"] for s in slots], ["10-13", "13-15", "15-18"])

    def test_saturday_single_slot(self):
        now = datetime(2026, 7, 10, 9, 0, tzinfo=_IST)
        # Sat 2026-07-11
        slots = available_slots_for_date("2026-07-11", now=now)
        self.assertEqual([s["id"] for s in slots], ["10-16"])

    def test_sunday_empty(self):
        now = datetime(2026, 7, 10, 9, 0, tzinfo=_IST)
        self.assertEqual(available_slots_for_date("2026-07-12", now=now), [])
        data = screen_data_for_date("2026-07-12", now=now)
        self.assertIn("Sunday", data["slot_error"])

    def test_holiday_empty(self):
        SUPPORT_HOLIDAYS["2026-07-14"] = "Test Holiday"  # Tue
        now = datetime(2026, 7, 10, 9, 0, tzinfo=_IST)
        self.assertEqual(available_slots_for_date("2026-07-14", now=now), [])
        data = screen_data_for_date("2026-07-14", now=now)
        self.assertIn("Test Holiday", data["slot_error"])

    def test_today_after_last_slot_empty(self):
        now = datetime(2026, 7, 13, 18, 0, tzinfo=_IST)  # Mon 6pm
        slots = available_slots_for_date("2026-07-13", now=now)
        self.assertEqual(slots, [])
        data = screen_data_for_date("2026-07-13", now=now)
        self.assertIn("No time slots", data["slot_error"])

    def test_past_date_empty(self):
        now = datetime(2026, 7, 13, 10, 0, tzinfo=_IST)
        self.assertEqual(available_slots_for_date("2026-07-12", now=now), [])

    def test_day_full_hides_slots(self):
        set_capacity_overrides(lambda _d: DAILY_MAX, lambda _d, _s: 0)
        now = datetime(2026, 7, 13, 9, 0, tzinfo=_IST)
        self.assertEqual(available_slots_for_date("2026-07-20", now=now), [])
        data = screen_data_for_date("2026-07-20", now=now)
        self.assertIn("fully booked", data["slot_error"].lower())

    def test_slot_capacity_filters(self):
        def slot_count(_d, sid):
            return SLOT_CAPACITY if sid == "10-13" else 0

        set_capacity_overrides(lambda _d: 1, slot_count)
        now = datetime(2026, 7, 13, 9, 0, tzinfo=_IST)
        ids = [s["id"] for s in available_slots_for_date("2026-07-20", now=now)]
        self.assertEqual(ids, ["13-15", "15-18"])

    def test_validation_reasons(self):
        now = datetime(2026, 7, 13, 13, 15, tzinfo=_IST)
        ok, reason = is_preferred_datetime_valid("2026-07-12", "13-15", now=now)
        self.assertFalse(ok)
        self.assertEqual(reason, "past_date")
        ok, reason = is_preferred_datetime_valid("2026-07-13", "10-13", now=now)
        self.assertFalse(ok)
        self.assertEqual(reason, "past_slot")
        ok, reason = is_preferred_datetime_valid("2026-07-13", "15-18", now=now)
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        ok, reason = is_preferred_datetime_valid("2026-07-12", "10-13", now=now)
        # Sunday
        self.assertFalse(ok)
        self.assertEqual(reason, "past_date")  # 12th is before 13th; use future Sunday
        ok, reason = is_preferred_datetime_valid("2026-07-19", "10-13", now=now)
        self.assertFalse(ok)
        self.assertEqual(reason, "closed_day")

    def test_legacy_normalize(self):
        self.assertEqual(normalize_slot_id("14-15", "2026-07-20"), "13-15")
        self.assertEqual(normalize_slot_id("morning", "2026-07-20"), "10-13")
        self.assertEqual(normalize_slot_id("10-11", "2026-07-11"), "10-16")

    def test_find_next_skips_full_slot(self):
        def slot_count(_d, sid):
            return SLOT_CAPACITY if sid == "10-13" else 0

        set_capacity_overrides(lambda _d: 1, slot_count)
        now = datetime(2026, 7, 13, 9, 0, tzinfo=_IST)
        nxt = find_next_available("2026-07-20", "10-13", now=now)
        self.assertEqual(nxt, ("2026-07-20", "13-15"))

    def test_find_next_day_when_day_full(self):
        def day_count(d):
            return DAILY_MAX if d == "2026-07-20" else 0

        set_capacity_overrides(day_count, lambda _d, _s: 0)
        now = datetime(2026, 7, 13, 9, 0, tzinfo=_IST)
        nxt = find_next_available("2026-07-20", "10-13", now=now)
        self.assertEqual(nxt, ("2026-07-21", "10-13"))  # Tue

    def test_resolve_reschedules_full_slot(self):
        def slot_count(_d, sid):
            return SLOT_CAPACITY if sid == "10-13" else 0

        set_capacity_overrides(lambda _d: 1, slot_count)
        now = datetime(2026, 7, 13, 9, 0, tzinfo=_IST)
        result = resolve_booking_slot("2026-07-20", "10-13", now=now)
        self.assertEqual(result, ("2026-07-20", "13-15", True))


if __name__ == "__main__":
    unittest.main()
