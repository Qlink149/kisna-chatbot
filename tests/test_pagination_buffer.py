"""Regression tests for the UI display buffer / API pagination decoupling and
the continuation-phrase-over-stale-slot-fill priority fix.

See plan: last_search_buffer decouples PAGE_SIZE=3 WhatsApp display pages from
the (up to 15-item) Clara API page, and continuation phrases ("any other
option") now win over a stale awaiting_custom_budget slot-fill.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL


def _make_text_msg(body):
    return {"text": {"body": body}}


def _product_search_profile(**extra):
    base = {
        "service_selected": SL.PRODUCT_SEARCH.value,
        "chat_history": [],
        "shown_product_ids": [],
        "last_search_filters": {},
        "last_search_page": 0,
        "last_search_total": 0,
    }
    base.update(extra)
    return base


def _mock_product(pid="p1"):
    return {
        "_id": pid,
        "title": "Gold Ring",
        "price": {"variantPrice": 25000},
        "materialType": "gold",
        "productType": {"category": {"name": "Rings"}},
        "shipping": {"edd": 5},
        "seos": {"slug": "gold-ring"},
        "mediaUrl": [{"isDefault": True, "image": "https://img.example/ring.webp", "type": "image"}],
    }


class ShowMoreBufferTests(unittest.TestCase):
    def test_buffer_drain_skips_api_call(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            buffer = [_mock_product(f"buf{i}") for i in range(1, 6)]  # 5 leftover items
            profile = _product_search_profile(
                last_search_filters={"category": "ring"},
                last_search_page=1,
                last_search_total=8,
                last_search_filter_ratio=1.0,
                last_search_api_total=8,
                last_search_buffer=buffer,
            )
            data = {"phone_number": "919999999999", "user_profile": profile}

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as mock_search:
                result = await agent._handle_show_more(data, data["phone_number"])

            mock_search.assert_not_awaited()
            shown_ids = {p["_id"] for p in result["user_profile"]["last_search_products"]}
            self.assertEqual(shown_ids, {"buf1", "buf2", "buf3"})
            self.assertEqual(
                [p["_id"] for p in result["user_profile"]["last_search_buffer"]],
                ["buf4", "buf5"],
            )
            # API cursor must not advance on a buffer-only serve.
            self.assertEqual(result["user_profile"]["last_search_page"], 1)
        asyncio.run(_run())

    def test_empty_buffer_falls_back_to_api(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            profile = _product_search_profile(
                last_search_filters={"category": "ring"},
                last_search_page=1,
                last_search_total=8,
                last_search_filter_ratio=1.0,
                last_search_api_total=8,
                last_search_buffer=[],
            )
            data = {"phone_number": "919999999999", "user_profile": profile}

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={
                    "products": [_mock_product("p2a"), _mock_product("p2b")],
                    "total_count": 8,
                    "page": 2,
                },
            ) as mock_search:
                result = await agent._handle_show_more(data, data["phone_number"])

            mock_search.assert_awaited()
            _, kwargs = mock_search.call_args
            self.assertEqual(kwargs.get("page_no"), 2)
            self.assertEqual(result["user_profile"]["last_search_page"], 2)
        asyncio.run(_run())


class ContinuationOverStaleBudgetTests(unittest.TestCase):
    def test_any_other_option_resumes_pagination_not_budget(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            buffer = [_mock_product("buf1"), _mock_product("buf2")]
            profile = _product_search_profile(
                awaiting_custom_budget=True,
                last_search_filters={"category": "ring"},
                last_search_page=1,
                last_search_total=5,
                last_search_filter_ratio=1.0,
                last_search_api_total=5,
                last_search_buffer=buffer,
            )
            data = {
                "phone_number": "919999999999",
                "messages": _make_text_msg("any other option"),
                "user_profile": profile,
            }

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as mock_search:
                result = await agent.process(data)

            mock_search.assert_not_awaited()
            self.assertFalse(result["user_profile"].get("awaiting_custom_budget"))
            bot_texts = " ".join(
                m.get("text", "") for m in result.get("bot_response", []) if m.get("type") == "text"
            )
            self.assertNotIn("couldn't understand that budget", bot_texts)
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
