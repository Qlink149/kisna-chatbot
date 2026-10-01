"""Follow-ups to the opening messages: the recent-search question for returning
users, the funnel question after the new-user welcome, and one chat_messages
row per WhatsApp message sent."""

import os
import time
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from kisna_chatbot.processors.opening_messages import apply_opening_rules  # noqa: E402
from kisna_chatbot.processors.service_list import (  # noqa: E402
    build_greeting_welcome_bot_responses,
    recent_search_question,
)
from kisna_chatbot.processors.shopping_wizard import build_step_prompt  # noqa: E402
from kisna_chatbot.utils.format_chathistory import format_outbound_messages  # noqa: E402

AT_14 = datetime(2026, 10, 1, 14, 0)
AT_23 = datetime(2026, 10, 1, 23, 0)
HISTORY = [{"role": "user", "content": "hi"}]


def _epoch(dt: datetime) -> int:
    from kisna_chatbot.utils.support_hours import IST

    return int(dt.replace(tzinfo=IST).timestamp())


def _profile(minutes_ago: int, base: datetime = AT_14, **filters) -> dict:
    return {
        "username": "Rajendra Singh Asoliya",
        "last_search_at": _epoch(base) - minutes_ago * 60,
        "last_search_filters": filters,
    }


class RecentSearchQuestionTests(unittest.TestCase):
    def _greet(self, profile, now=AT_14):
        return build_greeting_welcome_bot_responses(chat_history=HISTORY, user_profile=profile, now=now)[0]["text"]

    def test_replaces_the_closing_question_one_question_only(self):
        text = self._greet(_profile(30, category="ring"))
        self.assertEqual(
            text,
            "Good Afternoon, Rajendra! 👋 Welcome back to Kisna Diamond & Gold. 💎\n\n"
            "Would you like to keep exploring rings? 😊",
        )
        self.assertNotIn("How may I assist you today?", text)

    def test_night_form(self):
        self.assertEqual(
            self._greet(_profile(30, base=AT_23, category="earring"), now=AT_23),
            "Welcome back, Rajendra! 👋\n\nWould you like to keep exploring earrings? 😊",
        )

    def test_only_within_two_hours(self):
        self.assertTrue(self._greet(_profile(119, category="ring")).endswith("keep exploring rings? 😊"))
        self.assertTrue(self._greet(_profile(121, category="ring")).endswith("How may I assist you today? 😊"))
        self.assertTrue(self._greet({"username": "Rajendra"}).endswith("How may I assist you today? 😊"))

    def test_labels(self):
        now = _epoch(AT_14)
        cases = [
            ({"category": "ring", "material_type": "gold", "max_price": 50000}, "gold rings under ₹50,000"),
            ({"category": "necklace", "clara_category_override": "chain"}, "chains"),
            ({"category": "mangalsutra", "min_price": 20000, "max_price": 60000},
             "mangalsutra between ₹20,000 and ₹60,000"),
            ({"material_type": "diamond"}, "diamond jewellery"),
            ({"category": "bangle", "min_price": 30000}, "bangles above ₹30,000"),
        ]
        for filters, label in cases:
            with self.subTest(filters=filters):
                profile = {"last_search_at": now - 60, "last_search_filters": filters}
                self.assertEqual(recent_search_question(profile, now), f"Would you like to keep exploring {label}? 😊")

    def test_nothing_to_resume(self):
        now = _epoch(AT_14)
        self.assertIsNone(recent_search_question({"last_search_at": now - 60, "last_search_filters": {}}, now))
        self.assertIsNone(recent_search_question({"last_search_at": "x", "last_search_filters": {"category": "ring"}}, now))

    def test_new_user_welcome_is_unchanged_by_a_search(self):
        text = build_greeting_welcome_bot_responses(chat_history=[], user_profile=_profile(5, category="ring"), now=AT_14)[0]["text"]
        self.assertTrue(text.endswith("How may I assist you today? 😊"))
        self.assertNotIn("keep exploring", text)


class FunnelAfterWelcomeTests(unittest.TestCase):
    def _turn(self, new_user):
        data = {"phone_number": "919812345678", "_new_user": new_user, "user_profile": {"username": "Asha"},
                "bot_response": [build_step_prompt("category")]}
        apply_opening_rules(data, now=AT_14)
        return [r["text"] for r in data["bot_response"]]

    def test_new_user_second_message_is_the_narrower_question(self):
        texts = self._turn(True)
        self.assertEqual(len(texts), 2)
        self.assertTrue(texts[0].startswith("Good Afternoon! 🌤️"))
        self.assertEqual(texts[1], "Which type of jewellery are you looking for? 💍 e.g. rings, earrings, necklaces…")

    def test_returning_user_keeps_the_funnel_question(self):
        self.assertEqual(self._turn(False), ["What are you looking for today? e.g. rings, earrings, necklaces…"])

    def test_other_replies_untouched(self):
        data = {"_new_user": True, "user_profile": {}, "bot_response": [
            {"type": "text", "text": "Our stores open at 10:30 AM.", "_compose": "store_info"}]}
        apply_opening_rules(data, now=AT_14)
        self.assertEqual(data["bot_response"][1]["text"], "Our stores open at 10:30 AM.")


