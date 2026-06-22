"""Tests for greeting menu and complaint flow helpers."""

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
    _MENU_BODY,
    _WELCOME_TEXT,
    _normalize_menu_key,
    build_main_menu_bot_response,
    build_complaint_flow_bot_response,
    build_complaint_entry_cta_bot_response,
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
        self.assertEqual(menu["type"], "list")
        self.assertEqual(menu["list"], "list")
        self.assertIn("explore designs", menu["body"])

    def test_welcome_text_mentions_kia(self):
        self.assertIn("KIA", _WELCOME_TEXT)

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
        )
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["type"], "text")
        self.assertEqual(responses[1]["type"], "list")

    def test_greeting_responses_new_session(self):
        responses = build_greeting_welcome_bot_responses(
            phone_number="919999999999",
            chat_history=[],
        )
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["type"], "text")
        self.assertEqual(responses[1]["type"], "list")

    def test_complaint_flow_shape(self):
        flow = build_complaint_flow_bot_response()
        self.assertEqual(flow["type"], "flow")
        self.assertEqual(flow["flow"], "damage_complaint")

    def test_complaint_entry_cta_shape(self):
        cta = build_complaint_entry_cta_bot_response()
        self.assertEqual(cta["type"], "quickreply")
        self.assertEqual(cta["msgid"], QuickReplyId.COMPLAINT_REGISTER.value)
        self.assertEqual(cta["options"][0]["title"], "Register Complaint")

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
            "raise_complaint",
        )
        self.assertEqual(
            _normalize_menu_key("FAQs / About Kisna", ""),
            "faqs_help",
        )

    def test_handle_raise_complaint_legacy_title(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Raise Complaint", user_profile, data, "damage_complaint")
        self.assertEqual(user_profile["service_selected"], "complaint")
        self.assertNotIn("bot_response", data)

    def test_complaint_cta_click_routes_to_complaint_pipeline(self):
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
        self.assertEqual(result["user_profile"]["service_selected"], "complaint")
        self.assertNotIn("bot_response", result)

    def test_complaint_agent_sends_flow_on_first_entry(self):
        from kisna_chatbot.processors.complaint_agent import ComplaintAgent

        processor = ComplaintAgent()
        data = {
            "phone_number": "919999999999",
            "user_profile": {"service_selected": "complaint"},
            "messages": {"type": "text", "text": {"body": "complaint"}},
        }
        result = asyncio.run(processor.process(data))
        self.assertEqual(result["bot_response"][0]["type"], "flow")
        self.assertEqual(result["bot_response"][0]["flow"], "damage_complaint")

    def test_classifier_menu_shortcut_does_not_call_llm(self):
        processor = Classifier()
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {"service_selected": "product_search", "chat_history": [{"role": "user", "content": "hi"}]},
            "messages": {"text": {"body": "send me the menu"}},
        }
        with patch("kisna_chatbot.processors.classifier.complete_chat") as mocked:
            mocked.side_effect = AssertionError("LLM should not be called for menu requests")
            result = asyncio.run(processor.process(data))
        self.assertEqual(result["bot_response"][0]["type"], "list")
        self.assertEqual(result["classified_category"], "menu_help")

    def test_classifier_complaint_category_routes_to_complaint_pipeline(self):
        processor = Classifier()
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {"service_selected": "", "chat_history": []},
            "messages": {"text": {"body": "My order arrived damaged"}},
        }
        with patch("kisna_chatbot.processors.classifier.complete_chat") as mocked:
            mocked.return_value = '{"category":"complaint"}'
            result = asyncio.run(processor.process(data))
        self.assertEqual(result["user_profile"]["service_selected"], "complaint")
        self.assertNotIn("bot_response", result)


if __name__ == "__main__":
    unittest.main()
