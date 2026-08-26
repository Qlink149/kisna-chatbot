""""Track my order" split into two intents (client-crucial request).

order_status ("has it shipped/been confirmed yet") and track_order ("where is
it / when will it arrive") used to be one intent, order_tracking, with one
URL. They now route to two different destination URLs while sharing the same
ServiceList.ORDER_TRACKING pipeline -- see _CATEGORY_TO_SERVICE in
classifier.py. Both intents are single-shot per turn (no persistent state):
OrderTrackingAgent.process() clears service_selected on every response, so
_resolve_tracking_kind only ever needs to look at THIS turn.
"""

import os
import unittest
from unittest.mock import patch

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

import asyncio

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.processors.classifier import (
    _CATEGORY_TO_SERVICE,
    _keep_order_id_with_its_flow,
    _sticky_wait_escape_intent,
)
from kisna_chatbot.processors.order_tracking_agent import (
    OrderTrackingAgent,
    _resolve_tracking_kind,
)
from kisna_chatbot.models.service_list import ServiceList


class StickyEscapeRoutingTests(unittest.TestCase):
    """The narrow regex escape hatch used when a user is stuck in some other
    wait state (store pincode prompt, wizard, etc) -- not the primary LLM
    classification path, but must still resolve to the right one of the two."""

    def test_status_phrases_route_to_order_status(self):
        for text in (
            "order confirm hua kya",
            "order status",
            "ship hua ya nahi",
        ):
            self.assertEqual(_sticky_wait_escape_intent(text), "order_status", text)

    def test_tracking_phrases_route_to_track_order(self):
        for text in (
            "track my order",
            "track order KIS12345",
            "where is my order",
            "delivery kab hogi",
        ):
            self.assertEqual(_sticky_wait_escape_intent(text), "track_order", text)

    def test_bare_ambiguous_phrase_is_deliberately_unmatched(self):
        """"mera order" alone appeared in BOTH old regexes -- genuinely
        ambiguous with no qualifying word either way. Falling through to no
        match (stay in the current wait state one more turn) is safer than
        confidently routing to the wrong URL."""
        self.assertIsNone(_sticky_wait_escape_intent("mera order"))


class CategoryToServiceTests(unittest.TestCase):
    def test_both_new_intents_map_to_the_existing_order_tracking_service(self):
        self.assertEqual(_CATEGORY_TO_SERVICE["order_status"], ServiceList.ORDER_TRACKING)
        self.assertEqual(_CATEGORY_TO_SERVICE["track_order"], ServiceList.ORDER_TRACKING)


class OrderIdOwnershipCoversBothIntentsTests(unittest.TestCase):
    """A bare order id typed while returns/complaint owns the conversation is
    the answer to THEIR question, not a request to track that order --
    regardless of which of the two new intents the classifier guessed."""

    def test_order_status_does_not_steal_a_returns_prompt_answer(self):
        result = _keep_order_id_with_its_flow(
            {"service_selected": "returns_refund"}, "KIS12345", "order_status"
        )
        self.assertEqual(result, "returns_refund")

    def test_track_order_does_not_steal_a_complaint_prompt_answer(self):
        result = _keep_order_id_with_its_flow(
            {"service_selected": "complaint"}, "KIS12345", "track_order"
        )
        self.assertEqual(result, "complaint")


class ResolveTrackingKindTests(unittest.TestCase):
    def test_track_button_always_wins_regardless_of_classified_category(self):
        interactive = {
            "type": "button_reply",
            "button_reply": {"id": "track$KIS999"},
        }
        data = {"classified_category": "order_status"}
        self.assertEqual(_resolve_tracking_kind(data, interactive), "track_order")

    def test_fresh_classified_category_is_trusted(self):
        self.assertEqual(
            _resolve_tracking_kind({"classified_category": "order_status"}, {}),
            "order_status",
        )
        self.assertEqual(
            _resolve_tracking_kind({"classified_category": "track_order"}, {}),
            "track_order",
        )

    def test_falls_back_to_track_order_when_nothing_else_applies(self):
        """Matches the pre-split default most closely -- e.g. the static
        main-menu button, which sets service_selected without ever setting
        classified_category."""
        self.assertEqual(_resolve_tracking_kind({}, {}), "track_order")
        self.assertEqual(
            _resolve_tracking_kind({"classified_category": "product_search"}, {}),
            "track_order",
        )


