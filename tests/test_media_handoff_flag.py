"""F12: image/audio/video/document routes into the handoff path instead of a
dead-end apology (audit: 5 voice notes in a row got 5 identical refusals;
real customers send photos asking "can you customise this?" and hit a wall),
with a per-burst cooldown so a flurry of media gets one acknowledgement, not
one per file. Unconditional -- no on/off flag."""

import os
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.processors.non_text_handler import (  # noqa: E402
    handle_non_text_message,
)


def _media_data(msg_type: str = "image", **profile_extra) -> dict:
    profile = {"chat_history": [], "service_selected": ""}
    profile.update(profile_extra)
    return {
        "phone_number": "919999999999",
        "messages": {"type": msg_type, "from": "919999999999", "id": "wamid.test"},
        "user_profile": profile,
        "client_id": "kisna",
    }


class MediaHandoffTests(unittest.TestCase):
    def _support_response(self):
        return [{"type": "text", "text": "connecting...", "_compose": "support_handoff"}]

    def test_routes_to_handoff(self) -> None:
        with patch(
            "kisna_chatbot.processors.support_handler.build_expert_support_bot_response",
            return_value=self._support_response(),
        ) as build:
            data = _media_data("image")
            result = handle_non_text_message(data)
            self.assertIsNone(result)
            texts = [r["text"] for r in data["bot_response"]]
            self.assertIn("can't view images", texts[0])
            self.assertIn("connecting...", texts)
            build.assert_called_once()

    def test_covers_audio_video_document(self) -> None:
        with patch(
            "kisna_chatbot.processors.support_handler.build_expert_support_bot_response",
            return_value=self._support_response(),
        ):
            for msg_type in ("audio", "video", "document"):
                data = _media_data(msg_type)
                handle_non_text_message(data)
                self.assertIn("bot_response", data, msg_type)

    def test_second_media_within_cooldown_is_silent(self) -> None:
        with patch(
            "kisna_chatbot.processors.support_handler.build_expert_support_bot_response",
            return_value=self._support_response(),
        ):
            data1 = _media_data("audio")
            handle_non_text_message(data1)
            self.assertIn("bot_response", data1)

            # Same burst, same profile state (media_fallback_last_at carried over).
            data2 = _media_data(
                "audio", media_fallback_last_at=data1["user_profile"]["media_fallback_last_at"]
            )
            result2 = handle_non_text_message(data2)
            self.assertEqual(result2, "silent")
            self.assertNotIn("bot_response", data2)

    def test_media_after_cooldown_expires_gets_a_fresh_ack(self) -> None:
        with patch(
            "kisna_chatbot.processors.support_handler.build_expert_support_bot_response",
            return_value=self._support_response(),
        ):
            stale = time.time() - 120  # well past the 60s cooldown
            data = _media_data("audio", media_fallback_last_at=stale)
            result = handle_non_text_message(data)
            self.assertIsNone(result)
            self.assertIn("bot_response", data)

    def test_non_media_types_unaffected(self) -> None:
        # location/sticker/reaction/text/interactive keep their own handling.
        data = _media_data("sticker")
        handle_non_text_message(data)
        self.assertNotIn("connecting", data["bot_response"][0]["text"])


if __name__ == "__main__":
    unittest.main()
