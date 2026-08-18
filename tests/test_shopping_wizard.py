"""Tests for guided shopping wizard smart-skip funnel."""

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

from kisna_chatbot.models.service_list import ServiceList as SL  # noqa: E402
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    ProductSearchAgentV3,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    advance_wizard,
    build_wizard_summary,
    entities_from_wizard,
    filter_by_fulfillment,
    get_next_step,
    seed_wizard_from_entities,
    should_start_wizard,
    start_wizard,
)


class ShoppingWizardTests(unittest.TestCase):
    def test_seed_and_smart_skip(self):
        seeded = seed_wizard_from_entities(
            {
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "max_price": 20000,
                "min_price": 0,
                "fulfillment": "ready",
            }
        )
        self.assertIsNone(get_next_step(seeded))
        self.assertFalse(should_start_wizard(seeded))
        # Occasion is no longer a wizard step
        self.assertNotIn("occasion", seeded)

    def test_next_step_after_category_only(self):
        seeded = seed_wizard_from_entities({"category": "ring"})
        self.assertEqual(get_next_step(seeded), "gender")
        self.assertTrue(should_start_wizard({"category": "ring"}))

    def test_start_wizard_asks_gender(self):
        profile = {}
        responses = start_wizard(profile, entities={"category": "ring"})
        self.assertTrue(profile["shopping_wizard_active"])
        self.assertEqual(profile["shopping_wizard_step"], "gender")
        self.assertEqual(responses[0]["type"], "quickreply")
        self.assertEqual(responses[0]["msgid"], "wizard$gender")

    def test_advance_gender_then_material(self):
        profile = {}
        start_wizard(profile, entities={"category": "ring"})
        messages = {
            "interactive": {
                "type": "button_reply",
                "button_reply": {
                    "id": "wizard$gender",
                    "title": "Female",
                },
            }
        }
        status, responses = advance_wizard(profile, messages)
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "women")
        self.assertEqual(profile["shopping_wizard_step"], "material")
        self.assertEqual(responses[0]["msgid"], "wizard$material")

    def test_summary_copy(self):
        text = build_wizard_summary(
            {
                "category": "ring",
                "material_type": "diamond",
                "max_price": 20000,
                "min_price": 0,
            }
        )
        self.assertIn("diamond", text.lower())
        self.assertIn("ring", text.lower())
        self.assertIn("20,000", text)

    def test_entities_from_wizard(self):
        ents = entities_from_wizard(
            {
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "min_price": 0,
                "max_price": 20000,
                "fulfillment": "ready",
            }
        )
        self.assertEqual(ents["category"], "ring")
        self.assertEqual(ents["fulfillment"], "ready")
        self.assertEqual(ents["gender"], "women")
        self.assertIsNone(ents.get("occasion"))

    def test_fulfillment_completes_wizard(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "min_price": 0,
                "max_price": 20000,
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        messages = {
            "interactive": {
                "type": "button_reply",
                "button_reply": {
                    "id": "wizard$fulfillment",
                    "title": "Ready to ship",
                },
            }
        }
        status, responses = advance_wizard(profile, messages)
        self.assertEqual(status, "complete")
        self.assertIsNone(responses)
        self.assertEqual(profile["shopping_wizard_data"]["fulfillment"], "ready")

    def test_ready_to_ship_filter(self):
        products = [
            {"title": "fast", "shipping": {"edd": 5}},
            {"title": "slow", "shipping": {"edd": 20}},
        ]
        ready, note = filter_by_fulfillment(products, "ready")
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["title"], "fast")
        self.assertIsNone(note)

    def test_mto_does_not_post_filter(self):
        products = [
            {"title": "a", "shipping": {"edd": 5}},
            {"title": "b", "shipping": {"edd": 20}},
        ]
        out, note = filter_by_fulfillment(products, "mto")
        self.assertEqual(len(out), 2)
        self.assertIsNone(note)

    def test_summary_ready_vs_mto(self):
        ready = build_wizard_summary(
            {
                "category": "ring",
                "material_type": "diamond",
                "max_price": 20000,
                "min_price": 0,
                "fulfillment": "ready",
            }
        )
        self.assertIn("ready-to-ship", ready.lower())
        mto = build_wizard_summary(
            {
                "category": "ring",
                "material_type": "gold",
                "fulfillment": "mto",
            }
        )
        self.assertIn("made to order", mto.lower())

    def test_entities_to_api_params_gender_and_availability(self):
        from kisna_chatbot.processors.entity_extractor import entities_to_api_params

        ready = entities_to_api_params(
            {
                "category": "ring",
                "material_type": "diamond",
                "gender": "women",
                "fulfillment": "ready",
                "max_price": 20000,
                "min_price": 0,
            }
        )
        self.assertTrue(ready.get("ready_to_ship"))
        self.assertNotIn("made_to_order", ready)
        self.assertEqual(
            ready.get("tag_manager_id"), "6710b86de3421b6a92589b39"
        )

        mto = entities_to_api_params(
            {"category": "ring", "fulfillment": "mto", "gender": "men"}
        )
        self.assertTrue(mto.get("made_to_order"))
        self.assertNotIn("ready_to_ship", mto)
        self.assertEqual(mto.get("tag_manager_id"), "66ec862c348e37f29673a282")

    def test_ready_to_ship_relaxes_when_empty(self):
        products = [
            {"title": "slow", "shipping": {"edd": 20}},
        ]
        ready, note = filter_by_fulfillment(products, "ready")
        self.assertEqual(len(ready), 1)
        self.assertIsNone(note)

    def test_start_wizard_clears_stale_store_wait(self):
        profile = {
            "awaiting_store_pincode": True,
            "store_pincode_attempts": 2,
        }
        start_wizard(profile, entities={"category": "ring"})
        self.assertTrue(profile.get("shopping_wizard_active"))
        self.assertNotIn("awaiting_store_pincode", profile)
        self.assertNotIn("store_pincode_attempts", profile)

    def test_budget_50k_not_stolen_by_stale_store_wait(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "50k"}},
                "user_profile": {
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
                    "last_message_at": int(time.time()),
                },
            }
            result = await agent.process(data)
            text = (result.get("bot_response") or [{}])[0].get("text", "")
            self.assertNotIn("pincode", text.lower())
            self.assertNotIn("awaiting_store_pincode", result["user_profile"])
            self.assertEqual(
                result["user_profile"].get("shopping_wizard_step"), "fulfillment"
            )

        asyncio.run(_run())

    def test_budget_text_advance(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "budget")
        status, responses = advance_wizard(
            profile, {}, text="20000"
        )
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        self.assertIsNotNone(profile["shopping_wizard_data"].get("max_price"))

    def test_fulfillment_text_in_stock(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "gold",
                "max_price": 20000,
                "min_price": 0,
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        status, _ = advance_wizard(profile, {}, text="in stock please")
        self.assertEqual(status, "complete")
        self.assertEqual(profile["shopping_wizard_data"]["fulfillment"], "ready")

    def test_mid_wizard_gender_restate_overwrites(self):
        profile = {}
        start_wizard(
            profile,
            entities={"category": "ring", "gender": "women"},
        )
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "women")
        self.assertEqual(profile["shopping_wizard_step"], "material")
        status, _ = advance_wizard(profile, {}, text="for men gold")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "men")
        self.assertEqual(profile["shopping_wizard_data"]["material_type"], "gold")


if __name__ == "__main__":
    unittest.main()