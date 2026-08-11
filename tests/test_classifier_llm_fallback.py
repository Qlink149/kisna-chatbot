"""Classifier must not trap users when the LLM is down."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

for _k, _v in {
    "ENV_MODE": "dev",
    "MONGO_URI": "mongodb://localhost:27017",
    "OPENAI_API_KEY": "test-key",
    "GROQ_API_KEY": "test",
    "KISNA_CALLBACK_FLOW_ID": "flow_callback_test",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    _programmatic_intent_fallback,
)


class ClassifierLlmFailureFallbackTests(unittest.TestCase):
    def test_fallback_recognises_callback(self):
        self.assertEqual(
            _programmatic_intent_fallback("Callback")[0], "callback"
        )
        self.assertEqual(
            _programmatic_intent_fallback("Callback form")[0], "callback"
        )

    def test_llm_outage_still_opens_callback_form(self):
        async def _run():
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "Callback"}},
                "user_profile": {
                    "chat_history": [{"role": "user", "content": "hi"}],
                    "last_message_at": 9e18,
                    "service_selected": "",
                },
                "client_id": "kisna",
            }
            with patch(
                "kisna_chatbot.processors.classifier.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("rate limit"),
            ), patch(
                "kisna_chatbot.config.gupshup.get_callback_flow_id",
                return_value="flow_callback_test",
            ):
                result = await clf.process(data)
            self.assertEqual(result["user_profile"]["service_selected"], "callback")
            types = [r.get("type") for r in result.get("bot_response", [])]
            self.assertTrue(
                "flow" in types or any("callback" in str(r).lower() for r in result.get("bot_response", [])),
                result.get("bot_response"),
            )
            sorry = " ".join(
                r.get("text", "") for r in result.get("bot_response", [])
            ).lower()
            self.assertNotIn("didn't catch that", sorry)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
