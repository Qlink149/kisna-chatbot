"""Confirm-before-search recap: wording, yes, no, and correction re-recap."""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("KISNA_UTM_ENABLED", "false")

from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
from kisna_chatbot.processors.search_confirmation import (
    CONFIRM_MSGID,
    build_confirm_prompt,
    build_search_recap,
    has_pending_search,
    parse_confirm_reply,
    should_confirm,
)

_PRODUCTS = [
    {
        "_id": "p1",
        "title": "Kody Ring",
        "category": "ring",
        "materialType": "diamond",
        "price": {"finalPrice": 19151},
    },
]


def _text_message(body: str) -> dict:
    return {"text": {"body": body}, "type": "text"}


def _button_message(title: str, msgid: str = CONFIRM_MSGID) -> dict:
    return {
        "interactive": {
            "type": "button_reply",
            "button_reply": {
                "id": json.dumps({"msgid": msgid}),
                "title": title,
            },
        }
    }


class ConfirmEnabledMixin:
    """The autouse conftest fixture disables the recap; turn it back on here."""

    def setUp(self):
        self._prev = os.environ.get("KISNA_SEARCH_CONFIRM_ENABLED")
        os.environ["KISNA_SEARCH_CONFIRM_ENABLED"] = "true"

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("KISNA_SEARCH_CONFIRM_ENABLED", None)
        else:
            os.environ["KISNA_SEARCH_CONFIRM_ENABLED"] = self._prev


class RecapWordingTests(unittest.TestCase):
    def test_full_recap(self):
        recap = build_search_recap(
            {
                "category": "ring",
                "material_type": "diamond",
                "gender": "men",
                "min_price": 15000,
                "max_price": 30000,
                "fulfillment": "ready",
            }
        )
        self.assertEqual(
            recap,
            "diamond rings for men between ₹15,000 and ₹30,000 ready to ship",
        )

    def test_max_only_reads_under(self):
        recap = build_search_recap({"category": "ring", "max_price": 50000})
        self.assertEqual(recap, "rings under ₹50,000")

    def test_zero_min_still_reads_under(self):
        recap = build_search_recap(
            {"category": "ring", "min_price": 0, "max_price": 50000}
        )
        self.assertEqual(recap, "rings under ₹50,000")

    def test_min_only_reads_above(self):
        recap = build_search_recap({"category": "earring", "min_price": 20000})
        self.assertEqual(recap, "earrings above ₹20,000")

    def test_made_to_order_named(self):
        recap = build_search_recap({"category": "ring", "fulfillment": "mto"})
        self.assertEqual(recap, "rings made to order")

    def test_either_fulfillment_says_nothing(self):
        recap = build_search_recap({"category": "ring", "fulfillment": None})
        self.assertEqual(recap, "rings")
        self.assertNotIn("ship", build_search_recap({"category": "ring"}))

    def test_no_gender_phrase_when_unset(self):
        recap = build_search_recap({"category": "ring", "material_type": "gold"})
        self.assertEqual(recap, "gold rings")

    def test_multi_category_joined(self):
        recap = build_search_recap(
            {"categories": ["ring", "earring"], "material_type": "gold"}
        )
        self.assertEqual(recap, "gold rings and earrings")

    def test_empty_entities_not_worth_confirming(self):
        self.assertFalse(should_confirm({}))
        self.assertFalse(should_confirm({"category": None, "title": "Kody"}))
        self.assertTrue(should_confirm({"category": "ring"}))
        self.assertTrue(should_confirm({"material_type": "gold"}))

    def test_prompt_shape(self):
        prompt = build_confirm_prompt({"category": "ring"})
        self.assertEqual(prompt["type"], "quickreply")
        self.assertEqual(prompt["msgid"], CONFIRM_MSGID)
        self.assertEqual(
            [o["title"] for o in prompt["options"]], ["Yes, show me", "No, change it"]
        )
        self.assertIn("rings", prompt["text"])


class ParseConfirmReplyTests(unittest.TestCase):
    def test_button_titles(self):
        self.assertEqual(parse_confirm_reply(_button_message("Yes, show me")), "yes")
        self.assertEqual(parse_confirm_reply(_button_message("No, change it")), "no")

    def test_typed_answers(self):
        for text in ("yes", "haan", "ok", "sahi hai", "Yes!"):
            self.assertEqual(parse_confirm_reply({}, text), "yes", text)
        for text in ("no", "nahi", "galat", "change"):
            self.assertEqual(parse_confirm_reply({}, text), "no", text)

    def test_new_query_is_not_an_answer(self):
        self.assertIsNone(parse_confirm_reply({}, "show me gold necklaces"))


