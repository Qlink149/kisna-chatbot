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
from kisna_chatbot.processors.ad_flow_agent import (
    _filter_cached_stores,
    _UNPARSEABLE_STORE_TEXT,
)
from kisna_chatbot.processors.entity_extractor import (
    is_unrecognizable_input,
    normalize_category_for_api,
)
from kisna_chatbot.processors.offers_agent import _is_labour_promo
from kisna_chatbot.processors.order_tracking_agent import build_track_order_bot_response
from kisna_chatbot.processors.product_search_agent_v3 import (
    ProductSearchAgentV3,
    _build_search_success_response,
    _collect_carousel_products,
    _entities_from_last_viewed,
)
from kisna_chatbot.processors.service_list import (
    _build_explore_products_list,
    _handle_menu_selection,
)
from kisna_chatbot.utils.product_formatter import get_product_display_price
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
                "productType": {"category": {"name": "Rings"}},
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
            ) as search_mock, patch(
                "kisna_chatbot.processors.product_search_agent_v3.extract_entities_with_llm",
                new_callable=AsyncMock,
                return_value={
                    "category": "ring",
                    "material_type": "gold",
                    "max_price": 50000,
                },
            ), patch.dict(
                os.environ, {"CLOUDINARY_CLOUD_NAME": "test-cloud"}
            ):
                search_mock.return_value = {
                    "products": [mock_product],
                    "total_count": 1,
                    "page": 1,
                }
                result = await agent.process(data)
            self.assertIn("bot_response", result)
            media_msgs = [
                r for r in result["bot_response"] if r.get("type") == "image_with_cta"
            ]
            self.assertEqual(len(media_msgs), 1)
            self.assertIn(
                "res.cloudinary.com/test-cloud/image/fetch/f_jpg",
                media_msgs[0]["url"],
            )
            self.assertIn(clara_image, media_msgs[0]["url"])
            self.assertTrue(media_msgs[0]["url"].startswith("https://"))
            self.assertEqual(media_msgs[0]["cta_title"], "Buy on KISNA")
            self.assertIn("gold-ring", media_msgs[0]["cta_url"])
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
            cta_msgs = [
                r for r in result["bot_response"] if r.get("type") == "cta_url"
            ]
            self.assertEqual(len(cta_msgs), 1)
            self.assertIn("rings", cta_msgs[0]["url"])
            self.assertNotIn("quickreply", [r.get("type") for r in result["bot_response"]])

        import asyncio

        asyncio.run(_run())

    def test_build_search_success_response_image_with_cta_sequence(self):
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
        self.assertEqual(types, ["text", "image_with_cta", "cta_url"])
        self.assertEqual(response[1]["cta_title"], "Buy on KISNA")
        self.assertIn("gold-ring", response[1]["cta_url"])
        self.assertEqual(
            response[2]["url"],
            "https://www.kisna.com/jewellery/rings+gold",
        )
        self.assertNotIn("quickreply", types)
        self.assertNotIn("list", types)

    def test_show_more_pagination(self):
        async def _run():
            agent = ProductSearchAgentV3()
            list_id = json.dumps({"msgid": "search$more"})
            mock_product_page2 = {
                "_id": "p6",
                "title": "Diamond Ring",
                "price": {"variantPrice": 55000},
                "materialType": "diamond",
                "productType": {"category": {"name": "Rings"}},
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
            image_msgs = [
                r for r in result["bot_response"] if r.get("type") == "image_with_cta"
            ]
            self.assertEqual(len(image_msgs), 1)
            cta_msgs = [
                r for r in result["bot_response"] if r.get("type") == "cta_url"
            ]
            self.assertEqual(len(cta_msgs), 1)
            search_mock.assert_awaited_once()
            call_kwargs = search_mock.await_args.kwargs
            self.assertEqual(call_kwargs["page_no"], 2)

        import asyncio

        asyncio.run(_run())

    def test_show_more_natural_language(self):
        async def _run():
            agent = ProductSearchAgentV3()
            mock_product_page2 = {
                "_id": "p6",
                "title": "Diamond Ring",
                "price": {"variantPrice": 55000},
                "materialType": "diamond",
                "productType": {"category": {"name": "Rings"}},
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
                "messages": {"text": {"body": "aur dikhao"}},
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
            self.assertIn("No pieces found under ₹10,000", result["bot_response"][0]["text"])

        import asyncio

        asyncio.run(_run())

    def test_gold_chains_search_returns_carousel_not_zero_results(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Show me gold Chains"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "llm_extracted_entities": {
                    "category": "necklace",
                    "material_type": "gold",
                    "title": "chains",
                },
            }

            def _chain_product(pid: str, title: str) -> dict:
                return {
                    "_id": pid,
                    "title": title,
                    "price": {"variantPrice": 85000},
                    "materialType": "gold",
                    "productType": {"category": {"name": "Necklaces"}},
                    "shipping": {"edd": 5},
                    "seos": {"slug": f"gold-{pid}"},
                    "mediaUrl": [
                        {
                            "isDefault": True,
                            "image": f"https://img.example/{pid}.webp",
                            "type": "image",
                        }
                    ],
                }

            mock_products = [
                _chain_product(f"chain-{i}", "Gold Rope Chain")
                for i in range(7)
            ]

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={
                    "products": mock_products,
                    "total_count": 7,
                    "page": 1,
                },
            ) as search_mock, patch(
                "kisna_chatbot.processors.product_search_agent_v3.extract_entities_with_llm",
                new_callable=AsyncMock,
                return_value={},
            ):
                result = await agent.process(data)

            search_mock.assert_awaited_once()
            self.assertNotIn("couldn't find", result["bot_response"][0]["text"].lower())
            media_msgs = [
                r for r in result["bot_response"] if r.get("type") == "image_with_cta"
            ]
            self.assertGreater(len(media_msgs), 0)

        import asyncio

        asyncio.run(_run())

    def test_search_fallback_on_over_budget_api_results(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "text": {"body": "I want all the rings below 10,000"}
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }
            over_budget_ring = {
                "_id": "p1",
                "title": "Elysia Ring",
                "price": {"variantPrice": 24779},
                "materialType": ["diamond"],
                "shipping": {"edd": 5},
                "seos": {"slug": "products_elysia-ring"},
                "productType": {"category": {"name": "Rings"}},
                "mediaUrl": [
                    {
                        "isDefault": True,
                        "image": "https://img.example/elysia.webp",
                        "type": "image",
                    }
                ],
            }

            async def side_effect(**kwargs):
                if kwargs.get("max_price") == 10000:
                    page = kwargs.get("page_no", 1)
                    return {
                        "products": [over_budget_ring],
                        "total_count": 3390,
                        "page": page,
                    }
                return {
                    "products": [over_budget_ring],
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
            self.assertIn("No pieces found under ₹10,000", result["bot_response"][0]["text"])

        import asyncio

        asyncio.run(_run())

    def test_search_finds_budget_items_on_later_page(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "rings under 10,000"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }

            def _ring(pid: str, price: int, title: str) -> dict:
                return {
                    "_id": pid,
                    "title": title,
                    "price": {"variantPrice": price},
                    "materialType": "gold",
                    "shipping": {"edd": 5},
                    "seos": {"slug": f"ring-{pid}"},
                    "productType": {"category": {"name": "Rings"}},
                    "mediaUrl": [
                        {
                            "isDefault": True,
                            "image": f"https://img.example/{pid}.webp",
                            "type": "image",
                        }
                    ],
                }

            over_budget = _ring("over", 25000, "Premium Ring")
            under_budget = _ring("under", 8000, "Budget Ring")

            async def side_effect(**kwargs):
                if kwargs.get("max_price") == 10000:
                    page = kwargs.get("page_no", 1)
                    if page == 1:
                        return {
                            "products": [over_budget],
                            "total_count": 20,
                            "page": 1,
                        }
                    if page == 2:
                        return {
                            "products": [under_budget],
                            "total_count": 20,
                            "page": 2,
                        }
                    return {"products": [], "total_count": 20, "page": page}
                raise AssertionError("drop_price fallback should not run")

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=side_effect,
            ) as search_mock:
                result = await agent.process(data)

            self.assertEqual(search_mock.await_count, 2)
            image_msgs = [
                r for r in result["bot_response"] if r.get("type") == "image_with_cta"
            ]
            self.assertEqual(len(image_msgs), 1)
            self.assertIn("Budget Ring", image_msgs[0]["caption"])
            cta_msgs = [
                r for r in result["bot_response"] if r.get("type") == "cta_url"
            ]
            self.assertEqual(len(cta_msgs), 1)
            self.assertNotIn("outside your budget", cta_msgs[0]["text"])
            self.assertNotIn("No pieces found under", cta_msgs[0]["text"])

        import asyncio

        asyncio.run(_run())

    def test_search_filters_mixed_price_results(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold ring under 10k"}},
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            }

            def _ring(pid: str, price: int, title: str) -> dict:
                return {
                    "_id": pid,
                    "title": title,
                    "price": {"variantPrice": price},
                    "materialType": "gold",
                    "shipping": {"edd": 5},
                    "seos": {"slug": f"ring-{pid}"},
                    "productType": {"category": {"name": "Rings"}},
                    "mediaUrl": [
                        {
                            "isDefault": True,
                            "image": f"https://img.example/{pid}.webp",
                            "type": "image",
                        }
                    ],
                }

            under = _ring("under", 8000, "Budget Ring")
            over1 = _ring("over1", 25000, "Premium Ring")
            over2 = _ring("over2", 35000, "Luxury Ring")

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                search_mock.return_value = {
                    "products": [under, over1, over2],
                    "total_count": 3,
                    "page": 1,
                }
                result = await agent.process(data)

            image_msgs = [
                r for r in result["bot_response"] if r.get("type") == "image_with_cta"
            ]
            self.assertEqual(len(image_msgs), 1)
            self.assertIn("Budget Ring", image_msgs[0]["caption"])
            self.assertEqual(
                result["user_profile"]["last_search_products"],
                [under],
            )

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

    def test_explore_products_menu_shows_category_list(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Explore Products", user_profile, data, "explore_products")
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertEqual(data["bot_response"][0]["type"], "list")
        self.assertEqual(data["bot_response"][0]["msgid"], "search$cat$list")
        postbacks = [
            opt["postbackText"]
            for opt in data["bot_response"][0]["items"][0]["options"]
        ]
        self.assertIn("pref$cat$other", postbacks)
        self.assertIn("pref$cat$any", postbacks)
        self.assertEqual(len(postbacks), 9)

    def test_explore_products_clears_prior_search_and_shows_category_list(self):
        user_profile = {
            "last_search_filters": {"category": "ring", "material_type": "gold"},
            "last_search_products": [{"_id": "p1"}],
            "last_search_page": 2,
            "shown_product_ids": ["p1"],
            "llm_extracted_entities": {"category": "ring", "material_type": "gold"},
        }
        data = {}
        _handle_menu_selection("Explore Products", user_profile, data, "explore_products")
        self.assertEqual(data["bot_response"][0]["type"], "list")
        self.assertEqual(user_profile["last_search_filters"], {})
        self.assertEqual(user_profile["last_search_products"], [])
        self.assertEqual(user_profile["last_search_page"], 0)
        self.assertEqual(user_profile["shown_product_ids"], [])
        self.assertNotIn("pending_explore_search", user_profile)

    def test_explore_products_list_builder(self):
        payload = _build_explore_products_list()
        self.assertEqual(payload["type"], "list")
        self.assertIn("globalButtons", payload)
        self.assertEqual(payload["globalButtons"][0]["title"], "Select Category")
        postbacks = [
            opt["postbackText"]
            for opt in payload["items"][0]["options"]
        ]
        self.assertIn("pref$cat$ring", postbacks)
        self.assertIn("pref$cat$any", postbacks)
        self.assertIn("pref$cat$other", postbacks)

    def test_handle_menu_selection_delegates_pref_cat_postback(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Rings", user_profile, data, "pref$cat$ring")
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertNotIn("bot_response", data)

    def test_handle_menu_selection_delegates_search_cat_postback(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Rings", user_profile, data, "search$cat$ring")
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertNotIn("bot_response", data)

    def test_handle_menu_selection_delegates_pref_cat_any(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Browse All", user_profile, data, "pref$cat$any")
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertNotIn("bot_response", data)


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
            "messages": {"text": {"body": "view offers"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "hi"}],
            },
        }
        self.assertTrue(clf.should_run(data))

    def test_classifier_skips_awaiting_store_pincode(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "400001"}},
            "user_profile": {
                "awaiting_store_pincode": True,
                "chat_history": [{"role": "user", "content": "find store"}],
            },
        }
        self.assertFalse(clf.should_run(data))

    def test_classifier_skips_bare_pincode_when_ad_flow_active(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "400001"}},
            "user_profile": {
                "service_selected": SL.AD_FLOW.value,
                "chat_history": [{"role": "user", "content": "find store"}],
            },
        }
        self.assertFalse(clf.should_run(data))

    def test_classifier_pincode_wait_shortcut_routes_ad_flow(self):
        clf = Classifier()

        async def _run():
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "400001"}},
                "user_profile": {
                    "chat_history": [],
                    "service_selected": "",
                    "awaiting_store_pincode": True,
                },
                "client_id": "kisna",
            }
            return await clf.process(data)

        import asyncio

        result = asyncio.run(_run())
        self.assertEqual(result["classified_category"], "store_info")
        self.assertEqual(result["user_profile"]["service_selected"], SL.AD_FLOW.value)
        self.assertNotIn("bot_response", result)


