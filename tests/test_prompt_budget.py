"""Prompt size budgets — the test that would have caught the original drift.

The classifier prompt grew to 12,819 estimated tokens through a series of
well-meaning additions, each small on its own. Nothing measured the total, so
nobody noticed until it exceeded Groq's 12,000 TPM ceiling and every call on
that provider returned HTTP 413.

Estimate is len(prompt) / 3.6. That UNDERSTATES real tokens by roughly 15% on
this content (Indic script and JSON tokenise badly), so the budgets below are
set with that in mind: 6,000 estimated is ~6,900 real, leaving ~5,000 tokens of
context headroom under Groq's ceiling.
"""

import unittest

from kisna_chatbot.prompts.classifier_kisna import (
    kisna_classifier_intent,
    kisna_entity_extractor,
)

MAX_CLASSIFIER_INTENT_TOKENS = 6000
MAX_ENTITY_EXTRACTOR_TOKENS = 6500

# Groq on-demand TPM ceiling for llama-3.3-70b-versatile. The prompt plus its
# context and the user message must fit inside this or the call 413s.
GROQ_TPM_CEILING = 12000
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

    def test_classifier_fits_under_the_groq_ceiling_with_context(self):
        """The fallback provider must remain usable for the classifier.

        At 12,819 est tokens this was false: Groq returned 413 on every
        classifier call, so arming the fallback would have protected every
        agent except the one users notice.
        """
        real = estimate_tokens(kisna_classifier_intent) * EST_TO_REAL_TOKEN_RATIO
        headroom = GROQ_TPM_CEILING - real
        self.assertGreater(
            headroom,
            3000,
            f"classifier is ~{real:.0f} real tokens; only {headroom:.0f} tokens "
            f"left under Groq's {GROQ_TPM_CEILING} ceiling for chat history, "
            f"shown products and the user message.",
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
        # And it blew the provider ceiling, which is the failure that mattered.
        self.assertGreater(historical * EST_TO_REAL_TOKEN_RATIO, GROQ_TPM_CEILING)


if __name__ == "__main__":
    unittest.main()
