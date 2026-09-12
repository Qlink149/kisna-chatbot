"""F9: an agent-ETA / repeated-complaint question hard-routes to a dedicated
handoff-status answer instead of falling through to the classifier's default
(C4: the client's verbatim complaint -- "when will I receive the call" -- got
a Track-Your-Order button). Unconditional -- no on/off flag."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("GUPSHUP_WEBHOOK_SECRET", "test-webhook-secret")

from kisna_chatbot.processors.classifier import (  # noqa: E402
    _programmatic_intent_override,
    _sticky_wait_escape_intent,
)
from kisna_chatbot.processors.support_handler import (  # noqa: E402
    build_handoff_status_response,
)


class HandoffStatusRoutingTests(unittest.TestCase):
    def test_client_exact_phrase_routes_to_handoff_status(self) -> None:
        self.assertEqual(
            _programmatic_intent_override("May I know when I'll recevue the call"),
            ("handoff_status", 0.95),
        )

    def test_repeated_complaint_phrases_route_to_handoff_status(self) -> None:
        for phrase in (
            "this was said before also still not connected",
            "I am waiting from long time",
            "still not connected",
        ):
            self.assertEqual(
                _programmatic_intent_override(phrase),
                ("handoff_status", 0.95),
                msg=phrase,
            )

    def test_genuine_delivery_questions_unaffected(self) -> None:
        # Must never shadow real order-tracking questions.
        self.assertIsNone(_programmatic_intent_override("track my order"))
        self.assertIsNone(_programmatic_intent_override("delivery kab hoga"))
        self.assertIsNone(_programmatic_intent_override("where is my order"))

    def test_status_phrase_with_order_context_is_not_hijacked(self) -> None:
        # QA-found regression: the "still not connected"-style phrases matched
        # even when the message was plainly about the ORDER, not a human. The
        # order/bill/complaint context guard must defer to the LLM there.
        for msg in (
            "this was said before also, my order still not shipped",
            "i am waiting from long time for my delivery",
            "still not connected and my parcel hasn't moved",
        ):
            self.assertIsNone(_programmatic_intent_override(msg), msg)
            self.assertNotEqual(
                _sticky_wait_escape_intent(msg), "handoff_status", msg
            )

    def test_pure_handoff_status_phrases_still_route(self) -> None:
        for msg in (
            "I am waiting from long time",
            "this was said before also still not connected",
            "kab tak call aayega",
        ):
            self.assertEqual(
                _programmatic_intent_override(msg), ("handoff_status", 0.95), msg
            )

    def test_sticky_escape_routes_to_handoff_status(self) -> None:
        self.assertEqual(
            _sticky_wait_escape_intent("still not connected"), "handoff_status"
        )

    def test_response_with_booked_callback_tells_the_slot(self) -> None:
        booked = {
            "preferred_date": "2026-09-10",
            "preferred_time_label": "Evening — 3 PM-6 PM",
        }
        with patch(
            "kisna_chatbot.processors.support_handler._find_pending_callback",
            return_value=booked,
        ):
            resp = build_handoff_status_response("919999999999", "kisna", {})
            text = resp[0]["text"]
            self.assertIn("2026-09-10", text)
            self.assertIn("already", text.lower())
            self.assertEqual(resp[0].get("_compose"), "handoff_status_booked")

    def test_response_with_pending_handoff_offers_callback(self) -> None:
        with patch(
            "kisna_chatbot.processors.support_handler._find_pending_callback",
            return_value=None,
        ), patch(
            "kisna_chatbot.config.gupshup.get_callback_flow_id", return_value=None
        ):
            profile = {"live_agent_required": True, "human_takeover": {}}
            resp = build_handoff_status_response("919999999999", "kisna", profile)
            self.assertEqual(resp[0].get("_compose"), "handoff_status_pending")

    def test_response_with_active_takeover_does_not_repeat_pending_line(self) -> None:
        # An agent already has the conversation -- do not tell the user
        # "we haven't picked this up yet" when someone has.
        with patch(
            "kisna_chatbot.processors.support_handler._find_pending_callback",
            return_value=None,
        ):
            profile = {
                "live_agent_required": True,
                "human_takeover": {"active": True},
            }
            resp = build_handoff_status_response("919999999999", "kisna", profile)
            self.assertEqual(resp[0].get("_compose"), "handoff_status_none")

    def test_response_with_nothing_pending_offers_a_choice(self) -> None:
        with patch(
            "kisna_chatbot.processors.support_handler._find_pending_callback",
            return_value=None,
        ):
            resp = build_handoff_status_response("919999999999", "kisna", {})
            self.assertEqual(resp[0].get("_compose"), "handoff_status_none")


if __name__ == "__main__":
    unittest.main()
