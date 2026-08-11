"""GeneralAgent catalog follow-up reroute tests."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.general_agent import GeneralAgent


class GeneralAgentRerouteTests(unittest.TestCase):
    def test_cheapest_question_is_answered_from_shown_products(self):
        async def _run():
            agent = GeneralAgent()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "which is cheapest?"}},
                "user_profile": {
                    "service_selected": SL.GENERAL.value,
                    "last_search_products": [
                        {"_id": "1", "title": "Ring A", "price": {"variantPrice": 50000}}
                    ],
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.general_agent.run_general_agent",
                new_callable=AsyncMock,
            ) as mock_llm:
                result = await agent.process(data)
            mock_llm.assert_not_called()
            self.assertEqual(result["classified_category"], "product_info")
            self.assertEqual(
                result["user_profile"]["service_selected"], SL.PRODUCT_SEARCH.value
            )
            # Product search answers it from the real shown products — the
            # GeneralAgent LLM must never invent a price here.
            texts = " ".join(
                item.get("text", "") for item in result.get("bot_response", [])
            )
            self.assertIn("Ring A", texts)
            self.assertIn("50,000", texts)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
