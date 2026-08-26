"""P0 defects from the 2026-08-22 heavy QA pass (audit/heavy_loadtest_report.md).

251 conversations / 532 turns replayed through the real pipeline surfaced three
defects that fire every time, not flakily:

P0-1  Any off-step message during the shopping funnel wiped every collected
      slot. Real session: "Do you have rings" -> "Under 10k ?" came back as
      "Hi! What are you looking for today?" with the category gone. ~30
      independent off-step messages were tried and NONE kept their slots.

P0-2  A budget ceiling stated in any non-Latin script became a FLOOR. Real
      session: a Marathi request for gold rings under Rs 20,000 was confirmed
      back as "Rs 20,000 to Rs 30,000" and every product shown cost more than
      the customer's stated limit.

P0-3  Order tracking echoed a garbage id scraped out of ordinary words --
      "track my order" replied "Order *my*", "tracking my order" replied
      "Order *ing*" -- and the same junk was used to build the tracking URL.
"""

import os
import re
import asyncio
import unittest
from unittest import mock

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
from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    _MAX_DIRECTION_RE,
    normalize_price_entities,
)
from kisna_chatbot.processors.order_tracking_agent import (  # noqa: E402
    _extract_order_id_from_text,
)
from kisna_chatbot.processors import product_search_agent_v3  # noqa: E402
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    _ESCAPE_RE,
    _SHOW_ME_RE,
    WIZARD_CARRYOVER_KEYS,
    _any_answer_target_step,
    _names_new_product,
)


class OrderIdExtractionTests(unittest.TestCase):
    """P0-3 -- an order id always carries digits; ordinary words never do."""

    def test_natural_phrasings_yield_no_id(self):
        # Each of these produced a user-visible "Order *my*" / "Order *ing*".
        for text in (
            "track my order",
            "i want to track my order",
            "tracking my order",
            "my order track",
            "track order",
            "order status?",
            "I had ordered a chain 3 years ago. I want you to track my order.",
        ):
            self.assertIsNone(_extract_order_id_from_text(text), text)

    def test_real_ids_are_still_extracted(self):
        for text, expected in (
            ("track order KIS12345", "KIS12345"),
            ("my order id is #KIS12345", "KIS12345"),
            ("order no 123456", "123456"),
            ("order id: ORD-99", "ORD-99"),
            ("I want to track my order 987654", "987654"),
            ("KIS-1234 kaha hai", "KIS-1234"),
        ):
            self.assertEqual(_extract_order_id_from_text(text), expected, text)


