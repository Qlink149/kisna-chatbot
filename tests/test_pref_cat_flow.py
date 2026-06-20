"""Tests for pref$cat$ category browse flow."""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
from kisna_chatbot.processors.service_list import (
    build_main_category_list,
    build_other_jewellery_list,
)


class PrefCatFlowTests(unittest.TestCase):
    def test_main_category_list_has_nine_rows(self):
        payload = build_main_category_list()
        options = payload["items"][0]["options"]
        self.assertEqual(len(options), 9)
        titles = [opt["title"] for opt in options]
        self.assertIn("Other Jewellery", titles)
        self.assertIn("Browse All", titles)

    def test_other_jewellery_list_has_back_button(self):
        payload = build_other_jewellery_list()
        postbacks = [opt["postbackText"] for opt in payload["items"][0]["options"]]
        self.assertIn("pref$cat$back", postbacks)
        self.assertIn("pref$cat$solitaire", postbacks)

    def test_pref_cat_other_shows_secondary_list(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps(
                {"msgid": "pref$cat$other$list", "postbackText": "pref$cat$other"}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {
                            "id": list_id,
                            "title": "Other Jewellery",
                        },
                    }
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }
            result = await agent.process(data)
            self.assertEqual(result["bot_response"][0]["msgid"], "pref$cat$other$list")

        asyncio.run(_run())

    def test_pref_cat_back_shows_main_list(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps(
                {"msgid": "pref$cat$other$list", "postbackText": "pref$cat$back"}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "Back"},
                    }
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }
            result = await agent.process(data)
            self.assertEqual(result["bot_response"][0]["msgid"], "search$cat$list")

        asyncio.run(_run())

    def test_pref_cat_ring_shows_material_list(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps(
                {"msgid": "search$cat$list", "postbackText": "pref$cat$ring"}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "Rings"},
                    }
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                result = await agent.process(data)
            search_mock.assert_not_called()
            self.assertEqual(result["bot_response"][0]["msgid"], "pref$step1$list")

        asyncio.run(_run())

    def test_legacy_search_cat_ring_shows_material_list(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps(
                {"msgid": "search$cat$list", "postbackText": "search$cat$ring"}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "Rings"},
                    }
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                result = await agent.process(data)
            search_mock.assert_not_called()
            self.assertEqual(result["bot_response"][0]["msgid"], "pref$step1$list")

        asyncio.run(_run())

    def test_browse_all_uses_image_with_cta_and_base_catalogue(self):
        async def _run():
            agent = ProductSearchAgentV3()
            mock_product = {
                "_id": "p1",
                "title": "Gold Ring",
                "price": {"variantPrice": 45000},
                "materialType": "gold",
                "productType": {"category": {"name": "Rings"}},
                "shipping": {"edd": 5},
                "seos": {"slug": "gold-ring"},
                "mediaUrl": [
                    {
                        "isDefault": True,
                        "image": "https://img.example/ring.webp",
                        "type": "image",
                    }
                ],
            }
            list_id = json.dumps(
                {"msgid": "search$cat$list", "postbackText": "pref$cat$any"}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "Browse All"},
                    }
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "client_config": MagicMock(client_id="kisna"),
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={
                    "products": [mock_product],
                    "total_count": 1,
                    "page": 1,
                },
            ):
                result = await agent.process(data)
            qr = [r for r in result["bot_response"] if r.get("type") == "quickreply"]
            self.assertEqual(qr, [])
            images = [
                r for r in result["bot_response"] if r.get("type") == "image_with_cta"
            ]
            self.assertEqual(len(images), 1)
            cta = [r for r in result["bot_response"] if r.get("type") == "cta_url"]
            self.assertEqual(cta[0]["url"], "https://www.kisna.com/jewellery")

        asyncio.run(_run())

    def test_low_confidence_shows_main_menu(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "hmm maybe something"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "classified_category": "product_search",
                "classifier_confidence": 0.3,
            }
            result = await agent.process(data)
            self.assertEqual(result["bot_response"][-1]["type"], "list")
            self.assertIn("not sure", result["bot_response"][0]["text"].lower())

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
