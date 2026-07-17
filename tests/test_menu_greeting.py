"""Tests for greeting and menu helpers (text-only conversational)."""

import os
import asyncio
import unittest
from unittest.mock import patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from kisna_chatbot.processors.service_list import (
    _handle_menu_selection,
    _normalize_menu_key,
    build_main_menu_bot_response,
    build_complaint_flow_bot_response,
    build_complaint_entry_cta_bot_response,
    build_greeting_text,
    build_greeting_welcome_bot_responses,
    is_menu_request,
    is_new_session,
    is_pure_greeting,
    ServiceList,
)
from kisna_chatbot.models.enums import QuickReplyId
from kisna_chatbot.processors.classifier import Classifier, is_greeting_message
from kisna_chatbot.constants import KIA_HANDOFF_MESSAGE


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

    def test_menu_request_detection(self):
        self.assertTrue(is_menu_request("Send me the menu"))
        self.assertTrue(is_menu_request("open menu"))
        self.assertTrue(is_menu_request("options"))
        self.assertFalse(is_menu_request("I want a sofa"))

    def test_main_menu_builder_shape(self):
        menu = build_main_menu_bot_response()
        self.assertEqual(menu["type"], "text")
        self.assertIsInstance(menu["text"], str)
        self.assertTrue(menu["text"].strip())
        self.assertIn("tell me what you need", menu["text"].lower())

    def test_greeting_by_name(self):
        text = build_greeting_text(
            chat_history=[],
            user_profile={"username": "Priya"},
        )
        self.assertIn("Priya", text)
        self.assertIn("Welcome to Kisna", text)

    def test_greeting_without_name(self):
        text = build_greeting_text(chat_history=[], user_profile={})
        self.assertNotIn("None", text)
        self.assertIn("Welcome to Kisna", text)

    def test_greeting_garbage_name_omitted(self):
        for bad in ("12345", "a" * 40, "foo@bar.com", "None"):
            text = build_greeting_text(
                chat_history=[],
                user_profile={"username": bad},
            )
            self.assertNotIn(bad[:10], text)

    def test_greeting_suffix_detection(self):
        self.assertTrue(is_greeting_message("hey there"))
        self.assertTrue(is_greeting_message("hello ji"))
        self.assertFalse(is_greeting_message("hi show me rings"))

    def test_kia_handoff_message(self):
        self.assertIn("Kisna representative", KIA_HANDOFF_MESSAGE)
        self.assertNotIn("live designer", KIA_HANDOFF_MESSAGE.lower())

    def test_greeting_responses_returning_user(self):
        responses = build_greeting_welcome_bot_responses(
            chat_history=[{"role": "user", "content": "hi"}],
            user_profile={"username": "Asha"},
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["type"], "text")
        self.assertIn("Welcome back", responses[0]["text"])
        self.assertIn("Asha", responses[0]["text"])

    def test_greeting_responses_new_session(self):
        responses = build_greeting_welcome_bot_responses(
            phone_number="919999999999",
            chat_history=[],
            user_profile={},
        )
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["type"], "text")
        self.assertIn("Welcome to Kisna", responses[0]["text"])
        self.assertNotIn("Welcome back", responses[0]["text"])

    def test_complaint_flow_shape(self):
        flow = build_complaint_flow_bot_response()
        self.assertEqual(flow["type"], "flow")
        self.assertEqual(flow["flow"], "damage_complaint")

    def test_complaint_entry_cta_is_now_form(self):
        cta = build_complaint_entry_cta_bot_response()
        self.assertEqual(cta["type"], "flow")
        self.assertEqual(cta["flow"], "damage_complaint")

    def test_raise_complaint_menu_titles(self):
        self.assertEqual(
            _normalize_menu_key("Raise Complaint", "damage_complaint"),
            "damage_complaint",
        )
        self.assertEqual(
            _normalize_menu_key("Raise a Complaint", ""),
            "raise_complaint",
        )
        self.assertEqual(
            _normalize_menu_key("Help / Complaint", ""),
            "help_center",
        )
        self.assertEqual(
            _normalize_menu_key("FAQs / About Kisna", ""),
            "faqs_help",
        )

    def test_handle_raise_complaint_legacy_title(self):
        user_profile = {}
        data = {"phone_number": "919999999999"}
        _handle_menu_selection("Raise Complaint", user_profile, data, "damage_complaint")
        self.assertEqual(data["bot_response"][0]["type"], "flow")
        self.assertEqual(data["bot_response"][0]["flow"], "damage_complaint")

    def test_complaint_cta_click_opens_flow(self):
        processor = ServiceList()
        data = {
            "phone_number": "919999999999",
            "user_profile": {"service_selected": ""},
            "messages": {
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {
                        "id": QuickReplyId.COMPLAINT_REGISTER.value,
                        "title": "Register Complaint",
                    },
                }
            },
        }
        result = asyncio.run(processor.process(data))
        self.assertEqual(result["bot_response"][0]["type"], "flow")
        self.assertEqual(result["bot_response"][0]["flow"], "damage_complaint")

    def test_classifier_menu_shortcut_does_not_call_llm(self):
        processor = Classifier()
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {
                "service_selected": "product_search",
                "chat_history": [{"role": "user", "content": "hi"}],
            },
            "messages": {"text": {"body": "send me the menu"}},
        }
        with patch("kisna_chatbot.processors.classifier.complete_chat") as mocked:
            mocked.side_effect = AssertionError(
                "LLM should not be called for menu requests"
            )
            result = asyncio.run(processor.process(data))
        self.assertEqual(result["bot_response"][0]["type"], "text")
        self.assertEqual(result["classified_category"], "menu_help")

    def test_classifier_complaint_category_sends_flow(self):
        processor = Classifier()
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {"service_selected": "", "chat_history": []},
            "messages": {"text": {"body": "My order arrived damaged"}},
        }
        with patch("kisna_chatbot.processors.classifier.complete_chat") as mocked:
            mocked.return_value = (
                '{"intent":"complaint","confidence":0.9,"language":"en"}'
            )
            result = asyncio.run(processor.process(data))
        self.assertEqual(result["bot_response"][0]["type"], "flow")
        self.assertEqual(result["bot_response"][0]["flow"], "damage_complaint")


if __name__ == "__main__":
    unittest.main()
