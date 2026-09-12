"""F5: an English conversation seeds "en" into user_profile["language"] and
does not flip to Hindi/Hinglish on a single ambiguous word (C2: unprompted
English->Hindi mid-chat). Unconditional -- no on/off flag."""

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

from kisna_chatbot.processors.classifier import _store_language  # noqa: E402


class LangEnStickyTests(unittest.TestCase):
    def test_english_message_seeds_en(self) -> None:
        profile: dict = {}
        _store_language(profile, None, "I need a ring")
        self.assertEqual(profile.get("language"), "en")

    def test_ambiguous_single_token_does_not_flip_anchored_english(self) -> None:
        profile = {"language": "en"}
        _store_language(profile, "hi-Latn", "pass")
        self.assertEqual(profile.get("language"), "en")
        _store_language(profile, "hi-Latn", "kar")
        self.assertEqual(profile.get("language"), "en")
        _store_language(profile, "bn-Latn", "ami")
        self.assertEqual(profile.get("language"), "en")
        _store_language(profile, "gu-Latn", "che")
        self.assertEqual(profile.get("language"), "en")

    def test_real_hinglish_sentence_still_flips(self) -> None:
        profile = {"language": "en"}
        _store_language(profile, "hi-Latn", "mujhe gold ring chahiye")
        self.assertEqual(profile.get("language"), "hi-Latn")

    def test_native_script_always_flips_even_from_anchored_english(self) -> None:
        profile = {"language": "en"}
        _store_language(profile, "hi", "मुझे अंगूठी चाहिए")
        self.assertEqual(profile.get("language"), "hi")

    def test_explicit_override_still_wins(self) -> None:
        profile: dict = {}
        _store_language(profile, None, "please reply in English only")
        self.assertEqual(profile.get("language"), "en")
        _store_language(profile, "hi-Latn", "mujhe gold ring chahiye")
        self.assertEqual(profile.get("language"), "en")

    def test_two_ambiguous_tokens_together_are_enough_evidence(self) -> None:
        profile = {"language": "en"}
        _store_language(profile, "hi-Latn", "pass kar do")
        self.assertEqual(profile.get("language"), "hi-Latn")

    def test_non_english_stored_language_unaffected(self) -> None:
        # The weak-exit guard only protects an "en"-anchored conversation --
        # every other already-established language keeps its existing rules.
        profile = {"language": "hi-Latn"}
        _store_language(profile, "en", "show me rings")
        self.assertEqual(profile.get("language"), "en")


if __name__ == "__main__":
    unittest.main()