class OneRowPerWhatsAppMessageTests(unittest.TestCase):
    TURN = [
        {"type": "text", "text": "Welcome!", "_compose": "greeting_new"},
        {"type": "skip"},
        {"type": "text", "text": ""},
        {"type": "quickreply", "text": "Who is it for?", "options": [{"title": "Female"}, {"title": "Male"}]},
        {"type": "media", "media_type": "image", "urls": [
            {"url": "https://x/1.jpg", "caption": "Ring A"}, {"url": "https://x/2.jpg", "caption": "Ring B"},
            {"url": "https://x/3.jpg", "caption": "Ring C"}]},
        {"type": "cta_url", "text": "See all", "display_text": "See Collection", "url": "https://kisna.com/x"},
    ]

    def test_one_entry_per_message_in_send_order(self):
        rows = format_outbound_messages(self.TURN, "919812345678", request_id="rid-1", timestamp=100)
        self.assertEqual([r["content"] for r in rows], [
            "Welcome!",
            "Who is it for?\n[Options: Female, Male]",
            "Showed product images - Ring A",
            "Showed product images - Ring B",
            "Showed product images - Ring C",
            "See all\n[Button: See Collection]",
        ])
        self.assertTrue(all(r["role"] == "assistant" and r["request_id"] == "rid-1" and r["timestamp"] == 100 for r in rows))

    def test_empty_turn_writes_no_bot_row(self):
        self.assertEqual(format_outbound_messages([], "9198"), [])
        self.assertEqual(format_outbound_messages(None, "9198"), [])
        self.assertEqual(format_outbound_messages([{"type": "skip"}], "9198"), [])

    @patch("kisna_chatbot.database.db_utils.users")
    def test_save_writes_rows_per_message_but_keeps_one_history_turn(self, mock_users):
        from kisna_chatbot.database import db_utils

        mock_users.find_one_and_update.return_value = {"phone_number": "919812345678"}
        data = {
            "phone_number": "919812345678", "client_id": "kisna", "request_id": "rid-9",
            "messages": {"type": "text", "text": {"body": "Hi, I'm looking for jewellery"}},
            "bot_response": [
                {"type": "text", "text": "Good Afternoon! … How may I assist you today? 😊", "_compose": "greeting_new"},
                {"type": "text", "text": "Which type of jewellery are you looking for? 💍", "_compose": "wizard_category"},
            ],
            "user_profile": {"chat_history": []},
        }
        with patch.object(db_utils, "dual_write_chat_entries") as dual:
            db_utils.save_to_mongo(data)
        written = dual.call_args[0][2]
        self.assertEqual([(r["role"], r["content"]) for r in written], [
            ("user", "Hi, I'm looking for jewellery"),
            ("assistant", "Good Afternoon! … How may I assist you today? 😊"),
            ("assistant", "Which type of jewellery are you looking for? 💍"),
        ])
        self.assertEqual({r["timestamp"] for r in written}, {written[0]["timestamp"]})
        self.assertTrue(all(r["request_id"] == "rid-9" for r in written))
        history = mock_users.find_one_and_update.call_args[0][1]["$set"]["chat_history"]
        self.assertEqual([h["role"] for h in history], ["user", "assistant"])  # model context: one turn
        self.assertIn("How may I assist you today? 😊\nWhich type of jewellery", history[1]["content"])

    def test_rows_keep_send_order_on_the_same_second(self):
        # The page query sorts by (ts, _id): ids made in insert order sort in
        # insert order, so a turn's messages never shuffle in the dashboard.
        from bson import ObjectId

        ids = [ObjectId() for _ in range(5)]
        self.assertEqual(sorted(ids), ids)
        self.assertEqual(sorted(str(i) for i in ids), [str(i) for i in ids])

    def test_dual_write_ids_are_distinct_per_row(self):
        from kisna_chatbot.database import db_utils

        with patch.object(db_utils, "chat_messages") as col:
            ids = db_utils.dual_write_chat_entries(
                "9198", "kisna", format_outbound_messages(self.TURN, "9198", request_id="r", timestamp=int(time.time())))
        self.assertEqual(len(ids), 6)
        self.assertEqual(len(set(ids)), 6)
        self.assertEqual(col.insert_one.call_count, 6)


if __name__ == "__main__":
    unittest.main()
