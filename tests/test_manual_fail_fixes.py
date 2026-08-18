"""LLM-primary sticky escape + title match + Indic wizard regressions."""

import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, patch

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
from kisna_chatbot.processors.classifier import Classifier  # noqa: E402
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    _handle_typed_product_title,
    _match_shown_product_by_title,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    _parse_text_for_step,
)


class StickyEscapeLlmPrimaryTests(unittest.TestCase):
    def test_connect_me_with_agent_during_wizard_goes_to_llm(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Connect me with agent"}},
                "user_profile": {
                    "chat_history": [],
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "shopping_wizard_active": True,
                    "shopping_wizard_step": "budget",
                    "shopping_wizard_data": {"category": "ring"},
                    "last_message_at": _fresh_ts(),
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {"intent": "human_handoff", "confidence": 0.95, "entities": {}}
                ),
            ) as mock_llm, patch(
                "kisna_chatbot.processors.support_handler.send_customer_support_template"
            ), patch(
                "kisna_chatbot.processors.support_handler.get_support_status",
                return_value={"status": "open"},
            ):
                result = await clf.process(data)
            mock_llm.assert_called_once()
            system = mock_llm.call_args.kwargs["messages"][0]["content"]
            self.assertIn("live-agent", system.lower())
            self.assertEqual(result["classified_category"], "human_handoff")
            self.assertTrue(result["user_profile"].get("live_agent_required"))
            self.assertFalse(result["user_profile"].get("shopping_wizard_active"))
            text = (result["bot_response"][0].get("text") or "").lower()
            self.assertNotIn("samajh nahi", text)
            self.assertNotIn("didn't catch", text)

        asyncio.run(_run())

    def test_call_me_back_during_wizard_llm_callback(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "call me back"}},
                "user_profile": {
                    "chat_history": [],
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "shopping_wizard_active": True,
                    "shopping_wizard_step": "gender",
                    "shopping_wizard_data": {"category": "ring"},
                    "last_message_at": _fresh_ts(),
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                return_value=json.dumps(
                    {"intent": "callback", "confidence": 0.95, "entities": {}}
                ),
            ) as mock_llm, patch(
                "kisna_chatbot.config.gupshup.get_callback_flow_id",
                return_value="flow_cb",
            ):
                result = await clf.process(data)
            mock_llm.assert_called_once()
            self.assertEqual(result["classified_category"], "callback")
            types = [r.get("type") for r in result["bot_response"]]
            self.assertIn("flow", types)
            self.assertFalse(result["user_profile"].get("shopping_wizard_active"))

        asyncio.run(_run())

    def test_indic_wizard_slot_skips_classifier(self):
        clf = Classifier()
        data = {
            "phone_number": "919999999999",
            "messages": {"text": {"body": "डाइमंड"}},
            "user_profile": {
                "shopping_wizard_active": True,
                "shopping_wizard_step": "material",
                "shopping_wizard_data": {"category": "necklace"},
                "service_selected": SL.PRODUCT_SEARCH.value,
                "last_message_at": _fresh_ts(),
            },
        }
        self.assertFalse(clf.should_run(data))


class IndicWizardMaterialTests(unittest.TestCase):
    def test_devanagari_diamond_parses(self):
        self.assertEqual(_parse_text_for_step("material", "डाइमंड"), "diamond")
        self.assertEqual(_parse_text_for_step("material", "डायमंड"), "diamond")
        self.assertEqual(_parse_text_for_step("material", "सोना"), "gold")


class TypedTitleMatchTests(unittest.TestCase):
    def test_match_starred_title(self):
        shown = [
            {"_id": "1", "title": "Raya Diamond Necklace", "price": 60000},
            {"_id": "2", "title": "Glimmering Diamond Pendant", "price": 55000},
        ]
        hit = _match_shown_product_by_title("*Glimmering Diamond Pendant*", shown)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["_id"], "2")

    def test_open_title_clears_wizard(self):
        data = {
            "user_profile": {
                "shopping_wizard_active": True,
                "shopping_wizard_step": "gender",
                "last_search_products": [
                    {
                        "_id": "2",
                        "title": "Glimmering Diamond Pendant",
                        "price": 55000,
                        "mediaUrl": "",
                    }
                ],
            }
        }
        with patch(
            "kisna_chatbot.processors.product_search_agent_v3.build_product_image_with_cta_message",
            return_value=None,
        ), patch(
            "kisna_chatbot.processors.product_details_agent._save_last_viewed_product"
        ):
            result = _handle_typed_product_title(
                data, "*Glimmering Diamond Pendant*"
            )
        self.assertIsNotNone(result)
        self.assertFalse(data["user_profile"].get("shopping_wizard_active"))
        self.assertEqual(data["classified_category"], "product_info")
        self.assertTrue(data["bot_response"])


if __name__ == "__main__":
    unittest.main()
