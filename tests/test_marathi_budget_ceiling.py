"""Marathi "kami" (under/less) was read as a range, not a ceiling.

Live, real tester traffic (2026-08-24, phone 919653404870): "25k kami"
("under 25k") parsed as min_price=20000, max_price=30000 -- a spurious +/-5k
BAND around 25k, instead of min_price=None, max_price=25000. Reproduced 4/4
in the real transcript's exact sequence and in independent harness replays.

Every other language already had this exact ceiling-word treatment (English
"under X", Hindi "से कम", Gujarati "થી ઓછું") -- Marathi's "kami" simply never
got it. The extractor has no deterministic post-processing step for this (see
_carat_weight_only / _mentions_a_ring_word in entity_extractor.py for the
shape that fix would take): the rule and a worked example were added directly
to the prompt, matched to the exact live failure. Measured after: 8/8 clean
correct in the full wizard context (0/8 before the fix, 3/5 with the rule but
no worked example -- the worked example is what made it reliable).

This is a prompt-content guardrail, not a live-extraction test: the prompt is
what an offline suite can check without an LLM call. The live measurement
above is the actual verification and is not repeated here.
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
from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor  # noqa: E402


class MarathiKamiIsACeilingTests(unittest.TestCase):
    def test_the_rule_names_kami_as_under(self):
        self.assertIn("kami", kisna_entity_extractor)
        self.assertIn("Marathi", kisna_entity_extractor)

    def test_the_worked_example_matches_the_exact_live_failure(self):
        # Anti-regression: without this exact example present, the model
        # measured 3/5 correct rather than 8/8 -- the abstract rule alone was
        # not reliable enough on its own.
        self.assertIn("25k kami", kisna_entity_extractor)
        self.assertIn("max_price=25000", kisna_entity_extractor)

    def test_the_devanagari_direction_word_is_present_too(self):
        self.assertIn("पेक्षा कमी", kisna_entity_extractor)


if __name__ == "__main__":
    unittest.main()