class SeeSimilarTests(unittest.TestCase):
    def test_normalize_category_earring_not_corrupted(self):
        self.assertEqual(normalize_category_for_api("earring"), "earring")
        self.assertEqual(normalize_category_for_api("earrings"), "earring")

    def test_entities_from_last_viewed_uses_canonical_category(self):
        entities = _entities_from_last_viewed({"category": "earring"})
        self.assertEqual(entities["category"], "earring")


class StoreFlowTests(unittest.TestCase):
    def test_filter_cached_stores_no_unrelated_fallback(self):
        cached = {
            "stores": [
                {"name": "Mumbai Store", "address": {"line1": "Mumbai", "pincode": "400001"}},
            ]
        }
        result = _filter_cached_stores(cached, pincode="999999")
        self.assertEqual(result["stores"], [])

    def test_find_store_menu_sets_awaiting_pincode(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Find Store", user_profile, data, "find_store")
        self.assertTrue(user_profile["awaiting_store_pincode"])
        self.assertEqual(user_profile["service_selected"], SL.AD_FLOW.value)

    def test_unparseable_store_input_message_defined(self):
        self.assertIn("6-digit pincode", _UNPARSEABLE_STORE_TEXT)


class TrackOrderTests(unittest.TestCase):
    def test_track_order_menu_returns_cta_url(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("Track Order", user_profile, data, "track_order")
        self.assertEqual(user_profile["service_selected"], SL.ORDER_TRACKING.value)
        self.assertTrue(any(item.get("type") == "cta_url" for item in data["bot_response"]))

    def test_build_track_order_bot_response_has_cta(self):
        response = build_track_order_bot_response()
        self.assertEqual(response[-1]["type"], "cta_url")
        self.assertIn("track-order", response[-1]["url"])


class OffersMenuTests(unittest.TestCase):
    def test_view_offers_delegates_without_prompt(self):
        user_profile = {}
        data = {}
        _handle_menu_selection("View Offers", user_profile, data, "view_offers")
        self.assertEqual(user_profile["service_selected"], SL.OFFERS.value)
        self.assertEqual(data["classified_category"], "offers")
        self.assertNotIn("bot_response", data)

    def test_making_charges_promo_counts_as_labour(self):
        self.assertTrue(_is_labour_promo({"discOn": "Making Charges"}))


class SearchImageCarouselTests(unittest.TestCase):
    def test_carousel_sends_available_images_only(self):
        products = [
            {"_id": "1", "title": "A", "mediaUrl": [{"image": "https://ex.com/a.jpg"}]},
            {"_id": "2", "title": "B"},
            {"_id": "3", "title": "C", "mediaUrl": [{"image": "https://ex.com/c.jpg"}]},
            {"_id": "4", "title": "D", "mediaUrl": [{"image": "https://ex.com/d.jpg"}]},
            {"_id": "5", "title": "E", "mediaUrl": [{"image": "https://ex.com/e.jpg"}]},
        ]
        response = _build_search_success_response(products, 5, 1, {})
        image_items = [r for r in response if r.get("type") == "image_with_cta"]
        self.assertEqual(len(image_items), 3)

    def test_carousel_no_images_shows_fallback_text(self):
        products = [{"_id": "1", "title": "A"}]
        response = _build_search_success_response(products, 1, 1, {})
        texts = [r["text"] for r in response if r.get("type") == "text"]
        self.assertTrue(any("images unavailable" in t for t in texts))


class DisplayPriceTests(unittest.TestCase):
    def test_sale_price_takes_priority(self):
        product = {"price": {"variantPrice": 50000, "salePrice": 45000}}
        self.assertEqual(get_product_display_price(product), 45000)

    def test_display_uses_variant_price_when_api_mrp_stale(self):
        product = {
            "price": {"variantPrice": 64892},
            "variant": {"salePrice": 64892, "mrpPrice": 64892},
            "materialType": ["diamond"],
            "promotions": [
                {
                    "discOn": "Labour",
                    "fromAmt": 50000,
                    "toAmt": 99999,
                    "disc": 30,
                    "category": "Diamond",
                }
            ],
        }
        self.assertEqual(get_product_display_price(product), 64892)


class FilterMergeTests(unittest.TestCase):
    def test_merge_keeps_earring_on_under_10k(self):
        from kisna_chatbot.processors.entity_extractor import merge_search_entities

        prior = {"category": "earring", "material_type": None, "max_price": None}
        new = {"category": None, "max_price": 10000.0}
        merged = merge_search_entities(prior, new, "I want them under 10,000")
        self.assertEqual(merged["category"], "earring")
        self.assertEqual(merged["max_price"], 10000.0)


class OffersClassifierSkipTests(unittest.TestCase):
    def test_classifier_skips_offers_go_ahead(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "go ahead"}},
            "user_profile": {
                "service_selected": SL.OFFERS.value,
                "chat_history": [{"role": "user", "content": "offers"}],
            },
        }
        self.assertFalse(clf.should_run(data))