class OrderTrackingAgentShouldRunTests(unittest.TestCase):
    def _data(self, **overrides):
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "client_config": get_client_config("kisna"),
            "messages": {},
            "user_profile": {},
        }
        data.update(overrides)
        return data

    def test_runs_for_order_status_category(self):
        agent = OrderTrackingAgent()
        self.assertTrue(agent.should_run(self._data(classified_category="order_status")))

    def test_runs_for_track_order_category(self):
        agent = OrderTrackingAgent()
        self.assertTrue(agent.should_run(self._data(classified_category="track_order")))

    def test_does_not_run_for_unrelated_category(self):
        agent = OrderTrackingAgent()
        self.assertFalse(agent.should_run(self._data(classified_category="offers")))

    def test_runs_for_track_button_regardless_of_category(self):
        agent = OrderTrackingAgent()
        data = self._data(
            messages={
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "track$KIS999"},
                }
            }
        )
        self.assertTrue(agent.should_run(data))


class OrderTrackingAgentProcessTests(unittest.TestCase):
    def _data(self, **overrides):
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "client_config": get_client_config("kisna"),
            "messages": {},
            "user_profile": {},
        }
        data.update(overrides)
        return data

    def test_order_status_uses_status_url_and_tag(self):
        with patch.dict(
            os.environ,
            {
                "KISNA_ORDER_STATUS_URL": "https://kisna.clickpost.in/en",
                "KISNA_ORDER_TRACKING_URL": "https://www.kisna.com/account/order-history",
            },
        ):
            data = self._data(classified_category="order_status")
            asyncio.run(OrderTrackingAgent().process(data))

        response = data["bot_response"]
        self.assertEqual(response[0]["_compose"], "order_status_cta")
        self.assertIn("kisna.clickpost.in", response[0]["url"])

    def test_track_order_uses_tracking_url_and_existing_tag(self):
        with patch.dict(
            os.environ,
            {
                "KISNA_ORDER_STATUS_URL": "https://kisna.clickpost.in/en",
                "KISNA_ORDER_TRACKING_URL": "https://www.kisna.com/account/order-history",
            },
        ):
            data = self._data(classified_category="track_order")
            asyncio.run(OrderTrackingAgent().process(data))

        response = data["bot_response"]
        self.assertEqual(response[0]["_compose"], "order_tracking_cta")
        self.assertIn("kisna.com/account/order-history", response[0]["url"])

    def test_service_selected_is_cleared_after_either_kind(self):
        """Confirms the single-shot-per-turn architecture still holds after
        the split -- no new persistent order_tracking_kind flag was needed."""
        with patch.dict(os.environ, {"KISNA_ORDER_STATUS_URL": "https://x.example"}):
            data = self._data(
                classified_category="order_status",
                user_profile={"service_selected": "order_tracking"},
            )
            asyncio.run(OrderTrackingAgent().process(data))
        self.assertEqual(data["user_profile"]["service_selected"], "")


class OrderStatusUrlAdapterTests(unittest.TestCase):
    def test_uses_the_dedicated_env_var_when_set(self):
        from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter

        adapter = ClientAPIAdapter(get_client_config("kisna"))
        with patch.dict(os.environ, {"KISNA_ORDER_STATUS_URL": "https://kisna.clickpost.in/en"}):
            url = adapter.get_order_status_url("")
        self.assertIn("kisna.clickpost.in", url)

    def test_falls_back_to_the_tracking_url_when_unset(self):
        from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter

        adapter = ClientAPIAdapter(get_client_config("kisna"))
        with patch.dict(
            os.environ,
            {
                "KISNA_ORDER_STATUS_URL": "",
                "KISNA_ORDER_TRACKING_URL": "https://www.kisna.com/account/order-history",
            },
        ):
            url = adapter.get_order_status_url("")
        self.assertIn("kisna.com/account/order-history", url)


if __name__ == "__main__":
    unittest.main()
