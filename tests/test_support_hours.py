"""Tests for support availability engine."""

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from kisna_chatbot.utils import support_hours
from kisna_chatbot.utils.support_hours import (
    SUPPORT_HOLIDAYS,
    format_support_hours_text,
    get_support_status,
    is_holiday,
    is_working_day,
)

IST = ZoneInfo("Asia/Kolkata")


class TestSupportHours(unittest.TestCase):
    def setUp(self):
        self._holidays_backup = dict(SUPPORT_HOLIDAYS)
        SUPPORT_HOLIDAYS.clear()

    def tearDown(self):
        SUPPORT_HOLIDAYS.clear()
        SUPPORT_HOLIDAYS.update(self._holidays_backup)

    def test_open_weekday_midday(self):
        now = datetime(2026, 7, 8, 12, 0, tzinfo=IST)  # Wed
        self.assertEqual(get_support_status(now), {"status": "open"})

    def test_closed_sunday(self):
        now = datetime(2026, 7, 12, 12, 0, tzinfo=IST)  # Sun
        self.assertEqual(get_support_status(now), {"status": "closed_hours"})
        self.assertFalse(is_working_day(now.date()))

    def test_saturday_open_window(self):
        now = datetime(2026, 7, 11, 11, 0, tzinfo=IST)  # Sat 11am
        self.assertEqual(get_support_status(now), {"status": "open"})
        self.assertTrue(is_working_day(now.date()))

    def test_saturday_closed_evening(self):
        now = datetime(2026, 7, 11, 17, 0, tzinfo=IST)  # Sat 5pm
        self.assertEqual(get_support_status(now), {"status": "closed_hours"})

    def test_holiday_from_constant(self):
        SUPPORT_HOLIDAYS["2026-07-09"] = "Test Holiday"
        now = datetime(2026, 7, 9, 12, 0, tzinfo=IST)
        self.assertEqual(
            get_support_status(now),
            {"status": "closed_holiday", "holiday": "Test Holiday"},
        )
        self.assertTrue(is_holiday("2026-07-09"))
        self.assertFalse(is_working_day("2026-07-09"))

    def test_format_support_hours_text(self):
        text = format_support_hours_text()
        self.assertIn("10:00am", text)
        self.assertIn("6:30pm", text)
        self.assertIn("Sat", text)

    def test_no_env_holiday_helper(self):
        self.assertFalse(hasattr(support_hours, "_env_holidays"))
        self.assertFalse(hasattr(support_hours, "clear_support_hours_cache"))


if __name__ == "__main__":
    unittest.main()
