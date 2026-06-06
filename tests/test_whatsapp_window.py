"""Tests for WhatsApp 24-hour window detection."""

import os
import time
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.processors.response_manager import ResponseManager
from kisna_chatbot.utils.whatsapp_window import WINDOW_OPEN_HOURS, is_window_open


class TestIsWindowOpen:
    def test_missing_last_message_at_is_closed(self):
        assert is_window_open({}) is False
        assert is_window_open(None) is False

    def test_recent_message_is_open(self):
        profile = {"last_message_at": int(time.time()) - 3600}
        assert is_window_open(profile) is True

    def test_stale_message_is_closed(self):
        profile = {
            "last_message_at": int(time.time()) - (WINDOW_OPEN_HOURS + 2) * 3600
        }
        assert is_window_open(profile) is False

    def test_boundary_22h_open(self):
        profile = {"last_message_at": int(time.time()) - 22 * 3600}
        assert is_window_open(profile) is True


class TestResponseManagerWindow:
    def test_sends_template_when_window_closed(self):
        data = {
            "phone_number": "919999999999",
            "user_profile": {
                "last_message_at": int(time.time()) - 25 * 3600,
            },
            "bot_response": [{"type": "text", "text": "Hello"}],
        }
        with (
            patch(
                "kisna_chatbot.processors.response_manager.send_kisna_welcome_template",
                return_value={"status": "submitted"},
            ) as mock_template,
            patch(
                "kisna_chatbot.processors.response_manager.send_text_message_with_retry",
                return_value={"status": "submitted"},
            ) as mock_text,
        ):
            ResponseManager().handle_responses(data)

        mock_template.assert_called_once_with("919999999999")
        mock_text.assert_called_once()

    def test_no_template_when_window_open(self):
        data = {
            "phone_number": "919999999999",
            "user_profile": {"last_message_at": int(time.time()) - 3600},
            "bot_response": [{"type": "text", "text": "Hello"}],
        }
        with (
            patch(
                "kisna_chatbot.processors.response_manager.send_kisna_welcome_template",
            ) as mock_template,
            patch(
                "kisna_chatbot.processors.response_manager.send_text_message_with_retry",
                return_value={"status": "submitted"},
            ) as mock_text,
        ):
            ResponseManager().handle_responses(data)

        mock_template.assert_not_called()
        mock_text.assert_called_once()

    def test_graceful_when_template_not_configured(self):
        data = {
            "phone_number": "919999999999",
            "user_profile": {},
            "bot_response": [{"type": "text", "text": "Hello"}],
        }
        with (
            patch(
                "kisna_chatbot.processors.response_manager.send_kisna_welcome_template",
                return_value=None,
            ) as mock_template,
            patch(
                "kisna_chatbot.processors.response_manager.send_text_message_with_retry",
                return_value={"status": "submitted"},
            ) as mock_text,
        ):
            ResponseManager().handle_responses(data)

        mock_template.assert_called_once()
        mock_text.assert_called_once()
