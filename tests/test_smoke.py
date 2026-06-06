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
from kisna_chatbot.processors.classifier import Classifier
from kisna_chatbot.processors.product_search_agent_v3 import (
    ProductSearchAgentV3,
    _build_search_success_response,
)
from kisna_chatbot.processors.service_list import (
    _build_explore_products_list,
    _handle_menu_selection,
)
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
            list_msgs = [
                r for r in result["bot_response"] if r.get("type") == "list"
            ]
            self.assertEqual(len(list_msgs), 1)

        import asyncio

        asyncio.run(_run())

    def test_build_search_success_response_always_includes_list(self):
        product = {
            "_id": "p1",
            "title": "Gold Ring",
            "price": {"variantPrice": 45000},
            "materialType": "gold",
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
        entities = {
            "category": "ring",
            "material_type": "gold",
            "min_price": None,
            "max_price": None,
            "title": None,
            "city": None,
            "pincode": None,
        }
        response = _build_search_success_response(
            [product], total_count=1, page=1, entities=entities
        )
        types = [r["type"] for r in response]
        self.assertIn("media", types)
        self.assertIn("list", types)
        self.assertNotIn("quickreply", types)

    def test_show_more_pagination(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps({"msgid": "search$more"})
            mock_product_page2 = {
                "_id": "p6",
                "title": "Diamond Ring",
                "price": {"variantPrice": 55000},
                "materialType": "diamond",
                "shipping": {"edd": 5},
                "seos": {"slug": "diamond-ring"},
                "mediaUrl": [
                    {
                        "isDefault": True,
                        "image": "https://img.example/diamond.webp",
                        "type": "image",
                    }
                ],
            }
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {"id": list_id, "title": "Show More"},
                    }
                },
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "last_search_filters": {
                        "category": "ring",
                        "material_type": "diamond",
                        "min_price": None,
                        "max_price": None,
                        "title": None,
                        "city": None,
                        "pincode": None,
                    },
                    "last_search_page": 1,
                    "last_search_total": 10,
                    "shown_product_ids": ["p1", "p2", "p3", "p4", "p5"],
                },
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                search_mock.return_value = {
                    "products": [mock_product_page2],
                    "total_count": 10,
                    "page": 2,
                }
                result = await agent.process(data)
            self.assertIn("bot_response", result)
            self.assertEqual(result["user_profile"]["last_search_page"], 2)
            self.assertIn("p6", result["user_profile"]["shown_product_ids"])
            list_msgs = [
                r for r in result["bot_response"] if r.get("type") == "list"
            ]
            self.assertEqual(len(list_msgs), 1)
            search_mock.assert_awaited_once()
            call_kwargs = search_mock.await_args.kwargs
            self.assertEqual(call_kwargs["page_no"], 2)

        import asyncio

        asyncio.run(_run())

    def test_search_fallback_drops_price(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold ring under 10k"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }
            mock_product = {
                "_id": "p1",
                "title": "Gold Ring",
                "price": {"variantPrice": 25000},
                "materialType": "gold",
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

            async def side_effect(**kwargs):
                if kwargs.get("max_price") == 10000:
                    return {"products": [], "total_count": 0, "page": 1}
                return {
                    "products": [mock_product],
                    "total_count": 1,
                    "page": 1,
                }

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=side_effect,
            ) as search_mock:
                result = await agent.process(data)
            self.assertGreaterEqual(search_mock.await_count, 2)
            self.assertEqual(result["bot_response"][0]["type"], "text")
            self.assertIn("outside your budget", result["bot_response"][0]["text"])

        import asyncio

        asyncio.run(_run())

    def test_category_list_triggers_ring_search(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps(
                {
                    "msgid": "search$cat$list",
                    "postbackText": "search$cat$ring",
                }
            )
            mock_product = {
                "_id": "r1",
                "title": "Ring",
                "price": {"variantPrice": 30000},
                "materialType": "gold",
                "shipping": {"edd": 5},
                "seos": {"slug": "ring"},
                "mediaUrl": [
                    {
                        "isDefault": True,
                        "image": "https://img.example/ring.webp",
                        "type": "image",
                    }
                ],
            }
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
                search_mock.return_value = {
                    "products": [mock_product],
                    "total_count": 1,
                    "page": 1,
                }
                result = await agent.process(data)
            call_kwargs = search_mock.await_args.kwargs
            self.assertEqual(call_kwargs["category"], "ring")
            self.assertIn("bot_response", result)

        import asyncio

        asyncio.run(_run())

    def test_explore_products_menu_is_category_list(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Explore Products", user_profile, data, "explore_products")
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertEqual(data["bot_response"][0]["type"], "list")
        self.assertEqual(data["bot_response"][0]["msgid"], "search$cat$list")

    def test_explore_products_list_builder(self):
        payload = _build_explore_products_list()
        postbacks = [
            opt["postbackText"]
            for opt in payload["items"][0]["options"]
        ]
        self.assertIn("search$cat$ring", postbacks)
        self.assertIn("search$explore", postbacks)


class ClassifierSkipTests(unittest.TestCase):
    def test_classifier_skips_product_search_followup(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "show earrings"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "hi"}],
            },
        }
        self.assertFalse(clf.should_run(data))

    def test_classifier_runs_for_offers_reroute(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "what offers do you have"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "hi"}],
            },
        }
        self.assertTrue(clf.should_run(data))


class ClientConfigTests(unittest.TestCase):
    def test_kisna_product_api_from_env(self):
        os.environ["KISNA_PRODUCT_API"] = "https://api.example.com/products"
        refresh_client_registry()
        config = get_client_config("kisna")
        self.assertEqual(config.product_api_base, "https://api.example.com/products")


if __name__ == "__main__":
    unittest.main()
