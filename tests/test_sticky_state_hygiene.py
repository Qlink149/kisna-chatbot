"""Client-handover sticky-state hygiene regressions."""

import asyncio
import os
import time
import unittest

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GROQ_API_KEY": "test",
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
    _PAGINATION_ONLY_RE,
    _sticky_wait_escape_intent,
)
from kisna_chatbot.processors.entity_extractor import merge_search_entities  # noqa: E402
from kisna_chatbot.utils.session_state import (  # noqa: E402
    maybe_expire_session,
    reset_session_on_fresh_start,
)


class FreshStartResetTests(unittest.TestCase):
    def test_greeting_clears_wizard_and_search(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Hey"}},
                "user_profile": {
                    "shopping_wizard_active": True,
                    "shopping_wizard_step": "gender",
                    "shopping_wizard_data": {"category": "ring"},
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "last_search_filters": {"category": "ring", "gender": "women"},
                    "last_search_products": [{"_id": "1"}],
                    "chat_history": [{"role": "user", "content": "rings"}],
                    "username": "Priya",
                    "last_message_at": _fresh_ts(),
                },
            }
            result = await clf.process(data)
            profile = result["user_profile"]
            self.assertEqual(result["classified_category"], "greeting")
            self.assertFalse(profile.get("shopping_wizard_active"))
            self.assertNotIn("shopping_wizard_data", profile)
            self.assertNotIn("last_search_filters", profile)
            self.assertNotIn("last_search_products", profile)
            self.assertEqual(profile.get("service_selected"), "")
            self.assertIn("Welcome back", result["bot_response"][0]["text"])

        asyncio.run(_run())

    def test_menu_clears_callback_capture(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "menu"}},
                "user_profile": {
                    "callback_capture_step": 2,
                    "callback_draft": {"request_type": "callback"},
                    "service_selected": SL.CALLBACK.value,
                    "chat_history": [{"role": "user", "content": "call me"}],
                    "last_message_at": _fresh_ts(),
                },
            }
            result = await clf.process(data)
            profile = result["user_profile"]
            self.assertEqual(result["classified_category"], "menu_help")
            self.assertNotIn("callback_capture_step", profile)
            self.assertNotIn("callback_draft", profile)
            self.assertEqual(profile.get("service_selected"), "")

        asyncio.run(_run())

    def test_greeting_wipes_filters_so_budget_alone_does_not_inherit(self):
        profile = {
            "last_search_filters": {"category": "ring", "material_type": "gold"},
            "shopping_wizard_active": True,
        }
        reset_session_on_fresh_start(profile)
        prior = profile.get("last_search_filters")
        merged = merge_search_entities(
            prior,
            {
                "category": None,
                "material_type": None,
                "min_price": None,
                "max_price": 20000,
                "title": None,
            },
            "I want them under 20k",
        )
        self.assertIsNone(merged.get("category"))
        self.assertEqual(merged.get("max_price"), 20000)


class StickyWaitEscapeTests(unittest.TestCase):
    def test_wizard_offers_escape(self):
        self.assertEqual(_sticky_wait_escape_intent("show offers"), "offers")
        self.assertEqual(_sticky_wait_escape_intent("find store"), "store_info")
        self.assertEqual(_sticky_wait_escape_intent("Ring"), "product_search")

    def test_wizard_active_escape_routes_product_search(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Ring"}},
                "user_profile": {
                    "shopping_wizard_active": True,
                    "shopping_wizard_step": "gender",
                    "shopping_wizard_data": {"category": "necklace"},
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "jewellery"}],
                    "last_message_at": _fresh_ts(),
                },
            }
            self.assertTrue(clf.should_run(data))
            result = await clf.process(data)
            self.assertFalse(result["user_profile"].get("shopping_wizard_active"))
            self.assertEqual(result["classified_category"], "product_search")
            ents = result["user_profile"].get("llm_extracted_entities") or {}
            self.assertEqual(ents.get("category"), "ring")

        asyncio.run(_run())

    def test_callback_capture_then_ring_escapes(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Ring"}},
                "user_profile": {
                    "callback_capture_step": 1,
                    "callback_draft": {"request_type": "callback"},
                    "service_selected": SL.CALLBACK.value,
                    "chat_history": [{"role": "user", "content": "call me back"}],
                    "last_message_at": _fresh_ts(),
                },
            }
            self.assertTrue(clf.should_run(data))
            result = await clf.process(data)
            self.assertNotIn("callback_capture_step", result["user_profile"])
            self.assertEqual(result["classified_category"], "product_search")

        asyncio.run(_run())

    def test_bare_pincode_still_skips_classifier(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "400001"}},
            "user_profile": {
                "awaiting_store_pincode": True,
                "chat_history": [{"role": "user", "content": "find store"}],
                "last_message_at": _fresh_ts(),
            },
        }
        self.assertFalse(clf.should_run(data))

    def test_wizard_budget_beats_stale_store_wait(self):
        """Stale awaiting_store_pincode must not steal wizard budget ('50k')."""
        from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
        from kisna_chatbot.processors.classifier import _apply_store_pincode_shortcut

        clf = Classifier()
        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "budget",
            "shopping_wizard_data": {
                "category": "ring",
                "gender": "men",
                "material_type": "gold",
            },
            "awaiting_store_pincode": True,
            "service_selected": SL.PRODUCT_SEARCH.value,
            "chat_history": [{"role": "user", "content": "Ring"}],
            "last_message_at": _fresh_ts(),
        }
        data = {
            "messages": {"text": {"body": "50k"}},
            "user_profile": profile,
        }
        self.assertFalse(clf.should_run(data))
        self.assertFalse(_apply_store_pincode_shortcut(data))
        self.assertFalse(AdFlowAgent().should_run(data))
        self.assertEqual(profile.get("service_selected"), SL.PRODUCT_SEARCH.value)
        self.assertTrue(profile.get("shopping_wizard_active"))


class ContinuationGateTests(unittest.TestCase):
    def test_something_else_does_not_skip_classifier(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "something else"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "gold rings"}],
                "last_search_filters": {"category": "ring"},
                "last_message_at": _fresh_ts(),
            },
        }
        self.assertTrue(clf.should_run(data))
        self.assertIsNone(_PAGINATION_ONLY_RE.match("something else"))

    def test_show_more_still_skips(self):
        clf = Classifier()
        data = {
            "messages": {"text": {"body": "show more"}},
            "user_profile": {
                "service_selected": SL.PRODUCT_SEARCH.value,
                "chat_history": [{"role": "user", "content": "gold rings"}],
                "last_message_at": _fresh_ts(),
            },
        }
        self.assertFalse(clf.should_run(data))


class TtlMissingTimestampTests(unittest.TestCase):
    def test_missing_last_message_at_clears_sticky_flags(self):
        profile = {
            "awaiting_store_pincode": True,
            "shopping_wizard_active": True,
            "service_selected": SL.AD_FLOW.value,
            "last_search_filters": {"category": "ring"},
        }
        maybe_expire_session(profile)
        self.assertNotIn("awaiting_store_pincode", profile)
        self.assertNotIn("shopping_wizard_active", profile)
        self.assertEqual(profile.get("service_selected"), "")
        self.assertNotIn("last_search_filters", profile)

    def test_missing_last_message_at_without_flags_noop(self):
        profile = {"service_selected": SL.PRODUCT_SEARCH.value, "username": "Asha"}
        maybe_expire_session(profile)
        self.assertEqual(profile["service_selected"], SL.PRODUCT_SEARCH.value)
        self.assertEqual(profile["username"], "Asha")


if __name__ == "__main__":
    unittest.main()
