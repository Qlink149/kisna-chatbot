"""How a turn opens: new vs returning user, greeting only vs with an intent
(processors/opening_messages.py, service_list greeting builders)."""

import os
import unittest
from datetime import datetime

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from kisna_chatbot.processors.opening_messages import (  # noqa: E402
    apply_opening_rules,
    strip_greeting_opener,
)
from kisna_chatbot.processors.service_list import (  # noqa: E402
    build_greeting_welcome_bot_responses,
    greeting_first_name,
)
from kisna_chatbot.processors.shopping_wizard import build_step_prompt  # noqa: E402

AT_09 = datetime(2026, 10, 1, 9, 0)
AT_14 = datetime(2026, 10, 1, 14, 0)
AT_23 = datetime(2026, 10, 1, 23, 0)

BODY = (
    "Namaste and welcome to Kisna Diamond & Gold. 💎\n\n"
    "I’m KIA – your personal jewellery assistant, and I’m delighted to assist you.\n\n"
    "Whether you’re exploring our latest collections, looking for the perfect jewellery, "
    "checking offers, tracking an order, or need any assistance — I’m here to make your "
    "Kisna experience simple and delightful. ✨\n\n"
    "How may I assist you today? 😊"
)
NEW_WELCOME = {
    AT_09: "Good Morning! ☀️ Hope you’re doing well!\n\n" + BODY,
    AT_14: "Good Afternoon! 🌤️ Hope you’re having a good day!\n\n" + BODY,
    AT_23: BODY,
}
RETURNING = {
    AT_09: "Good Morning, Rajendra! 👋 Welcome back to Kisna Diamond & Gold. 💎\n\nHow may I assist you today? 😊",
    AT_14: "Good Afternoon, Rajendra! 👋 Welcome back to Kisna Diamond & Gold. 💎\n\nHow may I assist you today? 😊",
    AT_23: "Welcome back, Rajendra! 👋\n\nHow may I assist you today? 😊",
}
WIZARD_REPLY = "What are you looking for today? e.g. rings, earrings, necklaces…"
PROFILE = {"username": "Rajendra Singh Asoliya"}
HISTORY = [{"role": "user", "content": "hi"}]


def _turn(new_user: bool, responses: list[dict]) -> dict:
    return {"phone_number": "919812345678", "_new_user": new_user, "user_profile": dict(PROFILE),
            "bot_response": responses}


class NewUserTests(unittest.TestCase):
    def test_greeting_only_is_the_clients_welcome_in_one_message(self):
        for now, text in NEW_WELCOME.items():
            with self.subTest(now=now):
                responses = build_greeting_welcome_bot_responses(chat_history=[], user_profile=PROFILE, now=now)
                data = _turn(True, responses)
                apply_opening_rules(data, now=now)
                self.assertEqual([r["text"] for r in data["bot_response"]], [text])
                self.assertEqual(data["bot_response"][0]["_compose"], "greeting_new")

    def test_with_intent_is_welcome_then_reply_as_two_messages(self):
        for now, welcome in NEW_WELCOME.items():
            with self.subTest(now=now):
                data = _turn(True, [build_step_prompt("category")])  # "Hi! 👋 What are you looking for…"
                apply_opening_rules(data, now=now)
                texts = [r["text"] for r in data["bot_response"]]
                self.assertEqual(texts, [welcome, WIZARD_REPLY])
                self.assertEqual(data["bot_response"][0]["_compose"], "greeting_new")
                self.assertEqual(data["bot_response"][1]["_compose"], "wizard_category")

    def test_with_intent_keeps_every_reply_message(self):
        reply = [{"type": "text", "text": "Hello! 😊 Our stores are open 10:30 AM–8 PM.", "_compose": "x"},
                 {"type": "cta_url", "text": "Find a store", "url": "https://www.kisna.com/store"}]
        data = _turn(True, reply)
        apply_opening_rules(data, now=AT_14)
        self.assertEqual(len(data["bot_response"]), 3)
        self.assertEqual(data["bot_response"][1]["text"], "Our stores are open 10:30 AM–8 PM.")
        self.assertEqual(data["bot_response"][2]["text"], "Find a store")


class ReturningUserTests(unittest.TestCase):
    def test_greeting_only_is_one_message_with_first_name(self):
        for now, text in RETURNING.items():
            with self.subTest(now=now):
                responses = build_greeting_welcome_bot_responses(chat_history=HISTORY, user_profile=PROFILE, now=now)
                data = _turn(False, responses)
                apply_opening_rules(data, now=now)
                self.assertEqual([r["text"] for r in data["bot_response"]], [text])
                self.assertEqual(data["bot_response"][0]["_compose"], "greeting_return")
                self.assertNotIn("Singh", text)

    def test_with_intent_has_no_greeting(self):
        for now in (AT_09, AT_14, AT_23):
            with self.subTest(now=now):
                data = _turn(False, [build_step_prompt("category")])
                apply_opening_rules(data, now=now)
                self.assertEqual([r["text"] for r in data["bot_response"]], [WIZARD_REPLY])

    def test_name_omitted_with_its_comma(self):
        for profile in ({}, {"username": ""}, {"username": "Raj123"}, {"username": "😊 Priya"},
                        {"username": "Abcdefghijklmnopqrstu"}):
            with self.subTest(profile=profile):
                text = build_greeting_welcome_bot_responses(chat_history=HISTORY, user_profile=profile, now=AT_09)[0]["text"]
                self.assertTrue(text.startswith("Good Morning! 👋 Welcome back to Kisna Diamond & Gold. 💎"), text)
                night = build_greeting_welcome_bot_responses(chat_history=HISTORY, user_profile=profile, now=AT_23)[0]["text"]
                self.assertTrue(night.startswith("Welcome back! 👋\n\nHow may I assist you today? 😊"), night)