class NonLatinBudgetDirectionTests(unittest.TestCase):
    """P0-2 -- a stated ceiling stays a ceiling in every script we serve."""

    CEILINGS = (
        ("marathi", "मला २० हजार रुपयांपेक्षा कमी किमतीची सोन्याची अंगठी विकत घ्यायची आहे.", 20000),
        ("hindi_se_kam", "मुझे 25 हज़ार से कम की अंगूठी चाहिए", 25000),
        ("hindi_ke_andar", "50000 के अंदर अंगूठी दिखाओ", 50000),
        ("gujarati", "મને ૫૦ હજાર રૂપિયાથી ઓછી કિંમતની બુટ્ટી જોઈએ છે", 50000),
        ("bengali", "২০,০০০ টাকার কম দামের সোনার আংটি দেখান", 20000),
        ("tamil", "30 ஆயிரத்திற்குள் மோதிரம் காட்டுங்கள்", 30000),
        ("telugu", "50 వేల లోపు ఉంగరాలు చూపించండి", 50000),
        ("kannada", "50000 ಒಳಗೆ ಉಂಗುರ ತೋರಿಸಿ", 50000),
        ("malayalam", "50000 രൂപയ്ക്ക് താഴെ മോതിരം", 50000),
        ("punjabi", "30 ਹਜ਼ਾਰ ਤੋਂ ਘੱਟ ਦੀ ਅੰਗੂਠੀ", 30000),
    )

    def test_ceiling_is_never_turned_into_a_floor(self):
        for label, query, ceiling in self.CEILINGS:
            out = normalize_price_entities(query, {"max_price": ceiling})
            self.assertIsNone(out.get("min_price"), f"{label}: {query}")
            self.assertEqual(out.get("max_price"), ceiling, label)

    def test_floor_stays_a_floor(self):
        for label, query, floor in (
            ("hindi", "50 हज़ार से ज़्यादा का नेकलेस", 50000),
            ("marathi", "२० हजारपेक्षा जास्त", 20000),
            ("gujarati", "૪૦ હજારથી વધુ કિંમતની બુટ્ટી", 40000),
            ("bengali", "৫০,০০০ থেকে বেশি", 50000),
            ("telugu", "50 వేల కంటే ఎక్కువ", 50000),
        ):
            out = normalize_price_entities(query, {"min_price": floor})
            self.assertIsNone(out.get("max_price"), label)
            self.assertEqual(out.get("min_price"), floor, label)

    def test_latin_and_hinglish_unchanged(self):
        for query, ceiling in (
            ("I want a gold ring under 20000", 20000),
            ("gold ring below 25k", 25000),
            ("25k tak ki ring dikhao", 25000),
        ):
            out = normalize_price_entities(query, {"max_price": ceiling})
            self.assertIsNone(out.get("min_price"), query)

    def test_single_stated_amount_still_widens_to_a_band(self):
        # The band behaviour is deliberate and must survive the direction fix.
        for query, entities in (
            ("50k ka ring", {"max_price": 50000}),
            ("price 50000", {"max_price": 50000}),
        ):
            out = normalize_price_entities(query, dict(entities))
            self.assertIsNotNone(out.get("min_price"), query)
            self.assertNotEqual(out.get("min_price"), out.get("max_price"), query)

    def test_indic_word_boundary_trap(self):
        """The native alternatives must NOT be \\b-wrapped.

        Python's \\w does not classify Indic combining marks as word characters,
        so \\b immediately after one never fires. Every phrase below ends in a
        combining mark and is silently unmatchable once wrapped -- if someone
        "tidies" the regex by adding \\b, this fails loudly instead of quietly
        reverting the P0. ("से कम" is the control: it ends in a full consonant,
        which is why the trap is easy to miss when spot-checking Hindi only.)
        """
        for label, pattern, text in (
            ("marathi", r"पेक्षा\s*कमी", "२० हजार पेक्षा कमी दाखवा"),
            ("telugu", r"లోపు", "50 వేల లోపు ఉంగరాలు"),
            ("tamil", r"குள்", "30 ஆயிரத்திற்குள் மோதிரம்"),
            ("kannada", r"ಒಳಗೆ", "50000 ಒಳಗೆ ಉಂಗುರ"),
        ):
            self.assertIsNone(
                re.compile(rf"\b{pattern}\b").search(text),
                f"{label}: \\b unexpectedly matched — trap assumption is stale",
            )
            self.assertIsNotNone(re.compile(pattern).search(text), label)
            self.assertIsNotNone(_MAX_DIRECTION_RE.search(text), label)

        self.assertIsNotNone(re.compile(r"\bसे\s*कम\b").search("25 हज़ार से कम"))


class WizardCarryoverTests(unittest.TestCase):
    """P0-1 -- the funnel must survive a message that is not the current step."""

    def test_everything_collected_is_carried_not_just_button_slots(self):
        for key in (
            "category",
            "gender",
            "material_type",
            "fulfillment",
            "min_price",
            "max_price",
        ):
            self.assertIn(key, WIZARD_CARRYOVER_KEYS, key)

    def test_show_me_alone_is_not_an_escape(self):
        # "show me gold ones" at the material step is an ANSWER. It used to
        # match _ESCAPE_RE and tear the funnel down.
        self.assertIsNone(_ESCAPE_RE.search("show me gold ones"))
        self.assertIsNotNone(_SHOW_ME_RE.search("show me gold ones"))
        self.assertFalse(_names_new_product("show me gold ones"))

    def test_show_me_a_different_product_still_escapes(self):
        self.assertTrue(_names_new_product("show me necklaces"))

    def test_other_escape_words_are_untouched(self):
        for text in ("skip", "koi bhi", "browse all", "doesn't matter"):
            self.assertIsNotNone(_ESCAPE_RE.search(text), text)