class ConfirmFlowTests(ConfirmEnabledMixin, unittest.TestCase):
    def _agent_data(self, messages: dict, user_profile: dict | None = None) -> dict:
        return {
            "phone_number": "919999999999",
            "messages": messages,
            "user_profile": user_profile
            if user_profile is not None
            else {"service_selected": SL.PRODUCT_SEARCH.value},
        }

    def _run_search_query(self, data: dict, llm_entities: dict) -> tuple[dict, AsyncMock]:
        async def _run():
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": _PRODUCTS, "total_count": 1, "page": 1},
            ) as search_mock, patch(
                "kisna_chatbot.processors.product_search_agent_v3"
                ".extract_entities_with_llm",
                new_callable=AsyncMock,
                return_value=llm_entities,
            ):
                result = await ProductSearchAgentV3().process(data)
            return result, search_mock

        return asyncio.run(_run())

    def test_text_search_asks_before_calling_clara(self):
        data = self._agent_data(_text_message("diamond rings for men under 50000"))
        result, search_mock = self._run_search_query(
            data,
            {
                "category": "ring",
                "material_type": "diamond",
                "gender": "men",
                "max_price": 50000,
            },
        )
        search_mock.assert_not_called()
        reply = result["bot_response"][0]
        self.assertEqual(reply["type"], "quickreply")
        self.assertIn("diamond rings", reply["text"])
        self.assertIn("for men", reply["text"])
        self.assertTrue(has_pending_search(data["user_profile"]))

    def test_yes_runs_the_pending_search(self):
        profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "pending_search": {
                "entities": {"category": "ring", "material_type": "diamond"},
                "query_label": "diamond rings",
                "occasion_prefix": None,
                "response_mode": None,
                "exclude_product_id": None,
            },
        }

        async def _run():
            data = self._agent_data(_button_message("Yes, show me"), profile)
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": _PRODUCTS, "total_count": 1, "page": 1},
            ) as search_mock:
                result = await ProductSearchAgentV3().process(data)
            return result, search_mock

        result, search_mock = asyncio.run(_run())
        search_mock.assert_awaited()
        params = search_mock.await_args_list[0].kwargs or {}
        self.assertEqual(params.get("materialType") or params.get("material_type"), "diamond")
        self.assertFalse(has_pending_search(profile))
        self.assertNotEqual(result["bot_response"][0].get("msgid"), CONFIRM_MSGID)

    def test_yes_runs_even_when_last_search_at_is_stale(self):
        """Live bug: recap Yes hit expiry before confirm and fell to fallback."""
        import time

        profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "last_search_at": int(time.time()) - (19 * 60 * 60),
            "last_search_filters": {"category": "pendant"},
            "pending_search": {
                "entities": {"category": "ring", "material_type": "gold"},
                "query_label": "live-trace:confirm",
                "occasion_prefix": None,
                "response_mode": None,
                "exclude_product_id": None,
            },
        }

        async def _run():
            data = self._agent_data(_button_message("Yes, show me"), profile)
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": _PRODUCTS, "total_count": 1, "page": 1},
            ) as search_mock:
                result = await ProductSearchAgentV3().process(data)
            return result, search_mock

        result, search_mock = asyncio.run(_run())
        search_mock.assert_awaited()
        params = search_mock.await_args_list[0].kwargs or {}
        self.assertEqual(params.get("materialType") or params.get("material_type"), "gold")
        self.assertIn("bot_response", result)
        self.assertNotIn("couldn't help", (result["bot_response"][0].get("text") or "").lower())

    def test_confirm_tap_without_pending_asks_to_search_again(self):
        profile = {"service_selected": SL.PRODUCT_SEARCH.value}

        async def _run():
            data = self._agent_data(_button_message("Yes, show me"), profile)
            return await ProductSearchAgentV3().process(data)

        result = asyncio.run(_run())
        text = (result["bot_response"][0].get("text") or "").lower()
        self.assertIn("expired", text)

    def test_no_asks_what_to_change_and_keeps_slots(self):
        profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "pending_search": {
                "entities": {"category": "ring", "material_type": "diamond"},
                "query_label": "diamond rings",
                "occasion_prefix": None,
                "response_mode": None,
                "exclude_product_id": None,
            },
        }

        async def _run():
            data = self._agent_data(_button_message("No, change it"), profile)
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
            ) as search_mock:
                result = await ProductSearchAgentV3().process(data)
            return result, search_mock

        result, search_mock = asyncio.run(_run())
        search_mock.assert_not_called()
        self.assertIn("change", result["bot_response"][0]["text"].lower())
        self.assertTrue(has_pending_search(profile))
        self.assertTrue(profile.get("awaiting_search_correction"))

    def test_correction_switches_material_and_re_recaps(self):
        profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "awaiting_search_correction": True,
            "pending_search": {
                "entities": {
                    "category": "ring",
                    "material_type": "diamond",
                    "gender": "men",
                    "min_price": 15000,
                    "max_price": 30000,
                },
                "query_label": "diamond rings",
                "occasion_prefix": None,
                "response_mode": None,
                "exclude_product_id": None,
            },
        }
        data = self._agent_data(_text_message("I want in gold"), profile)
        result, search_mock = self._run_search_query(data, {"material_type": "gold"})

        search_mock.assert_not_called()
        reply = result["bot_response"][0]
        self.assertEqual(reply["type"], "quickreply")
        self.assertIn("gold rings", reply["text"])
        self.assertNotIn("diamond", reply["text"])
        # Untouched slots survive the correction.
        self.assertIn("for men", reply["text"])
        self.assertIn("₹15,000", reply["text"])

    def _mangalsutra_profile(self) -> dict:
        return {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "awaiting_search_correction": True,
            "pending_search": {
                "entities": {
                    "category": "mangalsutra",
                    "gender": "women",
                    "material_type": "diamond",
                    "min_price": 20000,
                    "max_price": 30000,
                    "fulfillment": "ready",
                },
                "query_label": "wizard:mangalsutra",
                "occasion_prefix": None,
                "response_mode": None,
                "exclude_product_id": None,
            },
        }

    def test_refusing_ready_to_ship_keeps_every_other_slot(self):
        profile = self._mangalsutra_profile()
        data = self._agent_data(
            _text_message("mujhe ready to ship nahi chahiye"), profile
        )
        # The classifier answers "any" for a refusal, and echoes the category
        # it read from history — the echo must not restart the funnel.
        data["llm_extracted_entities"] = {
            "category": "mangalsutra",
            "fulfillment": "any",
        }
        result, search_mock = self._run_search_query(data, {})

        search_mock.assert_not_called()
        reply = result["bot_response"][0]
        self.assertEqual(reply["type"], "quickreply", reply)
        self.assertNotIn("ready to ship", reply["text"])
        self.assertNotIn("made to order", reply["text"])
        self.assertIn("diamond mangalsutra", reply["text"])
        self.assertIn("for women", reply["text"])
        self.assertIn("₹20,000", reply["text"])
        self.assertNotIn("budget", reply["text"].lower())

    def test_refusal_survives_without_the_llm(self):
        """Regex fallback: same correction when the classifier says nothing."""
        profile = self._mangalsutra_profile()
        data = self._agent_data(
            _text_message("mujhe ready to ship nahi chahiye"), profile
        )
        result, _ = self._run_search_query(data, {})
        self.assertNotIn("ready to ship", result["bot_response"][0]["text"])
        self.assertIn("₹20,000", result["bot_response"][0]["text"])

    def test_made_to_order_correction_switches_availability(self):
        profile = self._mangalsutra_profile()
        data = self._agent_data(_text_message("Mujhe make to order chahiye"), profile)
        data["llm_extracted_entities"] = {
            "category": "mangalsutra",
            "fulfillment": "mto",
        }
        result, search_mock = self._run_search_query(data, {})

        search_mock.assert_not_called()
        reply = result["bot_response"][0]
        self.assertIn("made to order", reply["text"])
        self.assertIn("diamond mangalsutra", reply["text"])
        self.assertIn("₹20,000", reply["text"])

    def test_unrelated_message_drops_the_pending_recap(self):
        profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "pending_search": {
                "entities": {"category": "ring", "material_type": "diamond"},
                "query_label": "diamond rings",
                "occasion_prefix": None,
                "response_mode": None,
                "exclude_product_id": None,
            },
        }
        data = self._agent_data(_text_message("show me gold necklaces"), profile)
        result, search_mock = self._run_search_query(
            data, {"category": "necklace", "material_type": "gold"}
        )
        search_mock.assert_not_called()
        self.assertIn("gold necklaces", result["bot_response"][0]["text"])

    def test_browse_all_tap_skips_the_recap(self):
        profile = {"service_selected": SL.PRODUCT_SEARCH.value}

        async def _run():
            data = self._agent_data(
                _button_message("Explore", msgid="search$explore"), profile
            )
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": _PRODUCTS, "total_count": 1, "page": 1},
            ) as search_mock:
                await ProductSearchAgentV3().process(data)
            return search_mock

        search_mock = asyncio.run(_run())
        search_mock.assert_awaited()
        self.assertFalse(has_pending_search(profile))


class WizardConfirmTests(ConfirmEnabledMixin, unittest.TestCase):
    def test_wizard_completion_recaps_before_products(self):
        profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "shopping_wizard_active": True,
            "shopping_wizard_step": "fulfillment",
            "shopping_wizard_data": {
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "min_price": 15000,
                "max_price": 30000,
            },
        }

        async def _run():
            data = {
                "phone_number": "919999999999",
                "messages": {
                    "interactive": {
                        "type": "button_reply",
                        "button_reply": {
                            "id": json.dumps({"msgid": "wizard$fulfillment"}),
                            "title": "Ready to ship",
                        },
                    }
                },
                "user_profile": profile,
            }
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": _PRODUCTS, "total_count": 1, "page": 1},
            ) as search_mock:
                result = await ProductSearchAgentV3().process(data)
            return result, search_mock

        result, search_mock = asyncio.run(_run())
        search_mock.assert_not_called()
        reply = result["bot_response"][0]
        self.assertEqual(reply["type"], "quickreply")
        self.assertIn("diamond rings", reply["text"])
        self.assertIn("for women", reply["text"])
        self.assertIn("ready to ship", reply["text"])
        self.assertTrue(has_pending_search(profile))


if __name__ == "__main__":
    unittest.main()
