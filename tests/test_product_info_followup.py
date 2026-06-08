"""Product info follow-up handling in ProductSearchAgentV3."""

import asyncio
import os
import unittest
from unittest.mock import MagicMock

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

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3


class ProductInfoFollowupTests(unittest.TestCase):
    def test_cheapest_from_last_search_products(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "which is cheapest?"}},
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "last_search_products": [
                        {
                            "_id": "cheap",
                            "title": "Budget Ring",
                            "price": {"variantPrice": 25000},
                            "mediaUrl": [
                                {"image": "https://ex.com/cheap.webp", "type": "image"}
                            ],
                        },
                        {
                            "_id": "costly",
                            "title": "Premium Ring",
                            "price": {"variantPrice": 95000},
                            "mediaUrl": [
                                {"image": "https://ex.com/costly.webp", "type": "image"}
                            ],
                        },
                    ],
                },
                "classified_category": "product_info",
                "client_config": MagicMock(client_id="kisna"),
            }
            result = await agent.process(data)
            self.assertIn("bot_response", result)
            texts = [
                item.get("text", "")
                for item in result["bot_response"]
                if item.get("type") == "text"
            ]
            self.assertTrue(any("most affordable" in t for t in texts))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
