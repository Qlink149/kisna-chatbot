"""Tests for non-text WhatsApp inbound handling."""

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.models.enums import QuickReplyId
from kisna_chatbot.processors.non_text_handler import handle_non_text_message
from kisna_chatbot.processors.service_list import handle_non_text_quick_reply


def _base_data(msg_type: str, **extra) -> dict:
    messages = {"type": msg_type, "from": "919999999999", "id": "wamid.test"}
    messages.update(extra)
    return {
        "phone_number": "919999999999",
        "messages": messages,
        "user_profile": {"chat_history": [], "service_selected": ""},
        "client_id": "kisna",
    }


class TestNonTextHandler:
    def test_text_not_handled(self):
        data = _base_data("text", text={"body": "hello"})
        assert handle_non_text_message(data) is None
        assert "bot_response" not in data

    def test_interactive_not_handled(self):
        data = _base_data(
            "interactive",
            interactive={"type": "button_reply", "button_reply": {"title": "Hi"}},
        )
        assert handle_non_text_message(data) is None

    def test_image_reply(self):
        data = _base_data("image", image={"id": "img123"})
        assert handle_non_text_message(data) is None
        assert len(data["bot_response"]) == 1
        assert data["bot_response"][0]["type"] == "quickreply"
        assert "unable to view images" in data["bot_response"][0]["text"].lower()
        assert data["bot_response"][0]["msgid"] == QuickReplyId.NON_TEXT_BROWSE.value

    def test_audio_reply(self):
        data = _base_data("audio", audio={"id": "aud123"})
        handle_non_text_message(data)
        assert "voice notes" in data["bot_response"][0]["text"].lower()

    def test_video_reply(self):
        data = _base_data("video", video={"id": "vid123"})
        handle_non_text_message(data)
        assert "voice notes" in data["bot_response"][0]["text"].lower()

    def test_sticker_reply(self):
        data = _base_data("sticker", sticker={"id": "stk123"})
        handle_non_text_message(data)
        assert "Lovely" in data["bot_response"][0]["text"]

    def test_reaction_silent(self):
        data = _base_data("reaction", reaction={"emoji": "👍"})
        assert handle_non_text_message(data) == "silent"
        assert "bot_response" not in data

    def test_location_routes_store(self):
        data = _base_data(
            "location",
            location={"latitude": 19.076, "longitude": 72.877},
        )
        assert handle_non_text_message(data) == "route_store"
        assert data["inbound_location"] == {"lat": 19.076, "lng": 72.877}
        assert data["user_profile"]["service_selected"] == SL.AD_FLOW.value
        assert data["user_profile"]["awaiting_store_pincode"] is False

    def test_location_without_coords_asks_pincode(self):
        data = _base_data("location", location={})
        handle_non_text_message(data)
        assert "PIN code" in data["bot_response"][0]["text"]
        assert data["user_profile"]["awaiting_store_pincode"] is True

    def test_contacts_reply(self):
        data = _base_data("contacts", contacts=[{"name": {"formatted_name": "A"}}])
        handle_non_text_message(data)
        assert data["bot_response"][0]["type"] == "quickreply"

    def test_non_text_quick_reply_browse(self):
        user_profile = {}
        data = {"_non_text_button_title": "Browse Jewellery"}
        assert handle_non_text_quick_reply(QuickReplyId.NON_TEXT_BROWSE.value, user_profile, data)
        assert user_profile["service_selected"] == SL.PRODUCT_SEARCH.value

    def test_non_text_quick_reply_open_menu(self):
        user_profile = {}
        data = {"_non_text_button_title": "Open Menu"}
        assert handle_non_text_quick_reply(QuickReplyId.NON_TEXT_BROWSE.value, user_profile, data)
        assert data["bot_response"][0]["type"] == "list"


def test_process_message_image_skips_initial_pipeline():
    from kisna_chatbot import main as main_mod

    request_data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "850788844795304"},
                            "contacts": [{"profile": {"name": "Test"}}],
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "wamid.img.test",
                                    "type": "image",
                                    "image": {"id": "img1"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    async def _run():
        with (
            patch.object(main_mod, "mark_inbound_processed", return_value=True),
            patch.object(main_mod, "get_takeover_status", return_value=None),
            patch.object(main_mod, "UserRegistration") as mock_reg_cls,
            patch.object(main_mod, "InitialPipeline") as mock_initial,
            patch.object(main_mod, "save_to_mongo"),
            patch.object(main_mod, "save_response_time"),
            patch.object(main_mod.ResponseManager, "handle_responses") as mock_send,
        ):
            mock_reg = MagicMock()
            mock_reg.process = AsyncMock(
                side_effect=lambda d: {
                    **d,
                    "user_profile": {"chat_history": [], "service_selected": ""},
                }
            )
            mock_reg_cls.return_value = mock_reg

            await main_mod.process_message(request_data, app_state=None)

            mock_initial.assert_not_called()
            mock_send.assert_called_once()

    asyncio.run(_run())


def test_process_message_reaction_silent():
    from kisna_chatbot import main as main_mod

    request_data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "850788844795304"},
                            "contacts": [],
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "wamid.react.test",
                                    "type": "reaction",
                                    "reaction": {"emoji": "❤️"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }

    async def _run():
        with (
            patch.object(main_mod, "mark_inbound_processed", return_value=True),
            patch.object(main_mod, "get_takeover_status", return_value=None),
            patch.object(main_mod, "UserRegistration") as mock_reg_cls,
            patch.object(main_mod, "InitialPipeline") as mock_initial,
            patch.object(main_mod, "touch_last_message_at") as mock_touch,
            patch.object(main_mod.ResponseManager, "handle_responses") as mock_send,
        ):
            mock_reg = MagicMock()
            mock_reg.process = AsyncMock(
                side_effect=lambda d: {
                    **d,
                    "user_profile": {"chat_history": [], "service_selected": ""},
                }
            )
            mock_reg_cls.return_value = mock_reg

            await main_mod.process_message(request_data, app_state=None)

            mock_initial.assert_not_called()
            mock_send.assert_not_called()
            mock_touch.assert_called_once()

    asyncio.run(_run())
