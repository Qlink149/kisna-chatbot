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


class ProviderDefaultTests(unittest.TestCase):
    """Every agent defaults to OpenAI so dev matches production.

    AI_PROVIDER used to default to "groq" and the classifier inherited it, so
    an unset environment ran the FALLBACK provider as primary — which is how a
    local Groq 413 was mistaken for a production outage.
    """

    def setUp(self):
        self._saved = {
            key: os.environ.pop(key, None)
            for key in ("AI_PROVIDER", "AI_PROVIDER_CLASSIFIER", "AI_PROVIDER_GENERAL")
        }
        refresh_ai_settings()

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        refresh_ai_settings()

    def test_classifier_defaults_to_openai_when_unset(self):
        self.assertEqual(resolve_provider(AgentName.CLASSIFIER), ProviderName.OPENAI)

    def test_general_defaults_to_openai_when_unset(self):
        self.assertEqual(resolve_provider(AgentName.GENERAL), ProviderName.OPENAI)

    def test_default_provider_is_openai_when_unset(self):
        self.assertEqual(get_ai_settings()["default_provider"], ProviderName.OPENAI)

    def test_groq_remains_selectable(self):
        os.environ["AI_PROVIDER_CLASSIFIER"] = "groq"
        refresh_ai_settings()
        self.assertEqual(resolve_provider(AgentName.CLASSIFIER), ProviderName.GROQ)


class FallbackTests(unittest.TestCase):
    def test_transient_errors(self):
        from openai import RateLimitError

        exc = RateLimitError("rate limit", response=MagicMock(), body=None)
        self.assertTrue(is_transient_error(exc))

        self.assertFalse(is_transient_error(ValueError("bad")))

    def test_non_transient_errors_do_not_trigger_fallback(self):
        """413 / 5xx / auth are NOT covered — documented, not accidental."""
        from openai import (
            APIStatusError,
            AuthenticationError,
            BadRequestError,
            InternalServerError,
        )

        for exc_cls in (
            InternalServerError,
            APIStatusError,
            BadRequestError,
            AuthenticationError,
        ):
            with self.subTest(exc=exc_cls.__name__):
                self.assertFalse(
                    issubclass(
                        exc_cls,
                        (
                            __import__("openai").RateLimitError,
                            __import__("openai").APITimeoutError,
                            __import__("openai").APIConnectionError,
                        ),
                    )
                )

    def _result(self, provider: ProviderName):
        from kisna_chatbot.ai.types import CompletionResult

        return CompletionResult(
            text="ok",
            provider=provider,
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )

    def _providers(self, primary_exc=None):
        from kisna_chatbot.ai.fallback import FallbackChatProvider

        primary = MagicMock()
        primary.provider_name = ProviderName.OPENAI
        primary.model = "gpt-4o-mini"
        primary.complete = AsyncMock(
            side_effect=primary_exc
            if primary_exc
            else None,
            return_value=None if primary_exc else self._result(ProviderName.OPENAI),
        )
        secondary = MagicMock()
        secondary.provider_name = ProviderName.GROQ
        secondary.model = "llama-3.3-70b-versatile"
        secondary.complete = AsyncMock(return_value=self._result(ProviderName.GROQ))
        return FallbackChatProvider(primary, secondary), primary, secondary

    def test_transient_failure_switches_to_fallback_provider(self):
        import asyncio

        from openai import RateLimitError

        exc = RateLimitError("429", response=MagicMock(), body=None)
        provider, primary, secondary = self._providers(primary_exc=exc)
        result = asyncio.run(provider.complete(MagicMock()))

        primary.complete.assert_awaited_once()
        secondary.complete.assert_awaited_once()
        self.assertEqual(result.provider, ProviderName.GROQ)
        self.assertTrue(result.fallback_used)

    def test_non_transient_failure_raises_without_fallback(self):
        import asyncio

        provider, primary, secondary = self._providers(
            primary_exc=ValueError("prompt too large")
        )
        with self.assertRaises(ValueError):
            asyncio.run(provider.complete(MagicMock()))
        primary.complete.assert_awaited_once()
        secondary.complete.assert_not_awaited()

    def test_healthy_primary_never_calls_fallback(self):
        import asyncio

        provider, primary, secondary = self._providers()
        result = asyncio.run(provider.complete(MagicMock()))
        self.assertEqual(result.provider, ProviderName.OPENAI)
        secondary.complete.assert_not_awaited()

    def test_fallback_is_unreachable_while_the_flag_is_off(self):
        """AI_FALLBACK_ENABLED=false means no wrapper is built at all."""
        from kisna_chatbot.ai.factory import get_chat_provider
        from kisna_chatbot.ai.fallback import FallbackChatProvider

        saved = os.environ.get("AI_FALLBACK_ENABLED")
        os.environ["AI_FALLBACK_ENABLED"] = "false"
        refresh_ai_settings()
        try:
            provider = get_chat_provider(AgentName.CLASSIFIER)
            self.assertNotIsInstance(provider, FallbackChatProvider)
        finally:
            if saved is None:
                os.environ.pop("AI_FALLBACK_ENABLED", None)
            else:
                os.environ["AI_FALLBACK_ENABLED"] = saved
            refresh_ai_settings()


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
