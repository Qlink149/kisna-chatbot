"""F7: a repeat offers request within KISNA_OFFERS_COOLDOWN_SECONDS gets a
one-line pointer instead of the full block re-sent (unreported audit finding
U4: one live user got the full offers block 6x in 6 minutes). Unconditional
-- no on/off flag; KISNA_OFFERS_COOLDOWN_SECONDS is a tuning knob only."""

import os
import time
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

from kisna_chatbot.processors.offers_agent import _within_offers_cooldown  # noqa: E402


class OffersCooldownTests(unittest.TestCase):
    def test_no_prior_send_not_in_cooldown(self) -> None:
        self.assertFalse(_within_offers_cooldown({}))

    def test_recent_send_is_in_cooldown(self) -> None:
        with patch.dict(os.environ, {"KISNA_OFFERS_COOLDOWN_SECONDS": "600"}):
            profile = {"offers_last_sent_at": time.time() - 30}
            self.assertTrue(_within_offers_cooldown(profile))

    def test_old_send_is_not_in_cooldown(self) -> None:
        with patch.dict(os.environ, {"KISNA_OFFERS_COOLDOWN_SECONDS": "600"}):
            profile = {"offers_last_sent_at": time.time() - 700}
            self.assertFalse(_within_offers_cooldown(profile))

    def test_malformed_timestamp_is_safe(self) -> None:
        self.assertFalse(_within_offers_cooldown({"offers_last_sent_at": "not-a-number"}))


if __name__ == "__main__":
    unittest.main()
