"""Tests for image_with_cta WhatsApp sender and ResponseManager dispatch."""

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.processors.response_manager import ResponseManager
from kisna_chatbot.whatsapp_functions.media.send_image_with_cta import (
    _build_interactive_payload,
    send_image_with_buy_button,
    send_image_with_cta,
)


class ImageWithCtaTests(unittest.TestCase):
    def test_interactive_payload_shape(self):
        payload = _build_interactive_payload(
            "https://img.example/ring.jpg",
            "Gold Ring\n₹45,000",
            "https://www.kisna.com/products/gold-ring",
            "Buy on KISNA",
        )
        self.assertEqual(payload["type"], "cta_url")
        self.assertEqual(payload["body"], "Gold Ring\n₹45,000")
        self.assertEqual(payload["display_text"], "Buy on KISNA")
        self.assertEqual(
            payload["url"],
            "https://www.kisna.com/products/gold-ring",
        )
        self.assertEqual(payload["footer"], "KISNA Diamond & Gold")
        self.assertEqual(payload["header"]["type"], "image")
        self.assertEqual(
            payload["header"]["image"]["link"],
            "https://img.example/ring.jpg",
        )
        self.assertNotIn("interactive", payload)

    def test_send_falls_back_to_plain_image_on_http_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "bad request"
        with patch(
            "kisna_chatbot.whatsapp_functions.media.send_image_with_cta.httpx.post",
            return_value=mock_response,
        ) as post_mock, patch(
            "kisna_chatbot.whatsapp_functions.media.send_image_with_cta.send_image_message",
            return_value={"status": "submitted"},
        ) as image_mock:
            result = send_image_with_buy_button(
                "919999999999",
                "https://img.example/ring.jpg",
                "caption",
                "https://www.kisna.com/products/gold-ring",
            )
        post_mock.assert_called_once()
        image_mock.assert_called_once_with(
            phone_number="919999999999",
            bot_response={
                "url": "https://img.example/ring.jpg",
                "caption": "caption",
            },
        )
        self.assertEqual(result["status"], "submitted")

    def test_send_image_with_cta_wrapper(self):
        with patch(
            "kisna_chatbot.whatsapp_functions.media.send_image_with_cta.send_image_with_buy_button",
            return_value={"status": "submitted"},
        ) as buy_mock:
            send_image_with_cta(
                "919999999999",
                {
                    "url": "https://img.example/a.jpg",
                    "caption": "Ring",
                    "cta_url": "https://www.kisna.com/products/ring",
                    "cta_title": "Buy on KISNA",
                },
            )
        buy_mock.assert_called_once_with(
            phone_number="919999999999",
            image_url="https://img.example/a.jpg",
            caption="Ring",
            product_url="https://www.kisna.com/products/ring",
            button_title="Buy on KISNA",
        )

    def test_response_manager_dispatches_image_with_cta(self):
        manager = ResponseManager()
        bot_response = {
            "type": "image_with_cta",
            "url": "https://img.example/a.jpg",
            "caption": "Ring",
            "cta_url": "https://www.kisna.com/products/ring",
        }
        with patch(
            "kisna_chatbot.processors.response_manager.send_image_with_cta",
            return_value={"status": "submitted"},
        ) as send_mock:
            manager._handle_image_with_cta("919999999999", bot_response)
        send_mock.assert_called_once_with(
            phone_number="919999999999",
            bot_response=bot_response,
        )


if __name__ == "__main__":
    unittest.main()
