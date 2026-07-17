"""Tests for Help Center routing (text-only / direct forms)."""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")

from kisna_chatbot.processors.service_list import (  # noqa: E402
    _handle_menu_selection,
    _normalize_menu_key,
    build_main_menu_bot_response,
)


class TestHelpCenter(unittest.TestCase):
    def test_main_menu_bot_response_is_text_help(self):
        resp = build_main_menu_bot_response()
        self.assertEqual(resp["type"], "text")
        self.assertIn("tell me what you need", resp["text"].lower())

    def test_help_center_menu_key(self):
        self.assertEqual(_normalize_menu_key("Help Center", ""), "help_center")

    def test_help_center_opens_text_help(self):
        user_profile = {}
        data = {"phone_number": "919999999999"}
        _handle_menu_selection("Help Center", user_profile, data, "help_center")
        self.assertEqual(data["bot_response"][0]["type"], "text")
        self.assertIn("tell me what you need", data["bot_response"][0]["text"].lower())

    def test_legacy_raise_complaint_sends_form(self):
        user_profile = {}
        data = {"phone_number": "919999999999"}
        _handle_menu_selection("Raise Complaint", user_profile, data, "raise_complaint")
        self.assertEqual(data["bot_response"][0]["type"], "flow")
        self.assertEqual(data["bot_response"][0]["flow"], "damage_complaint")


if __name__ == "__main__":
    unittest.main()
