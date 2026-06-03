"""Tests for provider-aware AI env validation and Groq key pool."""

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
from kisna_chatbot.ai.groq_keys import GroqKeyPool, parse_groq_api_keys
from kisna_chatbot.utils import env_load


class ParseGroqKeysTests(unittest.TestCase):
    def test_comma_separated_keys(self):
        keys = parse_groq_api_keys(
            groq_api_keys="key-a, key-b ,key-c",
            groq_api_key="ignored",
        )
        self.assertEqual(keys, ["key-a", "key-b", "key-c"])

    def test_single_key_fallback(self):
        keys = parse_groq_api_keys(groq_api_keys="", groq_api_key="solo-key")
        self.assertEqual(keys, ["solo-key"])


class GroqKeyPoolTests(unittest.TestCase):
    def test_rotate_cycles_keys(self):
        pool = GroqKeyPool(["a", "b", "c"])
        self.assertEqual(pool.current_key(), "a")
        pool.rotate()
        self.assertEqual(pool.current_key(), "b")
        pool.rotate()
        self.assertEqual(pool.current_key(), "c")
        pool.rotate()
        self.assertEqual(pool.current_key(), "a")

    def test_single_key_rotate_no_op(self):
        pool = GroqKeyPool(["only"])
        idx, total = pool.rotate()
        self.assertEqual(idx, 0)
        self.assertEqual(total, 1)


class MissingAiEnvKeysTests(unittest.TestCase):
    def setUp(self):
        refresh_ai_settings()
        env_load._ai_startup_validated = False

    def test_groq_only_chat_no_openai_required(self):
        os.environ["AI_PROVIDER"] = "groq"
        os.environ["AI_PROVIDER_CLASSIFIER"] = "groq"
        os.environ["AI_PROVIDER_GENERAL"] = "groq"
        os.environ["AI_FALLBACK_ENABLED"] = "false"
        os.environ["GROQ_API_KEY"] = "gsk-test"
        os.environ.pop("GROQ_API_KEYS", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("CHROMA_API_KEY", None)
        os.environ.pop("KB_ENABLED", None)
        refresh_ai_settings()

        missing = env_load.get_missing_ai_env_keys()
        self.assertNotIn("OPENAI_API_KEY", missing)
        openai_kb = [m for m in missing if "OPENAI_API_KEY" in m]
        self.assertEqual(openai_kb, [])

    def test_kb_enabled_requires_openai(self):
        os.environ["AI_PROVIDER"] = "groq"
        os.environ["AI_FALLBACK_ENABLED"] = "false"
        os.environ["GROQ_API_KEY"] = "gsk-test"
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["CHROMA_API_KEY"] = "chroma-test"
        refresh_ai_settings()

        missing = env_load.get_missing_ai_env_keys()
        self.assertTrue(any("OPENAI_API_KEY" in m for m in missing))

    def test_openai_chat_provider_requires_openai_key(self):
        os.environ["AI_PROVIDER"] = "openai"
        os.environ["AI_PROVIDER_GENERAL"] = "openai"
        os.environ["AI_FALLBACK_ENABLED"] = "false"
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["GROQ_API_KEY"] = "gsk-test"
        os.environ.pop("CHROMA_API_KEY", None)
        os.environ.pop("KB_ENABLED", None)
        refresh_ai_settings()

        missing = env_load.get_missing_ai_env_keys()
        self.assertIn("OPENAI_API_KEY", missing)

    def test_settings_exposes_groq_api_keys_list(self):
        os.environ["GROQ_API_KEYS"] = "k1,k2,k3"
        os.environ.pop("GROQ_API_KEY", None)
        refresh_ai_settings()
        settings = get_ai_settings()
        self.assertEqual(settings["groq_api_keys"], ["k1", "k2", "k3"])
        self.assertEqual(settings["groq_api_key"], "k1")


class GroqRateLimitRotationTests(unittest.TestCase):
    def test_rotate_on_rate_limit_switches_client(self):
        async def _run():
            from unittest.mock import AsyncMock, MagicMock, patch

            from openai import RateLimitError

            from kisna_chatbot.ai.groq_chat import GroqChatProvider
            from kisna_chatbot.ai.types import AgentName, CompletionRequest

            provider = GroqChatProvider(
                model="llama-test",
                keys=["key-one", "key-two"],
                base_url="https://api.groq.com/openai/v1",
                rotate_on_rate_limit=True,
            )

            mock_response = MagicMock()
            mock_response.choices = [
                MagicMock(message=MagicMock(content="hello"))
            ]
            mock_response.usage = None

            call_count = {"n": 0}

            async def side_effect(**kwargs):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    raise RateLimitError(
                        "rate limit",
                        response=MagicMock(status_code=429),
                        body=None,
                    )
                return mock_response

            for client in provider._clients.values():
                client.chat.completions.create = AsyncMock(side_effect=side_effect)

            request = CompletionRequest(
                agent=AgentName.CLASSIFIER,
                agent_display_name="classifier",
                instruction="test",
                messages=[{"role": "user", "content": "hi"}],
            )
            result = await provider.complete(request)
            self.assertEqual(result.text, "hello")
            self.assertEqual(call_count["n"], 2)
            self.assertEqual(provider._key_pool.current_index, 1)

        import asyncio

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
