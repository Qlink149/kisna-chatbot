"""No intent may be over-reinforced — prevents the "fix it in five places" pattern.

store_info regressed by accumulation: each client-reported miss added another
store example, until 17 of them (plus 20 "entities: all null" annotations) made
"store_info with empty entities" the lowest-effort answer for any message the
model found hard to parse. Native-script and romanized-regional messages were
hit hardest, because those are the hardest to parse.

The check is deliberately NOT "no intent exceeds 2x the median". product_search
legitimately dominates — it is what the bot is for — and general carries FAQ
variety. Flagging them would make the test noise that gets disabled. What went
wrong was a SECONDARY intent inflating, so that is what is measured.
"""

import re
import statistics
import unittest

from kisna_chatbot.prompts.classifier_kisna import kisna_classifier_intent

ALL_INTENTS = (
    "greeting", "menu_help", "product_search", "product_info", "compare",
    "repair", "offers", "store_info", "order_tracking", "returns_refund",
    "complaint", "human_handoff", "callback", "video_call", "gold_rate",
    "general",
)

# Structurally dominant by design: the catalogue is the product, and general
# absorbs every brand/policy question. Excluded from the balance comparison,
# but still covered by the token budget in test_prompt_budget.py.
DOMINANT_INTENTS = frozenset({"product_search", "general", "product_info"})

# Calibrated against the post-Stage-4 prompt: secondary max is 6, median 5
# (1.2x). A 2.0x multiplier leaves real headroom for future additions while
# still catching store_info's 17 examples (3.4x) — see the regression proof.
MAX_SECONDARY_MULTIPLE = 2.0


def count_examples_by_intent(prompt: str) -> dict[str, int]:
    """Count worked examples per intent, in either prompt format.

    The current prompt writes one-liners ("hi" -> greeting .95); the previous
    one wrote JSON payloads ({"intent": "greeting", ...}). Both are counted so
    the same threshold can be applied to either and the regression proof below
    is meaningful rather than an artefact of formatting.
    """
    counts = {intent: 0 for intent in ALL_INTENTS}
    for line in prompt.splitlines():
        match = re.search(
            r'->\s*([a-z_]+)[\s.]|"intent":\s*"([a-z_]+)"', line
        )
        if not match:
            continue
        intent = match.group(1) or match.group(2)
        if intent in counts:
            counts[intent] += 1
    return counts


def secondary_balance(prompt: str) -> tuple[float, str, int]:
    """(median, worst intent, its count) among non-dominant intents."""
    counts = count_examples_by_intent(prompt)
    secondary = {k: v for k, v in counts.items() if k not in DOMINANT_INTENTS}
    median = statistics.median(secondary.values())
    worst, worst_count = max(secondary.items(), key=lambda kv: kv[1])
    return median, worst, worst_count


class PromptBalanceTests(unittest.TestCase):
    def test_no_secondary_intent_is_over_reinforced(self):
        median, worst, count = secondary_balance(kisna_classifier_intent)
        limit = MAX_SECONDARY_MULTIPLE * median
        self.assertLessEqual(
            count,
            limit,
            f"intent '{worst}' has {count} examples against a secondary median "
            f"of {median} (limit {limit:.0f}). Adding examples is how the "
            f"store_info attractor formed — fix the RULE instead.",
        )

    def test_every_intent_has_at_least_one_example(self):
        counts = count_examples_by_intent(kisna_classifier_intent)
        missing = [intent for intent, count in counts.items() if count == 0]
        self.assertEqual(
            missing, [], f"intents with no worked example: {missing}"
        )

    def test_store_info_is_no_longer_the_dominant_secondary(self):
        counts = count_examples_by_intent(kisna_classifier_intent)
        self.assertLessEqual(
            counts["store_info"],
            6,
            "store_info example count is creeping back up; it was 17 when the "
            "all-null attractor formed.",
        )

    def test_threshold_would_have_caught_the_original_drift(self):
        """Proof the threshold catches the regression it was written for.

        Rebuilds the historical distribution in the OLD example format (JSON
        payloads rather than one-liners), measured from the combined prompt as
        of commit 813e028. That prompt is deleted; its shape is kept here so
        the calibration stays checkable — and so the counter is exercised
        against both formats.
        """
        historical = {
            "store_info": 17, "product_search": 40, "general": 20,
            "product_info": 12, "greeting": 10, "human_handoff": 11,
            "callback": 3, "video_call": 4, "offers": 6, "complaint": 6,
            "returns_refund": 5, "order_tracking": 5, "compare": 3,
            "repair": 4, "gold_rate": 3, "menu_help": 2,
        }
        old_format = "\n".join(
            f'{i}. "example {i}" -> {{"intent": "{intent}", "confidence": 0.9}}'
            for intent, n in historical.items()
            for i in range(n)
        )

        counts = count_examples_by_intent(old_format)
        self.assertEqual(counts["store_info"], 17, "counter mis-read old format")

        median, worst, count = secondary_balance(old_format)
        self.assertEqual(worst, "store_info")
        self.assertGreater(
            count,
            MAX_SECONDARY_MULTIPLE * median,
            f"expected the historical shape to trip the balance check, but "
            f"'{worst}' was {count} against median {median}",
        )


if __name__ == "__main__":
    unittest.main()
