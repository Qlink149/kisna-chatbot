"""Smoke tests for audit-plan fixes (complaint flow, search, routing, config)."""

import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Set minimal env before kisna_chatbot imports (database connects at import time).
os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("KISNA_PHONE_NUMBER_ID", "850788844795304")

from kisna_chatbot.config.clients import get_client_config, refresh_client_registry
from kisna_chatbot.main import _pipeline_for_service
from kisna_chatbot.models.enums import FLowId, FlowId
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.pipelines.inference_pipeline import ReturnsRefundPipeline
from kisna_chatbot.processors.complaint_agent import (
    _complaint_flow_ids,
    _parse_complaint_flow,
)
from kisna_chatbot.processors.product_details_agent import (
    ProductDetailsAgent,
    _parse_product_list_selection,
)
from kisna_chatbot.prompts.general_agent_kisna import build_general_agent_prompt
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
from kisna_chatbot.utils.product_formatter import format_product_list_message


class ComplaintFlowTokenTests(unittest.TestCase):
    def test_damage_complaint_token_in_allowed_set(self):
        flow_ids = _complaint_flow_ids()
        self.assertIn(FLowId.DAMAGE_COMPLAINT.value, flow_ids)
        self.assertIn(FlowId.COMPLAINT_FLOW.value, flow_ids)

    def test_parse_complaint_flow_accepts_damage_complaint_token(self):
        messages = {
            "interactive": {
                "nfm_reply": {
                    "name": "flow",
                    "response_json": json.dumps(
                        {
                            "flow_token": FLowId.DAMAGE_COMPLAINT.value,
                            "order_id": "KIS123",
                            "issue_description": "Damaged item",
                        }
                    ),
                }
            }
        }
        parsed = _parse_complaint_flow(messages)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("order_id"), "KIS123")


class RoutingTests(unittest.TestCase):
    def test_returns_refund_uses_returns_refund_pipeline(self):
        pipeline = _pipeline_for_service(SL.RETURNS_REFUND.value)
        self.assertIsInstance(pipeline, ReturnsRefundPipeline)


