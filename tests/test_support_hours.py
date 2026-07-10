"""Tests for support availability engine."""

import os
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from kisna_chatbot.utils.support_hours import (
    clear_support_hours_cache,
    format_support_hours_text,
    get_support_status,
)

IST = ZoneInfo("Asia/Kolkata")


class TestSupportHours(unittest.TestCase):
    def setUp(self):
        clear_support_hours_cache()
        self._old_holidays = os.environ.pop("KISNA_SUPPORT_HOLIDAYS", None)

    def tearDown(self):
        clear_support_hours_cache()
        if self._old_holidays is not None:
            os.environ["KISNA_SUPPORT_HOLIDAYS"] = self._old_holidays

    def test_open_weekday_midday(self):
        now = datetime(2026, 7, 8, 12, 0, tzinfo=IST)  # Wed
        self.assertEqual(get_support_status(now), {"status": "open"})

    def test_closed_sunday(self):
        now = datetime(2026, 7, 12, 12, 0, tzinfo=IST)  # Sun
        self.assertEqual(get_support_status(now), {"status": "closed_hours"})

    def test_saturday_open_window(self):
        now = datetime(2026, 7, 11, 11, 0, tzinfo=IST)  # Sat 11am
        self.assertEqual(get_support_status(now), {"status": "open"})

    def test_saturday_closed_evening(self):
        now = datetime(2026, 7, 11, 17, 0, tzinfo=IST)  # Sat 5pm
        self.assertEqual(get_support_status(now), {"status": "closed_hours"})

    def test_holiday_from_env(self):
        os.environ["KISNA_SUPPORT_HOLIDAYS"] = "2026-07-09:Test Holiday"
        clear_support_hours_cache()
        now = datetime(2026, 7, 9, 12, 0, tzinfo=IST)
        self.assertEqual(
            get_support_status(now),
            {"status": "closed_holiday", "holiday": "Test Holiday"},
        )

    def test_format_support_hours_text(self):
        text = format_support_hours_text()
        self.assertIn("10:00am", text)
        self.assertIn("6:30pm", text)
        self.assertIn("Sat", text)


if __name__ == "__main__":
    unittest.main()
