"""Regression tests for classification + extraction audit fixes."""

import asyncio
import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")

from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
from kisna_chatbot.processors.classifier import Classifier
from kisna_chatbot.processors.service_list import QuickReplyId


class StorePincodeEscapeTests(unittest.TestCase):
    def test_classifier_runs_for_product_query_while_awaiting_pincode(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "gold rings"}},
            "user_profile": {
                "awaiting_store_pincode": True,
                "service_selected": SL.AD_FLOW.value,
                "chat_history": [{"role": "user", "content": "find store"}],
            },
        }
        self.assertTrue(clf.should_run(data))

    def test_ad_flow_shows_switch_confirmation_for_product_query(self):
        async def _run():
            agent = AdFlowAgent()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "gold rings"}},
                "user_profile": {
                    "awaiting_store_pincode": True,
                    "service_selected": SL.AD_FLOW.value,
                },
            }
            result = await agent.process(data)
            self.assertIn("bot_response", result)
            qr = result["bot_response"][0]
            self.assertEqual(qr["type"], "quickreply")
            self.assertEqual(qr["msgid"], QuickReplyId.FLOW_SWITCH_CONFIRM.value)
            self.assertIn("store near you", qr["text"].lower())
            self.assertFalse(result["user_profile"]["awaiting_store_pincode"])
            self.assertIn("pending_flow_switch", result["user_profile"])

        asyncio.run(_run())


class ExpensiveSearchRoutingTests(unittest.TestCase):
    def test_expensive_followup_routes_to_product_search(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "aur expensive dikhao"}},
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "gold rings"}],
                    "last_search_products": [{"_id": "1", "title": "Ring"}],
                },
                "client_id": "kisna",
            }
            result = await clf.process(data)
            self.assertEqual(result["classified_category"], "product_search")
            self.assertEqual(
                result["user_profile"].get("llm_extracted_entities", {}).get(
                    "price_direction"
                ),
                "higher",
            )

        asyncio.run(_run())


class ProductInfoSkipCategoryTests(unittest.TestCase):
    def test_classifier_skip_sets_product_info_category(self):
        clf = Classifier()
        data = {
            "phone_number": "919999999999",
            "messages": {"text": {"body": "iska price kya hai"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "last_viewed_product": {"_id": "1", "title": "Ring"},
                "chat_history": [{"role": "user", "content": "gold rings"}],
            },
        }
        self.assertFalse(clf.should_run(data))

        async def _run():
            return await clf.process(data)

        result = asyncio.run(_run())
        self.assertEqual(result.get("classified_category"), "product_info")


if __name__ == "__main__":
    unittest.main()
