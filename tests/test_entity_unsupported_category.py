"""Unsupported category fallback messaging."""

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
from kisna_chatbot.processors.product_search_agent_v3 import (
    ProductSearchAgentV3,
    _UNSUPPORTED_CATEGORY_NOTE,
)


def test_payal_flags_unsupported():
    entities = extract_entities("payal")
    assert entities["category"] == "anklet"
    assert entities["unsupported_category"] is True


def test_search_prepends_unsupported_note():
    async def _run():
        agent = ProductSearchAgentV3()
        entities = extract_entities("payal under 20000")
        data = {"phone_number": "919999999999", "user_profile": {}}
        return await agent._execute_search(
            data,
            "919999999999",
            entities,
            query_label="payal under 20000",
        )

    with patch(
        "kisna_chatbot.processors.product_search_agent_v3.search_products",
        new_callable=AsyncMock,
        return_value={
            "products": [
                {
                    "_id": "1",
                    "title": "Generic Piece",
                    "price": {"variantPrice": 15000},
                    "mediaUrl": [{"image": "https://example.com/a.jpg"}],
                }
            ],
            "total_count": 1,
            "page": 1,
        },
    ):
        result = asyncio.run(_run())

    texts = [item["text"] for item in result["bot_response"] if item.get("type") == "text"]
    assert any(_UNSUPPORTED_CATEGORY_NOTE in text for text in texts)
