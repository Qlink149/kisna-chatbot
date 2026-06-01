"""Tests for multi-provider AI layer."""

import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key")
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

from kisna_chatbot.ai.config import (
    get_ai_settings,
    refresh_ai_settings,
    resolve_provider,
)
from kisna_chatbot.ai.fallback import is_transient_error
from kisna_chatbot.ai.types import AgentName, ProviderName


class AIConfigTests(unittest.TestCase):
    def setUp(self):
        refresh_ai_settings()

    def test_default_provider_openai(self):
        os.environ["AI_PROVIDER"] = "openai"
        os.environ.pop("AI_PROVIDER_CLASSIFIER", None)
        refresh_ai_settings()
        self.assertEqual(resolve_provider(AgentName.CLASSIFIER), ProviderName.OPENAI)

    def test_classifier_groq_override(self):
        os.environ["AI_PROVIDER"] = "openai"
        os.environ["AI_PROVIDER_CLASSIFIER"] = "groq"
        refresh_ai_settings()
        self.assertEqual(resolve_provider(AgentName.CLASSIFIER), ProviderName.GROQ)

    def test_general_defaults_openai(self):
        os.environ["AI_PROVIDER_GENERAL"] = "openai"
        refresh_ai_settings()
        self.assertEqual(resolve_provider(AgentName.GENERAL), ProviderName.OPENAI)


class FallbackTests(unittest.TestCase):
    def test_transient_errors(self):
        from openai import RateLimitError

        exc = RateLimitError("rate limit", response=MagicMock(), body=None)
        self.assertTrue(is_transient_error(exc))

        self.assertFalse(is_transient_error(ValueError("bad")))


class CompleteChatTests(unittest.TestCase):
    def test_complete_chat_returns_text(self):
        async def _run():
            from kisna_chatbot.ai.factory import complete_chat
            from kisna_chatbot.ai.types import CompletionResult, ProviderName

            mock_result = CompletionResult(
                text='{"category": "general"}',
                provider=ProviderName.OPENAI,
                model="gpt-4o-mini",
                prompt_tokens=10,
                completion_tokens=5,
                latency_ms=100,
            )

            mock_provider = MagicMock()
            mock_provider.complete = AsyncMock(return_value=mock_result)

            with patch(
                "kisna_chatbot.ai.factory.get_chat_provider",
                return_value=mock_provider,
            ), patch("kisna_chatbot.ai.factory.record_usage"):
                text = await complete_chat(
                    agent=AgentName.CLASSIFIER,
                    instruction="test",
                    messages=[{"role": "user", "content": "hi"}],
                )
            self.assertIn("general", text)
            mock_provider.complete.assert_awaited_once()

        import asyncio

        asyncio.run(_run())


class PublicConfigTests(unittest.TestCase):
    def test_get_public_config_structure(self):
        from kisna_chatbot.ai.config import get_public_config

        refresh_ai_settings()
        cfg = get_public_config()
        self.assertIn("agents", cfg)
        self.assertIn("classifier", cfg["agents"])
        self.assertIn("general", cfg["agents"])


if __name__ == "__main__":
    unittest.main()
