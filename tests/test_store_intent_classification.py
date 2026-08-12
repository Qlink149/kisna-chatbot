"""Store location intent — prompt/heuristic guards vs product_search hallucination."""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList
from kisna_chatbot.processors.classifier import (
    Classifier,
    _STORE_LOOKUP_RE,
    _programmatic_intent_fallback,
    _programmatic_intent_hint,
    _programmatic_intent_override,
    _sticky_wait_escape_intent,
    classify_query_for_audit,
)
from kisna_chatbot.prompts.classifier_kisna import (
    kisna_classifier_intent as kisna_classifier,
)

STORE_QUERIES = (
    "do you have a store in Mumbai",
    "Do you have a Kisna store in Delhi?",
    "is there a showroom in Pune",
    "any store near me",
    "store location in Bangalore",
    "nearest shop",
    "showroom address",
    "Mumbai me store hai kya",
    "where is your store in Hyderabad",
    "Jaipur outlet",
    "nearest store",
    "find store",
)

PRODUCT_DO_YOU_HAVE = (
    "do you have diamond rings?",
    "do you have gold necklaces",
)


class StoreLookupRegexTests(unittest.TestCase):
    def test_store_queries_match(self):
        for text in STORE_QUERIES:
            self.assertTrue(_STORE_LOOKUP_RE.search(text), msg=text)

    def test_product_do_you_have_does_not_match(self):
        for text in PRODUCT_DO_YOU_HAVE:
            self.assertFalse(_STORE_LOOKUP_RE.search(text), msg=text)


class StoreHintTests(unittest.TestCase):
    def test_store_is_hint_not_hard_override(self):
        for text in STORE_QUERIES:
            self.assertIsNone(_programmatic_intent_override(text), msg=text)
            hint = _programmatic_intent_hint(text)
            self.assertIsNotNone(hint, msg=text)
            self.assertIn("store_info", hint, msg=text)

    def test_multi_intent_shopping_skips_store_hint(self):
        # Primary shopping + store mention — leave to LLM (rule 26).
        self.assertIsNone(
            _programmatic_intent_hint("gold ring dikhao aur nearest store bhi batao")
        )

    def test_llm_outage_fallback_routes_store(self):
        intent, conf = _programmatic_intent_fallback("do you have a store in Mumbai")
        self.assertEqual(intent, "store_info")
        self.assertGreaterEqual(conf, 0.9)

    def test_sticky_escape_to_store(self):
        self.assertEqual(
            _sticky_wait_escape_intent("do you have a store in Mumbai"),
            "store_info",
        )


class StorePromptContentTests(unittest.TestCase):
    def test_prompt_has_contrastive_store_examples(self):
        self.assertIn("do you have a store in Mumbai", kisna_classifier)
        self.assertIn("STORE vs PRODUCT", kisna_classifier)
        self.assertIn("do you have diamond rings?", kisna_classifier)


class StoreGuardCorrectsLlmHallucinationTests(unittest.TestCase):
    def test_audit_guard_fixes_product_search_hallucination(self):
        async def _run():
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "intent": "product_search",
                        "confidence": 0.88,
                        "entities": {
                            "category": None,
                            "material_type": None,
                            "min_price": None,
                            "max_price": None,
                        },
                    }
                ),
            ) as mock_llm:
                result = await classify_query_for_audit(
                    "do you have a store in Mumbai", use_llm=True
                )
            mock_llm.assert_called_once()
            system_msg = mock_llm.call_args.kwargs["messages"][0]["content"]
            self.assertIn("Routing hint", system_msg)
            self.assertIn("store_info", system_msg)
            self.assertEqual(result["intent"], "store_info")
            self.assertEqual(result["source"], "store_guard")

        asyncio.run(_run())

    def test_classifier_routes_store_when_llm_says_product_search(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "do you have a store in Mumbai"}},
                "user_profile": {"chat_history": [], "service_selected": ""},
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {
                        "intent": "product_search",
                        "confidence": 0.9,
                        "language": "en",
                        "entities": {"category": None},
                    }
                ),
            ):
                result = await clf.process(data)
            self.assertEqual(result["classified_category"], "store_info")
            self.assertEqual(
                result["user_profile"]["service_selected"],
                ServiceList.AD_FLOW.value,
            )

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
