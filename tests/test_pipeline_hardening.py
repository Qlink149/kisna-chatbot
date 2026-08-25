"""Regressions for send-loop resilience, wizard escape carryover and budgets."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

for _k, _v in {
    "ENV_MODE": "dev",
    "MONGO_URI": "mongodb://localhost:27017",
    "OPENAI_API_KEY": "test-key",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    _extract_prices,
    _snap_single_price_to_band,
    extract_fulfillment,
    extract_fulfillment_change,
)
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    ProductSearchAgentV3,
)
from kisna_chatbot.processors.response_manager import ResponseManager  # noqa: E402
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    ANY_SLOT,
    _parse_text_for_step,
    advance_wizard,
    entities_from_wizard,
    get_next_step,
)


class SendLoopResilienceTests(unittest.TestCase):
    def test_one_failing_send_does_not_drop_the_rest(self):
        """A flaky CTA used to abort the turn, losing later cards silently."""
        manager = ResponseManager()
        sent: list[str] = []

        def ok(phone_number, bot_response):
            sent.append(bot_response["text"])
            return {"status": "submitted"}

        def boom(phone_number, bot_response):
            raise RuntimeError("gupshup down")

        data = {
            "phone_number": "919999999999",
            "user_profile": {"last_user_message_at": 9e18},
            "bot_response": [
                {"type": "text", "text": "first"},
                {"type": "cta_url", "text": "explodes"},
                {"type": "text", "text": "third"},
            ],
        }
        with patch.dict(
            manager._handlers, {"text": ok, "cta_url": boom}, clear=False
        ), patch(
            "kisna_chatbot.processors.response_manager.is_window_open",
            return_value=True,
        ), patch("kisna_chatbot.processors.response_manager.time.sleep"):
            manager.handle_responses(data=data)

        self.assertEqual(sent, ["first", "third"])


class WizardEscapeCarryoverTests(unittest.TestCase):
    def test_escape_keeps_button_tapped_slots(self):
        """"browse all" mid-funnel used to throw away Female + Gold."""
        agent = ProductSearchAgentV3()
        data = {
            "phone_number": "919999999999",
            "messages": {"text": {"body": "browse all"}},
            "user_profile": {
                "shopping_wizard_active": True,
                "shopping_wizard_step": "budget",
                "shopping_wizard_data": {
                    "category": "ring",
                    "gender": "women",
                    "material_type": "gold",
                },
                "chat_history": [{"role": "user", "content": "rings"}],
            },
            "classified_category": "product_search",
        }
        with patch(
            "kisna_chatbot.processors.product_search_agent_v3.search_products",
            new_callable=AsyncMock,
        ):
            result = asyncio.run(agent._handle_shopping_wizard(data, "919999999999"))

        profile = result["user_profile"]
        collected = profile.get("shopping_wizard_data") or {}
        self.assertEqual(collected.get("gender"), "women")
        self.assertEqual(collected.get("material_type"), "gold")
        self.assertNotEqual(profile.get("shopping_wizard_step"), "gender")


class GenderAnySlotTests(unittest.TestCase):
    def _gender_step_profile(self) -> dict:
        return {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "gender",
            "shopping_wizard_data": {"category": "ring"},
        }

    def test_koi_bhi_answers_gender_instead_of_escaping(self):
        profile = self._gender_step_profile()
        status, responses = advance_wizard(profile, {}, text="koi bhi")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], ANY_SLOT)
        self.assertEqual(profile["shopping_wizard_step"], "material")
        self.assertTrue(responses)

    def test_anyone_answers_gender(self):
        profile = self._gender_step_profile()
        status, _ = advance_wizard(profile, {}, text="anyone")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], ANY_SLOT)

    def test_any_slot_counts_as_filled_but_sends_no_filter(self):
        collected = {
            "category": "ring",
            "gender": ANY_SLOT,
            "material_type": "gold",
            "min_price": 1,
            "max_price": 2,
            "fulfillment": "ready",
        }
        self.assertIsNone(get_next_step(collected))
        self.assertIsNone(entities_from_wizard(collected)["gender"])

    def test_no_specific_budget_is_accepted(self):
        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "budget",
            "shopping_wizard_data": {
                "category": "ring",
                "gender": "women",
                "material_type": "gold",
            },
        }
        status, _ = advance_wizard(profile, {}, text="No specific budget")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        entities = entities_from_wizard(profile["shopping_wizard_data"])
        self.assertIsNone(entities["min_price"])
        self.assertIsNone(entities["max_price"])

    def test_skip_on_a_filter_step_answers_it(self):
        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "material",
            "shopping_wizard_data": {"category": "ring", "gender": "women"},
        }
        status, _ = advance_wizard(profile, {}, text="skip")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_step"], "budget")
        self.assertIsNone(
            entities_from_wizard(profile["shopping_wizard_data"])["material_type"]
        )

    def test_either_is_fine_completes_the_funnel(self):
        collected = {
            "category": "ring",
            "gender": "women",
            "material_type": "gold",
            "budget": ANY_SLOT,
            "fulfillment": ANY_SLOT,
        }
        self.assertIsNone(get_next_step(collected))
        self.assertIsNone(entities_from_wizard(collected)["fulfillment"])

    def test_koi_bhi_still_escapes_on_other_steps(self):
        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "category",
            "shopping_wizard_data": {},
        }
        status, _ = advance_wizard(profile, {}, text="koi bhi")
        self.assertEqual(status, "escape")


class FulfillmentNegationFallbackTests(unittest.TestCase):
    """Regex fallback for when the LLM returns no availability at all."""

    def test_a_refusal_is_not_a_request(self):
        self.assertIsNone(extract_fulfillment("mujhe ready to ship nahi chahiye"))
        self.assertIsNone(extract_fulfillment("I don't want ready to ship"))
        self.assertEqual(
            extract_fulfillment_change("mujhe ready to ship nahi chahiye"), "clear"
        )

    def test_a_plain_phrase_still_reads_normally(self):
        self.assertEqual(extract_fulfillment("ready to ship chahiye"), "ready")
        self.assertEqual(extract_fulfillment("Mujhe make to order chahiye"), "mto")
        self.assertEqual(extract_fulfillment_change("ready to ship"), "ready")


class WizardBudgetParsingTests(unittest.TestCase):
    def test_bare_amount_uses_the_shared_band(self):
        self.assertEqual(
            _parse_text_for_step("budget", "20000"),
            _snap_single_price_to_band(20000),
        )

    def test_pincode_is_not_a_budget(self):
        self.assertIsNone(_parse_text_for_step("budget", "400001"))
        self.assertIsNone(_parse_text_for_step("budget", "560001"))

    def test_round_six_digit_amount_is_still_a_budget(self):
        self.assertIsNotNone(_parse_text_for_step("budget", "100000"))

    def test_two_digit_answer_uses_the_shared_band(self):
        """A single stated amount lands in its bracket at every magnitude.

        This previously asserted a two-digit answer was rejected so the funnel
        would re-ask. That only ever held here, where _parse_text_for_step is
        called without llm_entities. Production always supplies them, and the
        model's literal read won before the rejection could apply — a customer
        answering "25" got a recap of "under Rs 25" and a maxPrice=25 search
        that matched nothing. Banding it is the consistent rule; a customer who
        means 25,000 types "25k".
        """
        self.assertEqual(
            _parse_text_for_step("budget", "50"),
            _snap_single_price_to_band(50),
        )
        self.assertEqual(
            _parse_text_for_step("budget", "50", {"min_price": None, "max_price": 50}),
            _snap_single_price_to_band(50),
        )


class HinglishRangeTests(unittest.TestCase):
    def test_se_range_without_tak(self):
        self.assertEqual(_extract_prices("50k se 1 lakh"), (50000, 100000))

    def test_se_range_with_tak_still_works(self):
        self.assertEqual(_extract_prices("20k se 50k tak"), (20000, 50000))

    def test_se_upar_is_a_minimum_not_a_range(self):
        min_p, max_p = _extract_prices("50k se upar")
        self.assertEqual(min_p, 50000)
        self.assertIsNone(max_p)

    def test_english_thousand_range(self):
        self.assertEqual(_extract_prices("15 to 35 thousand"), (15000, 35000))
        self.assertEqual(_extract_prices("15-35 thousand"), (15000, 35000))
        self.assertEqual(
            _extract_prices("between 15 and 35 thousand"), (15000, 35000)
        )

    def test_wizard_budget_thousand_range_not_digit_concat(self):
        # Regression: digit-strip turned "15 to 35 thousand" into ₹1535.
        self.assertEqual(
            _parse_text_for_step("budget", "15 to 35 thousand"),
            (15000.0, 35000.0),
        )
        band = _parse_text_for_step("budget", "15 to 35 thousand")
        self.assertNotEqual(band, _snap_single_price_to_band(1535))


if __name__ == "__main__":
    unittest.main()
