"""Tests for IST support slot filtering."""

import os
import unittest
from datetime import datetime, timedelta, timezone

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from kisna_chatbot.utils.support_slots import (  # noqa: E402
    available_slots_for_date,
    is_preferred_datetime_valid,
    is_slot_still_bookable,
    screen_data_for_date,
)

_IST = timezone(timedelta(hours=5, minutes=30))


class TestSupportSlots(unittest.TestCase):
    def test_today_1315_filters_early_slots(self):
        now = datetime(2026, 7, 13, 13, 15, tzinfo=_IST)
        slots = available_slots_for_date("2026-07-13", now=now)
        ids = [s["id"] for s in slots]
        self.assertEqual(ids, ["14-15", "15-16", "16-17"])
        self.assertFalse(is_slot_still_bookable("2026-07-13", "13-14", now=now))
        self.assertTrue(is_slot_still_bookable("2026-07-13", "14-15", now=now))

    def test_future_date_all_slots(self):
        now = datetime(2026, 7, 13, 13, 15, tzinfo=_IST)
        slots = available_slots_for_date("2026-07-20", now=now)
        self.assertEqual(len(slots), 7)
        self.assertEqual(slots[0]["id"], "10-11")

    def test_today_after_1700_empty(self):
        now = datetime(2026, 7, 13, 17, 0, tzinfo=_IST)
        slots = available_slots_for_date("2026-07-13", now=now)
        self.assertEqual(slots, [])
        data = screen_data_for_date("2026-07-13", now=now)
        self.assertIn("No time slots", data["slot_error"])

    def test_past_date_empty(self):
        now = datetime(2026, 7, 13, 10, 0, tzinfo=_IST)
        self.assertEqual(available_slots_for_date("2026-07-12", now=now), [])

    def test_validation_reasons(self):
        now = datetime(2026, 7, 13, 13, 15, tzinfo=_IST)
        ok, reason = is_preferred_datetime_valid("2026-07-12", "14-15", now=now)
        self.assertFalse(ok)
        self.assertEqual(reason, "past_date")
        ok, reason = is_preferred_datetime_valid("2026-07-13", "10-11", now=now)
        self.assertFalse(ok)
        self.assertEqual(reason, "past_slot")
        ok, reason = is_preferred_datetime_valid("2026-07-13", "14-15", now=now)
        self.assertTrue(ok)
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
