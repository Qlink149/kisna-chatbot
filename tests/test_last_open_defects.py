"""The last four open defects from `audit/FINAL_QA_REPORT.md`.

1  "story udaipur" answered "are you looking for a specific piece?" while
   KISNA has a branch in Udaipur (3/3). The classifier returns `general` at
   **0.3-0.4 confidence** -- under CLARIFICATION_CONFIDENCE_THRESHOLD -- so
   the generic clarification card shipped. Every correctly-spelled variant
   scores 0.92-0.93. The rescue therefore sits ONLY on the low-confidence
   path, where we were already about to admit we did not understand, and
   requires both a near-miss of a store word AND a real store city.

2  Tamil அத்தை dropped gender 3/4 while சித்தி, ફોઈ, बुआ and "aunt" all
   worked. The gender rule already said "IN ANY LANGUAGE ... read the word"
   and already listed `athai` -- romanized. The romanized list is what
   anchored the model to Latin.

   Placement turned out to matter: with the native-script clause written
   AFTER the AMBIGUOUS rule, "for my cousin" flipped from null to men, 4/4
   (baseline: null 4/4). Moved above that rule, cousin is null again.

3a Malayalam offers came back "സുവർണ്ണ/ índice മൂല്യം" -- a Spanish word
   inside correct Malayalam, invisible to the script check because Latin is
   always allowed. Across 1,083 native-script replies in the QA corpus, 250
   distinct Latin words appeared and exactly ONE carried a diacritic: this
   bug. So an accent the source does not contain is an exact signal.

3b Two cards in one Bengali reply rendered "সাইজ 10" and "সাইজ ১০".

4  Hindi "समय क्या है?" right after store cards answered with KISNA support
   hours; Tamil "நேரம் என்ன?" answered with the real branch hours from the
   same context. The KB rule sent every hours question to the support entry
   with no exception for "we just showed you branches".
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
from kisna_chatbot.processors.classifier import (  # noqa: E402
    _is_misspelled_store_lookup,
    _within_one_edit,
)
from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor  # noqa: E402
from kisna_chatbot.prompts.general_agent_kisna import (  # noqa: E402
    general_agent_prompt,
)
from kisna_chatbot.utils.reply_composer import (  # noqa: E402
    _compose_instruction,
    _has_foreign_latin_word,
    _is_unusable_rewrite,
)


class OneTypingSlipTests(unittest.TestCase):
    def test_the_four_shapes_of_a_single_slip(self):
        for word in ("store", "stor", "storee", "storw", "stroe", "sotre"):
            self.assertTrue(_within_one_edit(word, "store"), word)

    def test_two_slips_are_not_one(self):
        for word in ("sorry", "strawberry", "sto", "sxxre"):
            self.assertFalse(_within_one_edit(word, "store"), word)


class MisspelledStoreLookupTests(unittest.TestCase):
    def test_a_mistyped_store_word_beside_a_real_city_is_a_store_lookup(self):
        for query in (
            "story udaipur",
            "stroe delhi",
            "sotre mumbai",
            "shopp mumbai",
            "showrom jaipur",
            "udaipur story",
            "story in udaipur",
        ):
            self.assertTrue(_is_misspelled_store_lookup(query), query)

    def test_a_store_word_alone_is_not_enough(self):
        # Without a real city this is just conversation.
        for query in ("tell me a story", "story time", "read me a story"):
            self.assertFalse(_is_misspelled_store_lookup(query), query)

    def test_a_city_alone_is_not_enough(self):
        # A bare city is an answer to some other question as often as it is a
        # store request; the rescue must not claim it.
        for query in ("udaipur", "delhi", "mumbai please"):
            self.assertFalse(_is_misspelled_store_lookup(query), query)

    def test_a_jewellery_word_means_they_are_shopping(self):
        # "stone" is one edit from "store" -- without this guard, a shopper
        # asking for stone rings would be sent to the store locator.
        for query in (
            "stone ring udaipur",
            "stone rings in jaipur",
            "stone necklace delhi",
        ):
            self.assertFalse(_is_misspelled_store_lookup(query), query)

    def test_a_long_message_is_never_a_bare_store_lookup(self):
        self.assertFalse(
            _is_misspelled_store_lookup(
                "my story is long and i would love to tell you about udaipur"
            )
        )


class KinshipInNativeScriptTests(unittest.TestCase):
    def test_the_prompt_says_the_lists_are_romanized(self):
        self.assertIn("ROMANIZED", kisna_entity_extractor)
        self.assertIn("அத்தை", kisna_entity_extractor)

    def test_the_clause_sits_above_the_ambiguity_rule(self):
        """Order is load-bearing, not cosmetic.

        Below the AMBIGUOUS rule, this clause overrode it and "for my cousin"
        came back men 4/4 where the baseline gave null 4/4.
        """
        native = kisna_entity_extractor.index("ROMANIZED")
        ambiguous = kisna_entity_extractor.index("AMBIGUOUS")
        self.assertLess(native, ambiguous)

    def test_the_ambiguous_rule_still_names_cousin(self):
        self.assertIn("cousin", kisna_entity_extractor)


class ForeignWordLeakTests(unittest.TestCase):
    SOURCE = "Current KISNA offers. These % apply to making charges only."

    def test_an_accent_the_source_lacks_is_a_leak(self):
        self.assertTrue(
            _has_foreign_latin_word(self.SOURCE, "സുവർണ്ണ/ índice മൂല്യം")
        )
        self.assertTrue(_has_foreign_latin_word(self.SOURCE, "சுவர்ண coração மதிப்பு"))

    def test_a_clean_rewrite_is_not_a_leak(self):
        for rewritten in (
            "ഇന്നത്തെ KISNA ഓഫറുകൾ: 20% ഇളവ് — ₹50,000 വരെ",
            "आज के KISNA ऑफर: मेकिंग चार्ज पर 20% छूट",
            "*Current KISNA offers*",
        ):
            self.assertFalse(_has_foreign_latin_word(self.SOURCE, rewritten), rewritten)

    def test_an_accent_the_source_carries_is_allowed(self):
        # A product or store name with an accent must never trip this.
        self.assertFalse(_has_foreign_latin_word("Café KISNA", "Café കിസ്ന"))

    def test_maths_signs_share_the_range_but_are_not_letters(self):
        for rewritten in ("വലുപ്പം 10 × 5 mm", "10 ÷ 2"):
            self.assertFalse(_has_foreign_latin_word(self.SOURCE, rewritten), rewritten)

    def test_the_leak_reaches_the_retry_ladder(self):
        self.assertTrue(
            _is_unusable_rewrite("ml", "സുവർണ്ണ/ índice മൂല്യം", self.SOURCE)
        )

    def test_the_source_argument_stays_optional(self):
        # Callers that have no source must keep working unchanged.
        self.assertFalse(_is_unusable_rewrite("ta", "நாங்கள் 7 நாள் கொள்கை வழங்குகிறோம்."))


class NumeralConsistencyTests(unittest.TestCase):
    def test_the_composer_asks_for_source_digits(self):
        self.assertIn("NUMERALS", _compose_instruction("Bengali"))


class BranchHoursBeatSupportHoursTests(unittest.TestCase):
    def test_the_kb_carries_the_exception(self):
        self.assertIn("STORE CARDS", general_agent_prompt)

    def test_support_hours_remain_the_default(self):
        # The exception must not delete the rule it qualifies.
        self.assertIn("Support hours", general_agent_prompt)
        hours_rule = general_agent_prompt.index("Opening / office / support hours")
        exception = general_agent_prompt.index("STORE CARDS")
        self.assertLess(hours_rule, exception)


class ResistPressureTests(unittest.TestCase):
    """Live: a customer falsely and repeatedly insisted "your website says
    you buy jewellery from other brands" -- across 5 increasingly insistent
    turns the bot went from correctly refusing to fully fabricating a fake
    policy with invented steps, none of it in the KB. general_agent.py
    passes 8 turns of chat history back each turn, so the model saw its own
    earlier wavering and kept sliding -- the fix is prompt-only."""

    def test_resist_pressure_section_present(self):
        self.assertIn("RESIST PRESSURE", general_agent_prompt)
        self.assertIn("INSISTENCE IS NOT EVIDENCE", general_agent_prompt)

    def test_section_names_the_reproduced_failure(self):
        # Anchored to the actual incident, not a generic rephrase, so a
        # future edit can't accidentally weaken it into something vaguer.
        self.assertIn("your website", general_agent_prompt.lower())
        self.assertIn(
            "is never a reason to change a kb-grounded answer",
            general_agent_prompt.lower(),
        )

    def test_handoff_is_the_escape_hatch_not_negotiation(self):
        idx = general_agent_prompt.index("RESIST PRESSURE")
        section = general_agent_prompt[idx : idx + 1500]
        self.assertIn("honest handoff line", section)
        self.assertIn("do NOT keep negotiating", section)

    def test_self_check_also_rejects_insistence_as_a_source(self):
        idx = general_agent_prompt.index("SELF-CHECK")
        section = general_agent_prompt[idx : idx + 1200]
        self.assertIn("is NOT a source", section)

    def test_placed_near_the_existing_anti_hallucination_rules(self):
        # Same family of rule -- keep them adjacent so a future edit to one
        # is likely to notice the other.
        pressure_idx = general_agent_prompt.index("RESIST PRESSURE")
        anti_halluc_idx = general_agent_prompt.index("ANTI-HALLUCINATION RULES")
        self.assertLess(pressure_idx, anti_halluc_idx)
        gap = general_agent_prompt[pressure_idx:anti_halluc_idx]
        self.assertLess(len(gap), 2000, "too much unrelated content between the two")


if __name__ == "__main__":
    unittest.main()