class DeclineTargetsTheNamedSlotTests(unittest.TestCase):
    """A decline marks the slot the user NAMED, not the one on screen.

    "no specific budget" typed at the material step set material_type = any --
    the user said nothing about metal, and the budget they did speak to went
    unrecorded.
    """

    def test_named_budget_decline_marks_budget_from_any_step(self):
        for text in (
            "no specific budget",
            "koi specific budget nahi hai",
            "*koi specific budget nahi*",
            "no budget",
            "budget nahi",
            "कोई specific budget नहीं है।",
            "मेरा कोई बजट नहीं है",
        ):
            self.assertEqual(_any_answer_target_step(text, "material"), "budget", text)
            self.assertEqual(_any_answer_target_step(text, "gender"), "budget", text)

    def test_unnamed_decline_still_answers_the_current_step(self):
        for text, step in (
            ("anyone", "gender"),
            ("either is fine", "fulfillment"),
            ("koi bhi", "gender"),
            ("whatever", "material"),
            ("doesn't matter", "material"),
        ):
            self.assertEqual(_any_answer_target_step(text, step), step, text)

    def test_budget_step_itself_is_unchanged(self):
        self.assertEqual(_any_answer_target_step("no specific budget", "budget"), "budget")


class ConfirmationRefinementTests(unittest.TestCase):
    """P0-1 (confirmation half) -- narrowing a recap must not discard it.

    "show me something in evil eye" -> recap -> "under 20k" used to throw the
    recap away, collection included, and restart the conversation.

    The helper is LLM-primary now, so these stub the extractor rather than
    hitting the network: the point under test is the MERGE policy, not whether
    gpt-4o-mini reads a given sentence.
    """

    PENDING = {"entities": {"collection": "evil eye", "category": None}}

    @staticmethod
    def _merge(pending, text, stated=None, classified="product_search"):
        data = {"classified_category": classified}

        async def fake_extract(**_kwargs):
            return dict(stated or {})

        with mock.patch.object(
            product_search_agent_v3, "extract_entities_with_llm", fake_extract
        ):
            return asyncio.run(
                product_search_agent_v3._confirm_refinement_merge(
                    data, pending, text
                )
            )

    def test_budget_refines_instead_of_replacing(self):
        merged = self._merge(self.PENDING, "under 20k", {"max_price": 20000})
        self.assertIsNotNone(merged)
        self.assertEqual(merged.get("collection"), "evil eye")
        self.assertEqual(merged.get("max_price"), 20000)

    def test_price_refinement_replaces_the_whole_band(self):
        pending = {
            "entities": {
                "collection": "evil eye",
                "min_price": 10000,
                "max_price": 30000,
            }
        }
        merged = self._merge(pending, "under 20k", {"max_price": 20000})
        self.assertEqual(merged.get("max_price"), 20000)
        self.assertIsNone(merged.get("min_price"))

    def test_a_different_product_is_not_a_refinement(self):
        merged = self._merge(
            self.PENDING, "show me necklaces", {"category": "necklace"}
        )
        self.assertIsNone(merged)

    def test_a_non_shopping_route_still_escapes(self):
        """The classifier's route is what vetoes an escape now."""
        for text, route in (
            ("do you have a store in Mumbai", "store_info"),
            ("where is my order", "track_order"),
            ("hi", "greeting"),
        ):
            self.assertIsNone(self._merge(self.PENDING, text, {}, route), text)
        self.assertIsNone(self._merge(self.PENDING, "", {}))

    def test_an_unreadable_refinement_keeps_the_search(self):
        """D1: the whole point -- a recap survives what we cannot parse.

        "show me cheaper ones" came back as a bare action="more" with no slot
        value in it, so the old regex-only merge returned None and the entire
        search was thrown away in favour of a greeting.
        """
        merged = self._merge(self.PENDING, "show me cheaper ones", {"action": "more"})
        self.assertIsNotNone(merged)
        self.assertEqual(merged.get("collection"), "evil eye")

    def test_price_direction_shifts_the_recapped_band(self):
        pending = {"entities": {"category": "ring", "max_price": 50000}}
        merged = self._merge(
            pending, "thoda sasta dikhao", {"price_direction": "lower"}
        )
        self.assertEqual(merged.get("category"), "ring")
        self.assertLess(merged.get("max_price"), 50000)

        merged_up = self._merge(
            pending, "aur premium wale dikhao", {"price_direction": "higher"}
        )
        self.assertEqual(merged_up.get("min_price"), 65000)
        self.assertIsNone(merged_up.get("max_price"))


if __name__ == "__main__":
    unittest.main()
