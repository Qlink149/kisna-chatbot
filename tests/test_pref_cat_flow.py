"""Tests for pref$cat$ legacy list taps → conversational text prompts."""

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
os.environ.setdefault("KISNA_UTM_ENABLED", "false")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3


class PrefCatFlowTests(unittest.TestCase):
    def test_pref_cat_other_asks_slot_fill(self):
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
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn("rings", result["bot_response"][0]["text"].lower())

        asyncio.run(_run())

    def test_pref_cat_back_asks_slot_fill(self):
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
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn("budget", result["bot_response"][0]["text"].lower())

        asyncio.run(_run())

    def test_pref_cat_ring_asks_budget_in_text(self):
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
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn("budget", result["bot_response"][0]["text"].lower())
            self.assertEqual(result["user_profile"]["pref_category"], "ring")
            self.assertEqual(result["user_profile"]["preference_step"], 2)
            self.assertTrue(result["user_profile"]["awaiting_custom_budget"])

        asyncio.run(_run())

    def test_legacy_search_cat_ring_asks_budget_in_text(self):
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
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn("budget", result["bot_response"][0]["text"].lower())
            self.assertEqual(result["user_profile"]["pref_category"], "ring")
            self.assertTrue(result["user_profile"]["awaiting_custom_budget"])

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

    def test_low_confidence_shows_text_clarification(self):
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
            self.assertTrue(
                all(m.get("type") == "text" for m in result["bot_response"])
            )
            joined = " ".join(m["text"].lower() for m in result["bot_response"])
            self.assertTrue("not sure" in joined or "rings" in joined)
            self.assertTrue(result["user_profile"].get("pending_vague_slot_fill"))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
