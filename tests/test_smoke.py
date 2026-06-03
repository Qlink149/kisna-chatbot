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
from kisna_chatbot.pipelines.inference_pipeline import GeneralPipeline
from kisna_chatbot.processors.complaint_agent import (
    COMPLAINT_FLOW_IDS,
    _parse_complaint_flow,
)
from kisna_chatbot.processors.product_details_agent import _parse_product_list_selection
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
from kisna_chatbot.utils.product_formatter import format_product_list_message


class ComplaintFlowTokenTests(unittest.TestCase):
    def test_damage_complaint_token_in_allowed_set(self):
        self.assertIn(FLowId.DAMAGE_COMPLAINT.value, COMPLAINT_FLOW_IDS)
        self.assertIn(FlowId.COMPLAINT_FLOW.value, COMPLAINT_FLOW_IDS)

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
    def test_returns_refund_uses_general_pipeline(self):
        pipeline = _pipeline_for_service(SL.RETURNS_REFUND.value)
        self.assertIsInstance(pipeline, GeneralPipeline)


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
        self.assertEqual(_parse_product_list_selection(messages), "prod-42")

    def test_search_agent_calls_clara_api(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold ring under 50k"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "client_config": MagicMock(client_id="kisna"),
            }
            mock_product = {
                "_id": "1",
                "title": "Gold Ring",
                "price": {"variantPrice": 45000},
                "variant": {"title": "18KT Yellow Gold"},
                "materialType": "gold",
                "shipping": {"edd": 5},
                "seos": {"slug": "gold-ring"},
                "mediaUrl": [{"isDefault": True, "url": "https://img.example/r.jpg"}],
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
            search_mock.assert_awaited_once()
            self.assertEqual(result["user_profile"]["last_search_page"], 1)
            self.assertEqual(result["user_profile"]["last_search_total"], 1)
            self.assertIn("last_search_filters", result["user_profile"])

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
