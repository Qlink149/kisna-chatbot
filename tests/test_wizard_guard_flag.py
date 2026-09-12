"""F3 + F4: a bare greeting ("hi"/"bhai"/"yaar") mid-wizard preserves the
in-flight wizard instead of wiping it (C5 / audit U2-U3), and an unparseable
wizard step caps identical re-asks at 3 attempts -- rephrasing on the 2nd and
skipping-as-"no preference" on the 3rd (C5). Unconditional -- no on/off flag."""

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

from kisna_chatbot.processors.classifier import _reset_on_greeting  # noqa: E402
from kisna_chatbot.processors.shopping_wizard import apply_reask_guard  # noqa: E402
from kisna_chatbot.utils.session_state import (  # noqa: E402
    reset_session_on_fresh_start_preserving_wizard,
)


def _mid_wizard_profile(**extra) -> dict:
    base = {
        "service_selected": "product_search",
        "shopping_wizard_active": True,
        "shopping_wizard_step": "budget",
        "shopping_wizard_data": {"category": "ring", "gender": "female"},
        "shopping_wizard_explicit": True,
        "awaiting_store_pincode": True,  # an unrelated sticky wait -- must still clear
        "pending_clarification": "something",
    }
    base.update(extra)
    return base


class WizardGuardTests(unittest.TestCase):
    def test_greeting_mid_wizard_preserves_wizard_state(self) -> None:
        profile = _mid_wizard_profile()
        _reset_on_greeting(profile)
        self.assertTrue(profile.get("shopping_wizard_active"))
        self.assertEqual(profile.get("shopping_wizard_step"), "budget")
        self.assertEqual(profile.get("shopping_wizard_data"), {"category": "ring", "gender": "female"})
        self.assertEqual(profile.get("service_selected"), "product_search")
        # unrelated sticky waits still clear -- only the wizard survives
        self.assertNotIn("awaiting_store_pincode", profile)
        self.assertNotIn("pending_clarification", profile)

    def test_greeting_with_no_active_wizard_resets_normally(self) -> None:
        profile = {"service_selected": "product_search", "pending_clarification": "x"}
        _reset_on_greeting(profile)
        self.assertEqual(profile["service_selected"], "")
        self.assertNotIn("pending_clarification", profile)

    def test_preserving_reset_keeps_only_wizard_keys(self) -> None:
        profile = _mid_wizard_profile()
        reset_session_on_fresh_start_preserving_wizard(profile)
        self.assertTrue(profile.get("shopping_wizard_active"))
        self.assertNotIn("awaiting_store_pincode", profile)
        self.assertNotIn("pending_clarification", profile)

    def test_reask_guard_first_attempt_unchanged(self) -> None:
        profile = _mid_wizard_profile()
        original = [{"type": "text", "text": "What's your budget?"}]
        status, responses = apply_reask_guard(profile, "reask", original)
        self.assertEqual(status, "reask")
        self.assertEqual(responses, original)
        self.assertEqual(profile["wizard_reask_attempts"], 1)

    def test_reask_guard_second_attempt_rephrases(self) -> None:
        profile = _mid_wizard_profile()
        original = [{"type": "text", "text": "What's your budget?"}]
        apply_reask_guard(profile, "reask", original)
        status, responses = apply_reask_guard(profile, "reask", original)
        self.assertEqual(status, "reask")
        self.assertNotEqual(responses, original)
        self.assertEqual(len(responses), 1)
        self.assertTrue(responses[0]["text"])
        self.assertEqual(responses[0].get("_compose"), "wizard_reask_budget")
        self.assertEqual(profile["wizard_reask_attempts"], 2)

    def test_reask_guard_third_attempt_skips_field_and_advances(self) -> None:
        profile = _mid_wizard_profile()
        original = [{"type": "text", "text": "What's your budget?"}]
        apply_reask_guard(profile, "reask", original)
        apply_reask_guard(profile, "reask", original)
        status, responses = apply_reask_guard(profile, "reask", original)
        # budget was the only remaining slot in this fixture -> wizard completes
        self.assertIn(status, ("prompt", "complete"))
        self.assertEqual(profile["shopping_wizard_data"].get("budget"), "any")
        self.assertNotIn("wizard_reask_attempts", profile)
        self.assertNotIn("wizard_reask_step", profile)

    def test_reask_guard_never_asks_a_fourth_identical_prompt(self) -> None:
        profile = _mid_wizard_profile(
            shopping_wizard_data={"category": "ring", "gender": "female", "fulfillment": "any"}
        )
        original = [{"type": "text", "text": "What's your budget?"}]
        seen = []
        status = "reask"
        for _ in range(4):
            status, responses = apply_reask_guard(profile, status, original)
            if status != "reask":
                break
            seen.append(tuple(r["text"] for r in responses))
        self.assertLessEqual(len(seen), 2, "must not keep re-asking past attempt 2")

    def test_reask_guard_resets_counter_on_a_different_step(self) -> None:
        profile = _mid_wizard_profile()
        original = [{"type": "text", "text": "What's your budget?"}]
        apply_reask_guard(profile, "reask", original)
        apply_reask_guard(profile, "reask", original)
        self.assertEqual(profile["wizard_reask_attempts"], 2)
        # step changed underneath us (e.g. advance_wizard moved on) -> counter must reset
        profile["shopping_wizard_step"] = "fulfillment"
        status, responses = apply_reask_guard(
            profile, "reask", [{"type": "text", "text": "Ready to ship or made to order?"}]
        )
        self.assertEqual(profile["wizard_reask_attempts"], 1)

    def test_reask_guard_clears_counter_on_non_reask_status(self) -> None:
        profile = _mid_wizard_profile(wizard_reask_attempts=2, wizard_reask_step="budget")
        status, responses = apply_reask_guard(profile, "prompt", [{"type": "text", "text": "next step"}])
        self.assertEqual(status, "prompt")
        self.assertNotIn("wizard_reask_attempts", profile)
        self.assertNotIn("wizard_reask_step", profile)


if __name__ == "__main__":
    unittest.main()
