"""Prompt size budgets — the test that would have caught the original drift.

The classifier prompt grew to 12,819 estimated tokens through a series of
well-meaning additions, each small on its own. Nothing measured the total, so
nobody noticed until it exceeded a safe request-size ceiling and requests
started returning HTTP 413.

Estimate is len(prompt) / 3.6. That UNDERSTATES real tokens by roughly 15% on
this content (Indic script and JSON tokenise badly), so the budgets below are
set with that in mind: 6,000 estimated is ~6,900 real, leaving ~5,000 tokens of
context headroom under the configured ceiling.
"""

import unittest

from kisna_chatbot.prompts.classifier_kisna import (
    kisna_classifier_intent,
    kisna_entity_extractor,
)

MAX_CLASSIFIER_INTENT_TOKENS = 6000
# Raised from 6500 so the gender rule could state a PRINCIPLE ("kinship words
# are lexically gendered — read the word") instead of a closed list of terms.
# The list was the bug: "chachi" was not on it, so the model followed the
# "AMBIGUOUS -> null, do NOT guess" instruction and returned no gender for a
# word that is unambiguously feminine. A list can never cover nine languages.
# The extractor runs CONTEXT-FREE -- no chat history, no shown products -- so
# it needs far less headroom than the classifier; test_entity_extractor_fits_
# under_request_ceiling below is what actually protects the request size.
MAX_ENTITY_EXTRACTOR_TOKENS = 7000

# Conservative request-size ceiling. The prompt plus context and user message
# must fit inside this to avoid request-too-large errors.
REQUEST_SIZE_CEILING = 12000
EST_TO_REAL_TOKEN_RATIO = 1.16


def estimate_tokens(prompt: str) -> float:
    return len(prompt) / 3.6


class PromptBudgetTests(unittest.TestCase):
    def test_classifier_intent_within_budget(self):
        estimate = estimate_tokens(kisna_classifier_intent)
        self.assertLess(
            estimate,
            MAX_CLASSIFIER_INTENT_TOKENS,
            f"classifier prompt is {estimate:.0f} est tokens, budget is "
            f"{MAX_CLASSIFIER_INTENT_TOKENS}. Entity-extraction content belongs "
            f"in kisna_entity_extractor, not here.",
        )

    def test_entity_extractor_within_budget(self):
        estimate = estimate_tokens(kisna_entity_extractor)
        self.assertLess(
            estimate,
            MAX_ENTITY_EXTRACTOR_TOKENS,
            f"entity extractor is {estimate:.0f} est tokens, budget is "
            f"{MAX_ENTITY_EXTRACTOR_TOKENS}.",
        )

    def test_classifier_fits_under_request_ceiling_with_context(self):
        """Classifier prompt must leave enough room for runtime context."""
        real = estimate_tokens(kisna_classifier_intent) * EST_TO_REAL_TOKEN_RATIO
        headroom = REQUEST_SIZE_CEILING - real
        self.assertGreater(
            headroom,
            3000,
            f"classifier is ~{real:.0f} real tokens; only {headroom:.0f} tokens "
            f"left under {REQUEST_SIZE_CEILING} ceiling for chat history, "
            f"shown products and the user message.",
        )

    def test_entity_extractor_fits_under_request_ceiling(self):
        """The budget above is a style rule; THIS is the failure that matters.

        Added when MAX_ENTITY_EXTRACTOR_TOKENS was raised, so relaxing that
        number can never silently remove the protection it was standing in for.
        """
        real = estimate_tokens(kisna_entity_extractor) * EST_TO_REAL_TOKEN_RATIO
        headroom = REQUEST_SIZE_CEILING - real
        self.assertGreater(
            headroom,
            3000,
            f"entity extractor is ~{real:.0f} real tokens; only "
            f"{headroom:.0f} tokens left under {REQUEST_SIZE_CEILING}.",
        )

    def test_budget_would_have_caught_the_original_drift(self):
        """Proof the guardrail is calibrated to catch the real regression.

        Measured from the combined prompt this budget was written for (the
        `kisna_classifier` constant as of commit 813e028, before the Stage 1
        split). The prompt itself is deleted; its size is kept here so the
        calibration stays checkable.
        """
        HISTORICAL_CLASSIFIER_CHARS = 46_149  # -> 12,819 est tokens

        historical = HISTORICAL_CLASSIFIER_CHARS / 3.6
        self.assertGreater(historical, MAX_CLASSIFIER_INTENT_TOKENS)
        # And it blew the request-size ceiling, which is the failure that mattered.
        self.assertGreater(historical * EST_TO_REAL_TOKEN_RATIO, REQUEST_SIZE_CEILING)


if __name__ == "__main__":
    unittest.main()
