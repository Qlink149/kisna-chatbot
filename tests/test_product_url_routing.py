"""Pasting a Kisna product URL (single or multiple) routes straight to
product search via the existing title-search pipeline -- reproduces the real
customer scenario (+919934553059 sent a kisna.com product link expecting the
bot to find it). See kisna_product_url.py for why: Clara has no lookup-by-
id/slug/variant endpoint, only `title` substring search.
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
os.environ.setdefault("KISNA_UTM_ENABLED", "false")

from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import _apply_product_url_shortcut
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3

_CUSTOMER_URL = (
    "https://www.kisna.com/products/shree-diamond-gold-pendant"
    "?variant=6895d8b1e29b8e133eb53e0a"
)
_SECOND_URL = "https://www.kisna.com/products/evil-eye-gold-ring"

_MATCHING_PRODUCT = {
    "_id": "p1",
    "title": "Shree Diamond Gold Pendant",
    "category": "pendant",
    "materialType": "diamond",
    "price": {"finalPrice": 45000},
}


class ApplyProductUrlShortcutTests(unittest.TestCase):
    def _data(self, text: str) -> dict:
        return {
            "messages": {"text": {"body": text}},
            "user_profile": {},
        }

    def test_single_url_sets_title_entity_and_routes_to_product_search(self):
        data = self._data(f"is this in stock {_CUSTOMER_URL}")
        self.assertTrue(_apply_product_url_shortcut(data, data["messages"]["text"]["body"]))
        self.assertEqual(data["classified_category"], "product_search")
        self.assertEqual(
            data["user_profile"]["service_selected"], SL.PRODUCT_SEARCH.value
        )
        self.assertEqual(
            data["llm_extracted_entities"]["title"], "shree diamond gold pendant"
        )
        # Set for a single URL too -- always bypasses the confirmation
        # prompt, since the pasted link is already an explicit signal.
        self.assertEqual(data["_url_search_titles"], ["shree diamond gold pendant"])

    def test_two_urls_set_url_search_titles(self):
        text = f"{_CUSTOMER_URL} or {_SECOND_URL} which is better"
        data = self._data(text)
        self.assertTrue(_apply_product_url_shortcut(data, text))
        self.assertEqual(
            data["_url_search_titles"],
            ["shree diamond gold pendant", "evil eye gold ring"],
        )

    def test_no_url_is_a_no_op(self):
        data = self._data("show me gold rings")
        self.assertFalse(_apply_product_url_shortcut(data, "show me gold rings"))
        self.assertNotIn("classified_category", data)
        self.assertEqual(data["user_profile"], {})

    def test_non_kisna_url_is_a_no_op(self):
        text = "found this on https://www.tanishq.co.in/products/some-ring"
        data = self._data(text)
        self.assertFalse(_apply_product_url_shortcut(data, text))

    def test_two_variants_of_the_same_product_are_deduped(self):
        # Different variant= ids of the SAME slug -- must not show the same
        # product card twice.
        url_a = f"{_CUSTOMER_URL}"
        url_b = (
            "https://www.kisna.com/products/shree-diamond-gold-pendant"
            "?variant=different111variantid"
        )
        text = f"{url_a} or maybe {url_b}"
        data = self._data(text)
        self.assertTrue(_apply_product_url_shortcut(data, text))
        self.assertEqual(data["_url_search_titles"], ["shree diamond gold pendant"])


class SingleUrlEndToEndTests(unittest.TestCase):
    def test_customer_url_returns_a_matching_product_card(self):
        data = {
            "phone_number": "919934553059",
            "messages": {"text": {"body": _CUSTOMER_URL}},
            "user_profile": {},
        }
        self.assertTrue(
            _apply_product_url_shortcut(data, data["messages"]["text"]["body"])
        )

        async def _run():
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={
                    "products": [_MATCHING_PRODUCT],
                    "total_count": 1,
                    "page": 1,
                },
            ) as search_mock:
                result = await ProductSearchAgentV3().process(data)
            return result, search_mock

        result, search_mock = asyncio.run(_run())
        search_mock.assert_awaited()
        self.assertIn("bot_response", result)
        # No confirmation prompt -- _handle_url_multi_search always passes
        # confirm=False, even for a single URL.
        self.assertNotEqual(result["bot_response"][0].get("type"), "quickreply")
        self.assertTrue(
            any("Shree Diamond Gold Pendant" in str(item) for item in result["bot_response"])
        )


class MultiUrlSearchTests(unittest.TestCase):
    def test_merges_a_hit_and_a_miss_into_one_reply(self):
        data = {
            "phone_number": "919999999999",
            "messages": {"text": {"body": f"{_CUSTOMER_URL} {_SECOND_URL}"}},
            "user_profile": {"service_selected": SL.PRODUCT_SEARCH.value},
            "classified_category": "product_search",
            "_url_search_titles": ["shree diamond gold pendant", "evil eye gold ring"],
        }

        async def _run():
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=lambda **kwargs: (
                    {"products": [_MATCHING_PRODUCT], "total_count": 1, "page": 1}
                    if "shree" in (kwargs.get("title") or "").lower()
                    else {"products": [], "total_count": 0, "page": 1}
                ),
            ):
                result = await ProductSearchAgentV3().process(data)
            return result

        result = asyncio.run(_run())
        bot_response = result["bot_response"]
        composes = [item.get("_compose") for item in bot_response]
        self.assertIn("zero_results", composes)
        self.assertTrue(
            any(
                "Shree Diamond Gold Pendant" in str(item)
                for item in bot_response
            )
        )
        self.assertNotIn("_url_search_titles", result)


if __name__ == "__main__":
    unittest.main()
