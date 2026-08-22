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

# Raised from 6000 for product_question: the classifier now reports WHETHER
# a message asks something about a shown product, separately from WHICH
# product it means. Without that second fact, product_reference was the
# only signal and "iska price kya hai?" re-printed the card the customer
# was already looking at.
# Raised again (6400 -> 6700) for secondary_intent and the head-office rule.
# secondary_intent ends a documented decision to drop half of what the
# customer said: rule 26 used to instruct the model to answer the primary
# request and trust that "the user will ask the rest next". Measured live,
# the second request was dropped with no acknowledgement in 6 of 6 languages.
# Raised (6700 -> 6800) for the unsubscribe intent and the Assamese/Bengali
# disambiguation. Opt-out was an exact `== "stop"` match, so every other
# phrasing and every non-English equivalent was ignored — a compliance
# problem. Assamese shares Bengali's script, so without a marker rule the
# model labels it "bn" and Assamese customers are answered in Bengali.
MAX_CLASSIFIER_INTENT_TOKENS = 6800
# Raised from 6500 so the gender rule could state a PRINCIPLE ("kinship words
# are lexically gendered — read the word") instead of a closed list of terms.
# The list was the bug: "chachi" was not on it, so the model followed the
# "AMBIGUOUS -> null, do NOT guess" instruction and returned no gender for a
# word that is unambiguously feminine. A list can never cover nine languages.
# The extractor runs CONTEXT-FREE -- no chat history, no shown products -- so
# it needs far less headroom than the classifier; test_entity_extractor_fits_
# under_request_ceiling below is what actually protects the request size.
# Raised again (7000 -> 7300) for the negation rule and the
# more-premium/pagination disambiguation. Both are correctness fixes for
# behaviour the model was getting wrong, and this number is a style guard,
# not the real limit -- at 7300 est the extractor is ~8470 real tokens,
# leaving ~3500 under the 12000 ceiling, which the test below asserts.
# Raised again (7300 -> 7700) for excluded_material, pearl, the Gurmukhi
# category words and store city/state. Each is a measured correctness fix:
#   excluded_material -- "मुझे सोने की नहीं" returned material_type="gold"
#     in 6 of 6 Indic languages, because the model had nowhere to record a
#     refusal and fell back on the mapping table.
#   pearl -- absent from the enum, so the model said gemstone and the
#     funnel accepted an order for something Clara does not stock.
#   Gurmukhi -- ਮੁੰਦਰੀ (ring) came back as bangle/earring, unstably.
#   city/state -- the store locator read a 121-entry Latin city list and
#     nothing else, so "मुंबई में आपका स्टोर है क्या?" got a pincode prompt.
# Correctness wins over this number; the request-ceiling test below is the
# limit that actually matters, and it still leaves ~3200 tokens spare.
# Raised (7700 -> 7800) for two measured misreadings: Devanagari प्रीमियम
# read as pagination rather than a price direction, and Gujarati વીંટી read
# as an earring in long sentences (correct in short ones).
# HEADROOM IS NOW THIN: ~3045 tokens under the request ceiling against a
# 3000 floor. The next addition here will fail test_entity_extractor_fits_
# under_request_ceiling, and that is the gate working — trim, do not raise it.
MAX_ENTITY_EXTRACTOR_TOKENS = 7800

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
