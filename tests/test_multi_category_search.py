"""Multi-category search quick reply wiring."""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.processors.entity_extractor import extract_entities
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3


def test_extract_multi_category_flags():
    entities = extract_entities("rings aur earrings")
    assert entities["multi_category"] is True
    assert entities["categories"] == ["ring", "earring"]
    assert entities["secondary_category"] == "earring"


def test_execute_search_no_also_showing_quick_reply():
    """Multi-category search no longer appends quick reply after results."""
    async def _run():
        agent = ProductSearchAgentV3()
        entities = extract_entities("rings aur earrings")
        data = {
            "phone_number": "919999999999",
            "user_profile": {},
            "messages": {"text": {"body": "rings aur earrings"}},
        }
        return await agent._execute_search(
            data,
            "919999999999",
            entities,
            query_label="rings aur earrings",
        )

    with patch(
        "kisna_chatbot.processors.product_search_agent_v3.search_products",
        new_callable=AsyncMock,
        return_value={
            "products": [
                {
                    "_id": "1",
                    "title": "Test Ring",
                    "price": {"variantPrice": 25000},
                    "mediaUrl": [{"image": "https://example.com/a.jpg"}],
                    "productType": {"category": {"name": "Rings"}},
                    "seos": {"slug": "test-ring"},
                }
            ],
            "total_count": 1,
            "page": 1,
        },
    ):
        result = asyncio.run(_run())

    quick_replies = [
        item for item in result["bot_response"] if item.get("type") == "quickreply"
    ]
    assert quick_replies == []
    image_msgs = [
        item for item in result["bot_response"] if item.get("type") == "image_with_cta"
    ]
    assert len(image_msgs) == 1
    assert image_msgs[0]["cta_title"] == "Buy on KISNA"
