"""A self-contained detour must not silently erase the shopping wizard.

Live, from a real tester session (phone 919116914178, 2026-08-24):
"show me gold rings and also tell me your store in Mumbai" opened the wizard
(category=ring, material_type=gold) and appended the standard store-lookup
acknowledgement. Answering it with "400086" correctly returned the Mumbai
branches -- but silently wiped shopping_wizard_active/shopping_wizard_data.
The next reply, "Female" (tapped from the wizard's own gender buttons), had
no active flow left to land in: it restarted the wizard from empty, losing
category and material, and in one run was misrouted to human_handoff outright
because a bare "Female" carries no signal on its own.

Root cause: `_release_sticky_wait` tears the wizard down the moment a message
doesn't answer the wizard's OWN question -- correct, because at that point
nothing has classified the message yet. But offers/gold_rate/store_info/
general (`_SECONDARY_INTENTS`) are exactly the intents this codebase already
treats as answerable without abandoning the primary flow (secondary_intent.py
draws the identical line for a request folded into the SAME message); the
standalone-follow-up case just never got the same treatment.

The reproduction is not store_info-specific -- a standalone "what's today's
gold rate?", "what are today's offers?" or "what is your return policy?"
asked with NO priming at all, mid-wizard, wiped it exactly the same way.

Fix: `_release_sticky_wait` snapshots the wizard (plus service_selected, which
pipeline dispatch needs to route a button tap back to product_search) before
clearing it. `_restore_wizard_after_safe_detour`, called from main.py AFTER
the detour's own reply already exists, puts it back only when the resolved
intent turns out to be one of the four safe ones. Restoring any earlier would
run into GeneralAgent's own "wizard active -> hand back to product search"
guard and swallow the FAQ answer instead of giving it.
"""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401,E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    _WIZARD_STICKY_KEYS,
    _restore_wizard_after_safe_detour,
)


def _wizard_snapshot() -> dict:
    return {
        "shopping_wizard_active": True,
        "shopping_wizard_step": "gender",
        "shopping_wizard_data": {"category": "ring", "material_type": "gold"},
        "shopping_wizard_explicit": {},
        "service_selected": "product_search",
    }


class RestoreAfterSafeDetourTests(unittest.TestCase):
    def test_a_safe_detour_gives_the_wizard_back(self):
        for intent in ("offers", "gold_rate", "store_info", "general"):
            data = {
                "classified_category": intent,
                "_wizard_detour_snapshot": _wizard_snapshot(),
                "user_profile": {},
            }
            _restore_wizard_after_safe_detour(data)
            profile = data["user_profile"]
            self.assertTrue(profile.get("shopping_wizard_active"), intent)
            self.assertEqual(
                profile.get("shopping_wizard_data"),
                {"category": "ring", "material_type": "gold"},
                intent,
            )
            self.assertEqual(profile.get("service_selected"), "product_search", intent)
            self.assertNotIn("_wizard_detour_snapshot", data, intent)

    def test_a_genuine_abandonment_keeps_the_wizard_cleared(self):
        for intent in (
            "human_handoff",
            "complaint",
            "order_status",
            "track_order",
            "returns_refund",
            "callback",
            "video_call",
            "product_search",
            "repair",
            "menu_help",
            "greeting",
        ):
            data = {
                "classified_category": intent,
                "_wizard_detour_snapshot": _wizard_snapshot(),
                "user_profile": {},
            }
            _restore_wizard_after_safe_detour(data)
            self.assertEqual(data["user_profile"], {}, intent)

    def test_no_snapshot_is_a_clean_no_op(self):
        data = {"classified_category": "gold_rate", "user_profile": {}}
        _restore_wizard_after_safe_detour(data)  # must not raise
        self.assertEqual(data["user_profile"], {})

    def test_a_missing_user_profile_does_not_raise(self):
        data = {
            "classified_category": "gold_rate",
            "_wizard_detour_snapshot": _wizard_snapshot(),
        }
        _restore_wizard_after_safe_detour(data)  # must not raise

    def test_restore_only_ever_touches_the_wizard_and_service_keys(self):
        # Guards the snapshot shape itself, so a future edit that adds an
        # unrelated key to the snapshot is caught here rather than silently
        # leaking some other piece of profile state across a detour.
        snapshot_keys = set(_wizard_snapshot())
        self.assertEqual(
            snapshot_keys, set(_WIZARD_STICKY_KEYS) | {"service_selected"}
        )


if __name__ == "__main__":
    unittest.main()
