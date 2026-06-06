"""Vague browse queries show category menu instead of unfiltered API search."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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


class VagueBrowseMenuTests(unittest.TestCase):
    def test_kuch_dikhao_shows_category_menu(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "kuch dikhao"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "classified_category": "product_search",
                "client_config": MagicMock(client_id="kisna"),
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as mock_search:
                result = await agent.process(data)
            mock_search.assert_not_called()
            self.assertEqual(result["bot_response"][0]["type"], "list")
            self.assertIn(
                "jewellery",
                result["bot_response"][0]["body"].lower(),
            )

        asyncio.run(_run())

    def test_sab_dikhao_runs_unfiltered_search(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "sab dikhao"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "classified_category": "product_search",
                "client_config": MagicMock(client_id="kisna"),
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": [], "total_count": 0, "page": 1},
            ) as mock_search:
                await agent.process(data)
            mock_search.assert_awaited_once()

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