class FirstNameTests(unittest.TestCase):
    def test_first_word_title_cased(self):
        cases = {
            "Rajendra Singh Asoliya": "Rajendra",
            "RAJENDRA singh": "Rajendra",
            "priya": "Priya",
            "  asha  ": "Asha",
            "Abcdefghijklmnopqrst": "Abcdefghijklmnopqrst",  # 20 chars: allowed
            "प्रिया शर्मा": "प्रिया",
        }
        for raw, want in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(greeting_first_name({"username": raw}), want)

    def test_rejected_names(self):
        for raw in ("", "   ", "Raj123", "R.K.", "😊", "Abcdefghijklmnopqrstu", "user", "Customer", None):
            with self.subTest(raw=raw):
                self.assertIsNone(greeting_first_name({"username": raw}))


class StripGreetingOpenerTests(unittest.TestCase):
    def test_openers_removed(self):
        cases = {
            "Hi! 👋 What are you looking for today?": "What are you looking for today?",
            "Hello! Our stores open at 10:30 AM.": "Our stores open at 10:30 AM.",
            "Hey! 😊 sure, here are some rings.": "Sure, here are some rings.",
            "Namaste! 🙏 Kisna offers 18KT gold.": "Kisna offers 18KT gold.",
            "Hello there! Here you go.": "Here you go.",
            "Hi Priya! Here are some rings.": "Here are some rings.",
            "नमस्ते! 🙏 आपको क्या चाहिए?": "आपको क्या चाहिए?",
        }
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(strip_greeting_opener(text), want)

    def test_non_openers_untouched(self):
        for text in ("Highlights of our collection are below.", "Hello", "Hi! 👋",
                     "Absolutely! 💍 Kisna offers 18KT.", "His and hers rings are here."):
            with self.subTest(text=text):
                self.assertEqual(strip_greeting_opener(text), text)


class LanguageTests(unittest.TestCase):
    """Every language: the same structure, translated faithfully."""

    def _localize(self, data):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from kisna_chatbot.processors.opening_messages import strip_reply_opener_after_localize
        from kisna_chatbot.utils import reply_composer

        with patch.object(reply_composer, "compose", new_callable=AsyncMock,
                          side_effect=lambda key, text, **k: f"[hi:{key}] {text}"), \
             patch.object(reply_composer, "narrate", new_callable=AsyncMock,
                          side_effect=lambda text, **k: "नमस्ते! 🙏 " + text):
            asyncio.run(reply_composer.localize_bot_responses(data))
        strip_reply_opener_after_localize(data)
        return [r["text"] for r in data["bot_response"]]

    def test_hindi_new_user_with_intent_keeps_two_messages(self):
        data = _turn(True, [build_step_prompt("category")])
        data["user_profile"]["language"] = "hi"
        data["messages"] = {"type": "text", "text": {"body": "Hi, mujhe ring chahiye"}}
        apply_opening_rules(data, now=AT_09)
        texts = self._localize(data)
        self.assertEqual(len(texts), 2)
        self.assertEqual(texts[0], "[hi:greeting_new] " + NEW_WELCOME[AT_09])  # whole welcome, translated as one
        self.assertEqual(texts[1], "[hi:wizard_category] " + WIZARD_REPLY)

    def test_a_reply_rewritten_with_a_greeting_is_stripped_again(self):
        # narrate() (warm, personality-tagged lines) can greet again.
        data = _turn(False, [{"type": "text", "text": "Could you tell me your budget?", "_compose": "slot_fill"}])
        data["user_profile"]["language"] = "hi"
        data["messages"] = {"type": "text", "text": {"body": "ring chahiye"}}
        apply_opening_rules(data, now=AT_14)
        self.assertEqual(self._localize(data), ["Could you tell me your budget?"])

    def test_greeting_turn_is_never_restripped(self):
        from kisna_chatbot.processors.opening_messages import strip_reply_opener_after_localize

        data = _turn(False, [{"type": "text", "text": "Hello! 👋 Welcome back.", "_compose": "greeting_return"}])
        apply_opening_rules(data, now=AT_14)
        strip_reply_opener_after_localize(data)
        self.assertEqual(data["bot_response"][0]["text"], "Hello! 👋 Welcome back.")


class NewUserFlagTests(unittest.TestCase):
    def test_recorded_when_the_message_arrives(self):
        from kisna_chatbot.main import _stamp_inbound

        new = {"user_profile": {"chat_history": []}, "_inbound_at": 1}
        old = {"user_profile": {"chat_history": [{"role": "user", "content": "hi"}]}, "_inbound_at": 1}
        _stamp_inbound(new)
        _stamp_inbound(old)
        self.assertTrue(new["_new_user"])
        self.assertFalse(old["_new_user"])


if __name__ == "__main__":
    unittest.main()
