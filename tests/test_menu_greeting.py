"""Tests for greeting menu and complaint flow helpers."""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from kisna_chatbot.processors.service_list import (
    _handle_menu_selection,
    _normalize_menu_key,
    build_complaint_flow_bot_response,
    build_greeting_welcome_bot_responses,
    is_new_session,
    is_pure_greeting,
)


class TestMenuGreeting(unittest.TestCase):
    def test_pure_greetings(self):
        self.assertTrue(is_pure_greeting("Hi"))
        self.assertTrue(is_pure_greeting("  hello  "))
        self.assertTrue(is_pure_greeting("What's up"))
        self.assertFalse(is_pure_greeting("What do you have?"))
        self.assertFalse(is_pure_greeting("I have a complaint"))

    def test_new_session(self):
        self.assertTrue(is_new_session([]))
        self.assertFalse(is_new_session([{"role": "user", "content": "hi"}]))

    def test_greeting_responses_shape(self):
        responses = build_greeting_welcome_bot_responses()
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["type"], "text")
        self.assertEqual(responses[1]["type"], "list")

    def test_complaint_flow_shape(self):
        flow = build_complaint_flow_bot_response()
        self.assertEqual(flow["type"], "flow")
        self.assertEqual(flow["flow"], "damage_complaint")

    def test_raise_complaint_menu_titles(self):
        self.assertEqual(
            _normalize_menu_key("Raise Complaint", "damage_complaint"),
            "damage_complaint",
        )
        self.assertEqual(
            _normalize_menu_key("Raise a Complaint", ""),
            "raise_complaint",
        )

    def test_handle_raise_complaint_legacy_title(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Raise Complaint", user_profile, data, "damage_complaint")
        self.assertEqual(user_profile["service_selected"], "complaint")
        self.assertEqual(data["bot_response"][0]["type"], "flow")


if __name__ == "__main__":
    unittest.main()