class ProductSearchTests(unittest.TestCase):
    def test_format_product_list_message(self):
        products = [
            {
                "_id": "p1",
                "title": "Gold Ring",
                "price": {"variantPrice": 19999},
                "materialType": "gold",
                "shipping": {"edd": 5},
            },
            {
                "_id": "p2",
                "title": "Diamond Pendant",
                "price": {"variantPrice": 89999},
                "materialType": "diamond",
                "shipping": {"edd": 7},
            },
        ]
        payload = format_product_list_message(products, 2, 1, search_context="gold rings")
        self.assertEqual(payload["type"], "list")
        self.assertEqual(payload["msgid"], "product_select$results")
        self.assertEqual(len(payload["items"][0]["options"]), 2)
        self.assertEqual(payload["items"][0]["options"][0]["postbackText"], "p1")

    def test_format_product_list_material_type_list(self):
        products = [
            {
                "_id": "p1",
                "title": "Diamond Ring",
                "price": {"variantPrice": 25311},
                "materialType": ["diamond"],
                "shipping": {"edd": 7},
            }
        ]
        payload = format_product_list_message(products, 1, 1)
        desc = payload["items"][0]["options"][0]["description"]
        self.assertIn("Diamond", desc)
        self.assertNotIn("['diamond']", desc)

    def test_parse_product_list_selection(self):
        list_id = json.dumps(
            {"msgid": "product_select$results", "postbackText": "prod-42"}
        )
        messages = {
            "interactive": {
                "type": "list_reply",
                "list_reply": {"id": list_id, "title": "Sofa"},
            }
        }
        product_id, title = _parse_product_list_selection(messages)
        self.assertEqual(product_id, "prod-42")
        self.assertEqual(title, "Sofa")

    def test_build_general_agent_prompt_returns_string(self):
        prompt = build_general_agent_prompt()
        self.assertIn("KISNA", prompt)

    def test_product_details_from_cache(self):
        async def _run():
            agent = ProductDetailsAgent()
            list_id = json.dumps(
                {"msgid": "product_select$results", "postbackText": "prod-42"}
            )
            cached_product = {
                "_id": "prod-42",
                "title": "Gold Ring",
                "price": {"variantPrice": 45000},
                "materialType": ["gold"],
                "shipping": {"edd": 5},
                "seos": {"slug": "products_elysia-ring"},
                "mediaUrl": [{"isDefault": True, "url": "https://img.example/r.jpg"}],
            }
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "Gold Ring"},
                    }
                },
                "user_profile": {"last_search_products": [cached_product]},
            }
            result = await agent.process(data)
            self.assertIn("bot_response", result)
            response = result["bot_response"]
            self.assertEqual(len(response), 5)
            self.assertEqual(response[0]["type"], "media")
            self.assertEqual(response[0]["media_type"], "image")
            self.assertNotIn("products_elysia", response[0]["caption"])
            self.assertEqual(response[1]["type"], "cta_url")
            self.assertEqual(response[1]["display_text"], "Buy on KISNA")
            self.assertEqual(
                response[1]["url"],
                "https://www.kisna.com/products/elysia-ring",
            )
            self.assertEqual(response[2]["msgid"], "product$similar")
            self.assertEqual(response[3]["msgid"], "product$store")
            self.assertEqual(response[4]["msgid"], "product$browse")
            self.assertIn("last_viewed_product", result["user_profile"])

        import asyncio

        asyncio.run(_run())

    def test_search_agent_calls_clara_api(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold ring under 50k"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "client_config": MagicMock(client_id="kisna"),
            }
            clara_image = (
                "https://kisna-assets.blr1.cdn.digitaloceanspaces.com/"
                "compressed/assets/test-ring.webp"
            )
            mock_product = {
                "_id": "1",
                "title": "Gold Ring",
                "price": {"variantPrice": 45000},
                "variant": {"title": "18KT Yellow Gold"},
                "materialType": "gold",
                "shipping": {"edd": 5},
                "seos": {"slug": "gold-ring"},
                "mediaUrl": [
                    {
                        "isDefault": True,
                        "image": clara_image,
                        "color": "Yellow",
                        "type": "image",
                    }
                ],
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                search_mock.return_value = {
                    "products": [mock_product],
                    "total_count": 1,
                    "page": 1,
                }
                result = await agent.process(data)
            self.assertIn("bot_response", result)
            media_msgs = [
                r for r in result["bot_response"] if r.get("type") == "media"
            ]
            self.assertEqual(len(media_msgs), 1)
            self.assertEqual(media_msgs[0]["url"], clara_image)
            self.assertTrue(media_msgs[0]["url"].startswith("https://"))
            search_mock.assert_awaited_once()
            self.assertEqual(result["user_profile"]["last_search_page"], 1)
            self.assertEqual(result["user_profile"]["last_search_total"], 1)
            self.assertIn("last_search_filters", result["user_profile"])
            self.assertEqual(
                result["user_profile"]["last_search_products"],
                [mock_product],
            )
            self.assertIn("jewellery_profile", result["user_profile"])
            self.assertEqual(
                result["user_profile"]["jewellery_profile"]["material_preference"],
                "gold",
            )
            self.assertEqual(
                result["user_profile"]["jewellery_profile"]["category_preference"],
                "ring",
            )
            self.assertEqual(
                result["user_profile"]["jewellery_profile"]["budget_range"],
                "under ₹50,000",
            )

        import asyncio

        asyncio.run(_run())


class ClientConfigTests(unittest.TestCase):
    def test_kisna_product_api_from_env(self):
        os.environ["KISNA_PRODUCT_API"] = "https://api.example.com/products"
        refresh_client_registry()
        config = get_client_config("kisna")
        self.assertEqual(config.product_api_base, "https://api.example.com/products")


if __name__ == "__main__":
    unittest.main()
