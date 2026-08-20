"""Tests for provider-aware AI env validation (OpenAI-only)."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("GUPSHUP_APP_ID", "test")
os.environ.setdefault("GUPSHUP_TOKEN", "test")
os.environ.setdefault("GUPSHUP_APP_NAME", "test")
os.environ.setdefault("GUPSHUP_API_KEY", "test")

from kisna_chatbot.ai.config import get_ai_settings, refresh_ai_settings
from kisna_chatbot.ai.types import ProviderName
from kisna_chatbot.utils import env_load


class ProviderSelectionTests(unittest.TestCase):
    def setUp(self):
        refresh_ai_settings()
        for key in (
            "AI_PROVIDER",
            "AI_PROVIDER_CLASSIFIER",
            "AI_PROVIDER_GENERAL",
        ):
            os.environ.pop(key, None)

    def test_defaults_to_openai_for_all_agents(self):
        refresh_ai_settings()
        settings = get_ai_settings()
        self.assertEqual(settings["default_provider"], ProviderName.OPENAI)
        self.assertEqual(settings["classifier_provider"], ProviderName.OPENAI)
        self.assertEqual(settings["general_provider"], ProviderName.OPENAI)

    def test_invalid_provider_raises_clear_error(self):
        os.environ["AI_PROVIDER"] = "groq"
        refresh_ai_settings()
        with self.assertRaises(ValueError):
            get_ai_settings()


class MissingAiEnvKeysTests(unittest.TestCase):
    def setUp(self):
        refresh_ai_settings()
        env_load._ai_startup_validated = False

    def test_openai_required_when_provider_is_openai(self):
        os.environ["AI_PROVIDER"] = "openai"
        os.environ.pop("OPENAI_API_KEY", None)
        refresh_ai_settings()

        missing = env_load.get_missing_ai_env_keys()
        self.assertTrue(any("OPENAI_API_KEY" in m for m in missing))

    def test_openai_chat_provider_requires_openai_key(self):
        os.environ["AI_PROVIDER"] = "openai"
        os.environ["AI_PROVIDER_GENERAL"] = "openai"
        os.environ.pop("OPENAI_API_KEY", None)
        refresh_ai_settings()

        missing = env_load.get_missing_ai_env_keys()
        self.assertIn("OPENAI_API_KEY", missing)


if __name__ == "__main__":
    unittest.main()
