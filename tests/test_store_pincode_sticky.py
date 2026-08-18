"""Store-pincode sticky wait must not eat jewellery / greeting turns."""

import asyncio
import os
import time
import unittest

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_TOKEN": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "JWT_SECRET_KEY": "test",
    "SYSTEM_API_KEY": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_OFFERS_API": "http://localhost/offers",
    "KISNA_STORE_API": "http://localhost/stores",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "KB_ENABLED": "false",
}.items():
    os.environ.setdefault(_k, _v)


def _fresh_ts() -> int:
    return int(time.time())

from kisna_chatbot.models.service_list import ServiceList as SL  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    _clear_state_on_greeting,
    _looks_like_browse_escape,
    _store_pincode_escape_intent,
)


class StorePincodeStickyTests(unittest.TestCase):
    def test_bare_ring_is_browse_escape(self):
        self.assertTrue(_looks_like_browse_escape("Ring"))
        self.assertEqual(_store_pincode_escape_intent("Ring"), "product_search")
        self.assertEqual(_store_pincode_escape_intent("earrings"), "product_search")

    def test_classifier_runs_for_bare_ring_while_awaiting_pincode(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "Ring"}},
            "user_profile": {
                "awaiting_store_pincode": True,
                "service_selected": SL.AD_FLOW.value,
                "chat_history": [{"role": "user", "content": "store in udaipur"}],
                "last_message_at": _fresh_ts(),
            },
        }
        self.assertTrue(clf.should_run(data))

    def test_greeting_clears_awaiting_store_pincode(self):
        profile = {
            "awaiting_store_pincode": True,
            "store_pincode_attempts": 2,
            "service_selected": SL.AD_FLOW.value,
            "chat_history": [{"role": "user", "content": "find store"}],
        }
        _clear_state_on_greeting(profile)
        self.assertFalse(profile.get("awaiting_store_pincode"))
        self.assertNotIn("store_pincode_attempts", profile)
        self.assertEqual(profile.get("service_selected"), "")

    def test_greeting_shortcut_clears_store_wait(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Hey"}},
                "user_profile": {
                    "awaiting_store_pincode": True,
                    "service_selected": SL.AD_FLOW.value,
                    "chat_history": [{"role": "user", "content": "find store"}],
                    "username": "Rajendra",
                    "last_message_at": _fresh_ts(),
                },
            }
            result = await clf.process(data)
            self.assertEqual(result["classified_category"], "greeting")
            self.assertFalse(result["user_profile"].get("awaiting_store_pincode"))
            self.assertIn("Welcome back", result["bot_response"][0]["text"])

        asyncio.run(_run())

    def test_bare_ring_escape_routes_product_search(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Ring"}},
                "user_profile": {
                    "awaiting_store_pincode": True,
                    "service_selected": SL.AD_FLOW.value,
                    "chat_history": [{"role": "user", "content": "find store"}],
                    "last_message_at": _fresh_ts(),
                },
            }
            result = await clf.process(data)
            self.assertFalse(result["user_profile"].get("awaiting_store_pincode"))
            self.assertEqual(result["classified_category"], "product_search")
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.PRODUCT_SEARCH.value,
            )
            ents = result["user_profile"].get("llm_extracted_entities") or {}
            self.assertEqual(ents.get("category"), "ring")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
