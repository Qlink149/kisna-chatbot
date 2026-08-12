"""The suite must never reach a real LLM provider.

Before this guard existed, complete_chat succeeded inside pytest using
credentials from the developer's ambient environment: results depended on the
machine, and some tests asserted against live model output. These tests prove
the guard is armed, so it cannot rot silently.
"""

import asyncio
import os
import unittest

import pytest

for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_TOKEN": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "JWT_SECRET_KEY": "test",
    "SYSTEM_API_KEY": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_OFFERS_API": "http://localhost/offers",
    "KISNA_STORE_API": "http://localhost/stores",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "KB_ENABLED": "false",
}.items():
    os.environ.setdefault(_k, _v)

_GUARD_MESSAGE = "Live LLM call attempted in tests"


def _assert_blocked(coro):
    """The call must raise the guard error, not reach the network."""
    with pytest.raises(RuntimeError, match=_GUARD_MESSAGE):
        asyncio.run(coro)


class LlmIsolationTests(unittest.TestCase):
    def test_provider_credentials_are_sentinels(self):
        for var in ("OPENAI_API_KEY", "GROQ_API_KEY", "GROQ_API_KEYS"):
            self.assertEqual(
                os.environ.get(var),
                "test-sentinel-do-not-use",
                f"{var} leaked a real credential into the test run",
            )

    def test_complete_chat_is_blocked(self):
        from kisna_chatbot.ai import complete_chat
        from kisna_chatbot.ai.types import AgentName

        _assert_blocked(
            complete_chat(
                agent=AgentName.CLASSIFIER,
                instruction="say hi",
                messages=[{"role": "user", "content": "hi"}],
            )
        )

    def test_escape_gate_is_blocked_and_degrades_safely(self):
        """The gate must fail to None (fall back to regex), never crash a turn."""
        from kisna_chatbot.processors.classifier import _quick_escape_classify

        verdict = asyncio.run(
            _quick_escape_classify("hello there", "What is your budget?")
        )
        self.assertIsNone(verdict)

    def test_entity_extractor_is_blocked_and_degrades_safely(self):
        """extract_entities_with_llm swallows failures and returns {}."""
        from kisna_chatbot.processors.entity_extractor import (
            extract_entities_with_llm,
        )

        self.assertEqual(
            asyncio.run(extract_entities_with_llm(user_query="gold rings")), {}
        )

    def test_reply_composer_is_blocked(self):
        from kisna_chatbot.utils.reply_composer import compose

        # compose() catches its own failures and returns the source text.
        out = asyncio.run(
            compose("wizard_budget", "What's your budget?", language="hi")
        )
        self.assertEqual(out, "What's your budget?")

    def test_openai_responses_client_is_blocked(self):
        from kisna_chatbot.utils.get_openai_client import get_openai_client

        with self.assertRaises(RuntimeError) as ctx:
            get_openai_client()
        self.assertIn(_GUARD_MESSAGE, str(ctx.exception))


@pytest.mark.live
class LiveMarkerTests(unittest.TestCase):
    """Deselected by default (`addopts = -m "not live"`). Proves the opt-out."""

    def test_marker_opts_out_of_the_guard(self):
        self.assertNotEqual(
            os.environ.get("OPENAI_API_KEY"), "test-sentinel-do-not-use"
        )


if __name__ == "__main__":
    unittest.main()