class ClientConfigTests(unittest.TestCase):
    def test_kisna_product_api_from_env(self):
        os.environ["KISNA_PRODUCT_API"] = "https://api.example.com/products"
        refresh_client_registry()
        config = get_client_config("kisna")
        self.assertEqual(config.product_api_base, "https://api.example.com/products")


class HardeningAuditTests(unittest.TestCase):
    def test_product_details_cache_miss_retry(self):
        async def _run():
            agent = ProductDetailsAgent()
            list_id = json.dumps(
                {"msgid": "product_select$results", "postbackText": "prod-miss"}
            )
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "Gold Ring"},
                    }
                },
                "user_profile": {"last_search_products": []},
            }
            mock_result = {
                "products": [
                    {
                        "_id": "prod-miss",
                        "title": "Gold Ring",
                        "price": {"variantPrice": 45000},
                        "materialType": ["gold"],
                    }
                ],
                "total_count": 1,
                "page": 1,
            }
            with patch(
                "kisna_chatbot.processors.product_details_agent.search_products",
                new_callable=AsyncMock,
                return_value=mock_result,
            ):
                result = await agent.process(data)
            self.assertIn("bot_response", result)
            self.assertTrue(len(result["bot_response"]) >= 1)

        import asyncio

        asyncio.run(_run())

    def test_price_followup_from_last_viewed(self):
        async def _run():
            agent = ProductDetailsAgent()
            cached_product = {
                "_id": "prod-42",
                "title": "Gold Ring",
                "price": {"variantPrice": 45000},
                "materialType": ["gold"],
                "shipping": {"edd": 5},
            }
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "isme kitna hai?"}},
                "user_profile": {
                    "last_viewed_product": {
                        "_id": "prod-42",
                        "title": "Gold Ring",
                        "price": 45000,
                    },
                    "last_search_products": [cached_product],
                    "service_selected": SL.PRODUCT_SEARCH.value,
                },
            }
            result = await agent.process(data)
            self.assertIn("bot_response", result)
            self.assertIn("₹45,000", result["bot_response"][0]["text"])

        import asyncio

        asyncio.run(_run())

    def test_classifier_stays_in_offers_for_product_search(self):
        """Product-search-shaped text in OFFERS no longer forces classifier escape."""
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "gold ring under 50k"}},
            "user_profile": {
                "service_selected": SL.OFFERS.value,
                "chat_history": [{"role": "user", "content": "offers"}],
            },
        }
        self.assertFalse(clf.should_run(data))

    def test_classifier_json_fallback_menu(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "tell me about care"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value="not valid json",
            ):
                result = await clf.process(data)
            self.assertIn("bot_response", result)
            self.assertEqual(result["bot_response"][0]["type"], "list")

        import asyncio

        asyncio.run(_run())

    def test_ad_flow_cancel_returns_menu(self):
        async def _run():
            from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent

            agent = AdFlowAgent()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "cancel"}},
                "user_profile": {"awaiting_store_pincode": True},
            }
            result = await agent.process(data)
            self.assertIn("bot_response", result)
            self.assertEqual(result["user_profile"]["awaiting_store_pincode"], False)
            self.assertEqual(result["user_profile"]["service_selected"], "")

        import asyncio

        asyncio.run(_run())

    def test_offers_api_error_not_empty_message(self):
        async def _run():
            from kisna_chatbot.integrations.clara_api import ClaraAPIError
            from kisna_chatbot.processors.offers_agent import OffersAgent, _ERROR_TEXT

            agent = OffersAgent()
            data = {
                "phone_number": "919999999999",
                "user_profile": {"service_selected": SL.OFFERS.value},
                "client_config": get_client_config("kisna"),
                "classified_category": "offers",
            }
            with patch(
                "kisna_chatbot.processors.offers_agent.get_cached_promotions",
                new_callable=AsyncMock,
                return_value=[],
            ), patch(
                "kisna_chatbot.processors.offers_agent.get_promotions",
                new_callable=AsyncMock,
                side_effect=ClaraAPIError("down"),
            ):
                result = await agent.process(data)
            self.assertIn("bot_response", result)
            self.assertIn(_ERROR_TEXT, result["bot_response"][0]["text"])

        import asyncio

        asyncio.run(_run())

    def test_general_prompt_omits_placeholder_phone(self):
        prompt = build_general_agent_prompt()
        self.assertNotIn("1800-XXX-XXXX", prompt)
        self.assertIn("do not invent", prompt.lower())

    def test_garbage_zeros_detected(self):
        self.assertTrue(
            is_unrecognizable_input(
                "000000000000000000000000000000000000000000000000000000000"
            )
        )

    def test_garbage_excludes_pincode(self):
        self.assertFalse(is_unrecognizable_input("400001"))

    def test_garbage_excludes_catalog_query(self):
        self.assertFalse(is_unrecognizable_input("gold ring"))

    def test_classifier_runs_for_garbage_mid_search(self):
        clf = Classifier()
        data = {
            "messages": {
                "text": {
                    "body": "000000000000000000000000000000000000000000000000000000000"
                }
            },
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "mangalsutra"}],
            },
        }
        self.assertTrue(clf.should_run(data))

    def test_classifier_routes_garbage_to_general(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "text": {
                        "body": "000000000000000000000000000000000000000000000000000000000"
                    }
                },
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "mangalsutra"}],
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value='{"intent": "general", "confidence": 0.3, "entities": {}}',
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "general")
            self.assertEqual(result["user_profile"]["service_selected"], SL.GENERAL.value)
            self.assertNotIn("bot_response", result)

        import asyncio

        asyncio.run(_run())

    def test_search_skips_api_for_garbage(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "text": {
                        "body": "000000000000000000000000000000000000000000000000000000000"
                    }
                },
                "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
                "client_config": MagicMock(client_id="kisna"),
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as mock_search:
                result = await agent.process(data)
            mock_search.assert_not_called()
            self.assertEqual(result["classified_category"], "general")

        import asyncio

        asyncio.run(_run())

    def test_carousel_scans_beyond_first_five(self):
        products = []
        for i in range(10):
            product = {"_id": str(i), "title": f"P{i}"}
            if i in (0, 6, 8):
                product["mediaUrl"] = [
                    {"image": f"https://ex.com/p{i}.jpg", "type": "image"}
                ]
            products.append(product)

        carousel, skipped, scanned = _collect_carousel_products(products)
        self.assertEqual(len(carousel), 3)
        self.assertEqual(scanned, 9)

        response = _build_search_success_response(
            products[:5],
            10,
            1,
            {"category": "mangalsutra"},
            carousel_pool=products,
        )
        media_items = [r for r in response if r.get("type") == "image_with_cta"]
        self.assertEqual(len(media_items), 3)

    def test_product_detail_enriches_missing_image(self):
        async def _run():
            agent = ProductDetailsAgent()
            list_id = json.dumps(
                {"msgid": "product_select$results", "postbackText": "prod-2"}
            )
            cached = {
                "_id": "prod-2",
                "title": "TriAmour Mangalsutra",
                "price": {"variantPrice": 33850},
            }
            fresh = {
                "_id": "prod-2",
                "title": "TriAmour Mangalsutra",
                "mediaUrl": [
                    {"image": "https://ex.com/mangalsutra.jpg", "type": "image"}
                ],
            }
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "list_reply",
                        "list_reply": {"id": list_id, "title": "TriAmour Mangalsutra"},
                    }
                },
                "user_profile": {"last_search_products": [cached]},
            }
            with patch(
                "kisna_chatbot.processors.product_details_agent.search_products",
                new_callable=AsyncMock,
                return_value={"products": [fresh], "total_count": 1, "page": 1},
            ):
                result = await agent.process(data)
            self.assertEqual(result["bot_response"][0]["type"], "media")

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
