"""ResponseManager: Markdown-to-WhatsApp emphasis sanitization.

Regression: the LLM (GeneralAgent especially) frequently generates standard
Markdown **bold** despite prompt instructions to use WhatsApp's own syntax
-- confirmed live, 5/6 runs of one KB query used it, a different message
shape every time. WhatsApp only understands a single-asterisk pair as bold;
a double pair renders as literal, visible asterisks (the reported bug:
"*KMR-Amount*" showing with asterisks intact in the chat bubble). Fixed
centrally in the one place every outbound response passes through before
send, not per-prompt, so no future free-generation path can reintroduce it.
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
from kisna_chatbot.processors.response_manager import (  # noqa: E402
    _fix_whatsapp_markdown,
    _sanitize_response_text,
)


class WhatsAppMarkdownSanitizeTests(unittest.TestCase):
    def test_double_asterisk_bold_becomes_single(self):
        self.assertEqual(
            _fix_whatsapp_markdown("**Two variants**: KMR-Amount and KMR-Gram."),
            "*Two variants*: KMR-Amount and KMR-Gram.",
        )

    def test_multiple_bold_spans_in_one_message(self):
        text = (
            "- **Two variants**: KMR-Amount and KMR-Gram.\n"
            "- **Join**: Visit any Kisna store."
        )
        fixed = _fix_whatsapp_markdown(text)
        self.assertNotIn("**", fixed)
        self.assertIn("*Two variants*", fixed)
        self.assertIn("*Join*", fixed)

    def test_already_correct_single_asterisk_is_untouched(self):
        text = "Already correct *single* asterisk text stays *unchanged*."
        self.assertEqual(_fix_whatsapp_markdown(text), text)

    def test_plain_text_is_untouched(self):
        text = "No asterisks here at all."
        self.assertEqual(_fix_whatsapp_markdown(text), text)

    def test_mixed_single_and_double_in_one_message(self):
        fixed = _fix_whatsapp_markdown("Mixed: *fine* and **broken** in one message.")
        self.assertEqual(fixed, "Mixed: *fine* and *broken* in one message.")

    def test_none_and_empty_are_safe(self):
        self.assertIsNone(_fix_whatsapp_markdown(None))
        self.assertEqual(_fix_whatsapp_markdown(""), "")

    def test_sanitize_response_text_fixes_text_field(self):
        response = {"type": "text", "text": "**bold**"}
        sanitized = _sanitize_response_text(response)
        self.assertEqual(sanitized["text"], "*bold*")

    def test_sanitize_response_text_fixes_caption_field(self):
        response = {"type": "image_with_cta", "caption": "**bold caption**"}
        sanitized = _sanitize_response_text(response)
        self.assertEqual(sanitized["caption"], "*bold caption*")

    def test_sanitize_response_text_leaves_other_fields_alone(self):
        response = {"type": "quickreply", "text": "pick one", "msgid": "wizard$gender"}
        sanitized = _sanitize_response_text(response)
        self.assertEqual(sanitized["msgid"], "wizard$gender")


if __name__ == "__main__":
    unittest.main()
