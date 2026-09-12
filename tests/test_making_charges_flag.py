"""F6: a making-charges question hard-routes to the offers intent instead of
the LLM, which otherwise can't invent a percentage (C7: it fabricated "making
charge is often 10%" with a worked ₹ example). Unconditional -- no on/off flag."""

import os
import unittest

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


class MakingChargesRoutingTests(unittest.TestCase):
    def test_hard_override_routes_to_offers(self) -> None:
        self.assertEqual(
            _programmatic_intent_override("making charges kitna hai"),
            ("offers", 0.95),
        )
        self.assertEqual(
            _programmatic_intent_override("how are making charges calculated?"),
            ("offers", 0.95),
        )
        self.assertEqual(
            _programmatic_intent_override("what is the making charge on this ring"),
            ("offers", 0.95),
        )

    def test_sticky_escape_routes_to_offers(self) -> None:
        self.assertEqual(
            _sticky_wait_escape_intent("making charges kitna hai"), "offers"
        )

    def test_unrelated_queries_unaffected(self) -> None:
        self.assertIsNone(_programmatic_intent_override("show me gold rings"))
        self.assertIsNone(_programmatic_intent_override("what is the return policy"))

    def test_competitor_comparison_still_takes_precedence(self) -> None:
        # _is_competitor_comparison is checked first in the function -- must
        # not be shadowed by the making-charges branch.
        result = _programmatic_intent_override("Kisna vs Tanishq making charges comparison")
        self.assertEqual(result, ("general", 0.95))

    def test_billing_complaint_is_not_hijacked_to_offers(self) -> None:
        # QA-found regression: live LLM correctly classified these as complaint;
        # the raw override forced them to offers (re-created audit defect C3).
        # The hard override (the actual routing authority) must defer to the LLM
        # when the message carries order / bill / complaint context.
        for msg in (
            "The making charges discount is not showing in my bill",
            "my bill me making charges galat lag gaya hai, complaint karni hai",
            "making charges were overcharged on my invoice",
            "making charges refund not reflecting",
        ):
            self.assertIsNone(_programmatic_intent_override(msg), msg)

    def test_genuine_price_questions_still_route_to_offers(self) -> None:
        for msg in (
            "For 2 lac what will be making charges?",
            "25000. also what happens to making charges if i exchange",
            "Too much making charges i cannot",
        ):
            self.assertEqual(_programmatic_intent_override(msg), ("offers", 0.95), msg)


if __name__ == "__main__":
    unittest.main()
