"""format_assistant must always put a separator between reply segments.

Live, real tester traffic (2026-08-24, phones 919930728009 and 919967004767):
the personalised greeting narration and the wizard's category prompt are two
separate `bot_response` items, both `type: "text"`. `format_assistant` had
one branch -- plain "text" (and quick_reply's own text) -- that appended with
nothing in front, while every sibling branch (list/flow/media/image_with_cta/
cta_url/the fallback) already prepended "\n". Two adjacent text items glued
into one word in the stored chat history: "...today?Hi! ...".

WhatsApp itself was unaffected -- ResponseManager sends each bot_response
item as its own message -- but the corrupted string is exactly what
format_recent_history_str feeds back into the classifier's own context on
every later turn.

Fix: one separator, applied once before whatever a segment adds, rather than
per-branch -- closing the gap for every type combination, not just this one.
"""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401,E402
from kisna_chatbot.utils.format_chathistory import format_assistant  # noqa: E402


class ConsecutiveTextSegmentsTests(unittest.TestCase):
    def test_the_exact_live_failure_is_fixed(self):
        body = format_assistant(
            [
                {
                    "type": "text",
                    "text": (
                        "Hi there! Welcome. How can I help make your "
                        "shopping experience wonderful today?"
                    ),
                },
                {
                    "type": "text",
                    "text": (
                        "Hi! What are you looking for today? e.g. rings, "
                        "earrings, necklaces..."
                    ),
                },
            ],
            "919999999999",
        )
        self.assertNotIn("today?Hi", body)
        self.assertIn("today?\nHi", body)

    def test_text_then_quickreply_also_gets_a_separator(self):
        # quick_reply's own text branch had the identical gap -- untested
        # until now because a text item never preceded a quickreply item in
        # the fixtures that existed before this.
        body = format_assistant(
            [
                {"type": "text", "text": "Understood, looking for gold rings."},
                {
                    "type": "quickreply",
                    "text": "Who is it for?",
                    "options": [{"title": "Male"}, {"title": "Female"}],
                },
            ],
            "919999999999",
        )
        self.assertNotIn("rings.Who", body)
        self.assertIn("rings.\nWho is it for?", body)
        self.assertIn("[Options: Male, Female]", body)

    def test_a_single_text_item_is_unchanged(self):
        body = format_assistant(
            [{"type": "text", "text": "Just one message."}], "919999999999"
        )
        self.assertEqual(body, "Just one message.")

    def test_every_other_branch_keeps_its_own_separator_behaviour(self):
        # The existing branches already prepended "\n" themselves; the fix
        # must not double it up now that a shared guard runs first.
        body = format_assistant(
            [
                {"type": "text", "text": "Here you go."},
                {"type": "list", "list": "products"},
            ],
            "919999999999",
        )
        self.assertEqual(body, "Here you go.\nSent list - [products]")
        self.assertNotIn("\n\n", body)

    def test_skip_items_consume_no_separator(self):
        body = format_assistant(
            [
                {"type": "text", "text": "First."},
                {"type": "skip"},
                {"type": "text", "text": "Second."},
            ],
            "919999999999",
        )
        self.assertEqual(body, "First.\nSecond.")


if __name__ == "__main__":
    unittest.main()
