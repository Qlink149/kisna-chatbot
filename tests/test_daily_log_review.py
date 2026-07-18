"""Unit tests for the daily classifier log review analysis."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401  (breaks logger/env init cycle)
from scripts.daily_log_review import (
    _analyze,
    _reply_language_script,
    _script_of,
)


class ScriptDetectionTests(unittest.TestCase):
    def test_script_buckets(self):
        self.assertEqual(_script_of("Return krna hai"), "latin")
        self.assertEqual(_script_of("रिटर्न करना है"), "indic")
        self.assertEqual(_script_of("તમારી પાસે"), "indic")
        self.assertEqual(_script_of("12345"), "other")
        self.assertEqual(_script_of(""), "other")

    def test_reply_language_script(self):
        self.assertEqual(_reply_language_script("en"), "latin")
        self.assertEqual(_reply_language_script("hi-Latn"), "latin")
        self.assertEqual(_reply_language_script("gu-Latn"), "latin")
        self.assertEqual(_reply_language_script("hi"), "indic")
        self.assertEqual(_reply_language_script("gu"), "indic")
        self.assertIsNone(_reply_language_script(None))


class AnalyzeTests(unittest.TestCase):
    def test_intent_and_language_distribution(self):
        docs = [
            {"intent": "product_search", "confidence": 0.9, "language": "en",
             "outcome": "info_sent", "user_message": "show rings",
             "reply_preview": "Here are rings"},
            {"intent": "product_search", "confidence": 0.8, "language": "hi-Latn",
             "outcome": "info_sent", "user_message": "rings dikhao",
             "reply_preview": "yeh rahe rings"},
            {"intent": "gold_rate", "confidence": 0.95, "language": "en",
             "outcome": "info_sent", "user_message": "gold rate",
             "reply_preview": "Today's rate"},
        ]
        report = _analyze(docs)
        self.assertEqual(report["total"], 3)
        intents = dict(report["intents"])
        self.assertEqual(intents["product_search"], 2)
        self.assertEqual(intents["gold_rate"], 1)

    def test_low_confidence_flagging(self):
        docs = [
            {"intent": "general", "confidence": 0.3, "language": "en",
             "outcome": "info_sent", "user_message": "asdf", "reply_preview": "?"},
            {"intent": "product_search", "confidence": 0.9, "language": "en",
             "outcome": "info_sent", "user_message": "rings", "reply_preview": "x"},
        ]
        report = _analyze(docs)
        self.assertEqual(len(report["low_confidence"]), 1)
        self.assertEqual(report["low_confidence"][0]["user_message"], "asdf")

    def test_language_script_mismatch_detection(self):
        docs = [
            # User typed Latin (Hinglish), reply came out in Devanagari — mismatch.
            {"intent": "returns_refund", "confidence": 0.9, "language": "hi",
             "outcome": "info_sent", "user_message": "Return krna hai",
             "reply_preview": "बिल्कुल — मैं रिटर्न में मदद करूंगा।"},
            # Correct: Hinglish user, Hinglish reply.
            {"intent": "returns_refund", "confidence": 0.9, "language": "hi-Latn",
             "outcome": "info_sent", "user_message": "Return krna hai",
             "reply_preview": "Bilkul, main return me madad karunga"},
        ]
        report = _analyze(docs)
        self.assertEqual(len(report["language_mismatches"]), 1)
        self.assertEqual(report["language_mismatches"][0]["user_script"], "latin")
        self.assertEqual(report["language_mismatches"][0]["reply_script"], "indic")

    def test_missing_intent_counted(self):
        docs = [
            {"intent": None, "confidence": None, "language": "en",
             "outcome": "info_sent", "user_message": "hi", "reply_preview": "hello"},
        ]
        report = _analyze(docs)
        self.assertEqual(report["missing_intent"], 1)

    def test_empty(self):
        report = _analyze([])
        self.assertEqual(report["total"], 0)
        self.assertEqual(report["low_confidence"], [])


if __name__ == "__main__":
    unittest.main()