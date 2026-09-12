"""format_user's media branches -- the fix for the Gupshup-URL leak.

Before this fix, format_user had no image/audio/video/document branch and
fell through to str(user_message), which dumped the entire raw payload --
including Gupshup's public media URL -- into chat_messages.content, the
operator dashboard, and every later LLM prompt. This file locks that fixed
behaviour in: clean, stable text only, never the URL.
"""

import os
import unittest

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from kisna_chatbot.utils.format_chathistory import format_chat_history, format_user  # noqa: E402

_LEAKY_URL = "https://filemanager.gupshup.io/wa/99e74d4d/wa/media/123?download=false"


class FormatUserMediaTests(unittest.TestCase):
    def test_image_with_caption(self):
        msg = {"type": "image", "image": {"id": "1", "mime_type": "image/jpeg", "url": _LEAKY_URL, "caption": "in rose gold?"}}
        self.assertEqual(format_user(msg, "919999999999"), "[Image] in rose gold?")

    def test_image_without_caption(self):
        msg = {"type": "image", "image": {"id": "1", "mime_type": "image/jpeg", "url": _LEAKY_URL}}
        self.assertEqual(format_user(msg, "919999999999"), "[Image]")

    def test_audio_is_voice_note(self):
        msg = {"type": "audio", "audio": {"id": "1", "mime_type": "audio/ogg; codecs=opus", "url": _LEAKY_URL, "voice": True}}
        self.assertEqual(format_user(msg, "919999999999"), "[Voice note]")

    def test_video_with_caption(self):
        msg = {"type": "video", "video": {"id": "1", "mime_type": "video/mp4", "url": _LEAKY_URL, "caption": "see this"}}
        self.assertEqual(format_user(msg, "919999999999"), "[Video] see this")

    def test_document_uses_filename(self):
        msg = {"type": "document", "document": {"id": "1", "mime_type": "application/pdf", "url": _LEAKY_URL, "filename": "quote.pdf"}}
        self.assertEqual(format_user(msg, "919999999999"), "[Document] quote.pdf")

    def test_document_without_filename(self):
        msg = {"type": "document", "document": {"id": "1", "mime_type": "application/pdf", "url": _LEAKY_URL}}
        self.assertEqual(format_user(msg, "919999999999"), "[Document]")

    def test_no_gupshup_url_leaks_for_any_media_type(self):
        for msg_type in ("image", "audio", "video", "document"):
            payload = {"id": "1", "mime_type": "x/x", "url": _LEAKY_URL, "caption": "hi", "filename": "f.pdf"}
            msg = {"type": msg_type, msg_type: payload}
            content = format_user(msg, "919999999999")
            self.assertNotIn("filemanager.gupshup.io", content, msg_type)
            self.assertNotIn(_LEAKY_URL, content, msg_type)

    def test_unaffected_message_types_unchanged(self):
        # Guard the fix's blast radius: text/interactive branches untouched.
        self.assertEqual(
            format_user({"type": "text", "text": {"body": "hello"}}, "919999999999"), "hello"
        )
        self.assertEqual(
            format_user(
                {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"title": "Yes"}}},
                "919999999999",
            ),
            "User Selected - [Yes] from quick reply",
        )

    def test_format_chat_history_attaches_media_to_user_entry(self):
        media = {"kind": "image", "b2_key": "kisna/inbound/x.jpg"}
        entries = format_chat_history(
            user={"type": "image", "image": {"id": "1", "mime_type": "image/jpeg", "url": _LEAKY_URL}},
            assistant=[{"type": "text", "text": "..."}],
            phone_number="919999999999",
            media=media,
        )
        self.assertEqual(entries[0]["media"], media)
        self.assertNotIn("media", entries[1])  # assistant entry untouched

    def test_format_chat_history_no_media_key_when_none(self):
        entries = format_chat_history(
            user={"type": "text", "text": {"body": "hi"}},
            assistant=[{"type": "text", "text": "hello"}],
            phone_number="919999999999",
        )
        self.assertNotIn("media", entries[0])


if __name__ == "__main__":
    unittest.main()
