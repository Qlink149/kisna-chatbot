"""P1 defects from the 2026-08-22 heavy QA pass (audit/heavy_loadtest_report.md).

P1-4   An all-English conversation flipped to Hinglish and stayed there (9/9
       live): the classifier must emit SOME language label even for "under
       50k", and acting on it rewrote the whole rest of the chat.
P1-5   Gold-rate and offers replies were never translated -- those builders
       emitted untagged text and localize_bot_responses only rewrites tagged
       responses.
P1-6   Native-script replies came back mistranslated, with characters from
       unrelated scripts spliced in (Arabic inside Bengali, Malayalam inside
       Gujarati, Devanagari inside Telugu).
P1-7   silver / platinum / pearl were silently dropped by the funnel, which
       then offered Gold / Diamond / Gemstone as if nothing had been said.
P1-9   "### heading" and "[label](url)" reached users as literal punctuation.
P1-10  "under 50k" was intermittently read as an exact price and widened
       UPWARD, so results cost more than the stated ceiling (4 of 13 live).
P1-11  "under 10 carats" was parsed as a Rs 10 budget.
P1-12  Bare negation ("just not gold") set material_type to the very metal the
       customer ruled out.
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
from kisna_chatbot.ai.config import resolve_compose_model  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    _is_low_language_signal,
    _store_language,
)
from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    _extract_prices,
    extract_entities,
)
from kisna_chatbot.processors.response_manager import (  # noqa: E402
    _fix_whatsapp_markdown,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    _parse_text_for_step,
    _unsupported_material_note,
)
from kisna_chatbot.utils.reply_composer import _script_violations  # noqa: E402


class ReplyLanguageStabilityTests(unittest.TestCase):
    """P1-4 -- a slot answer is not a language change."""

    LOW_SIGNAL = (
        "under 50k", "Female", "Gold", "anyone", "50000", "yes", "Under 10k ?",
        "ok", "Ready to ship", "Either is fine", "15-35k", "koi bhi", "?", "male",
    )
    REAL_EVIDENCE = (
        "Return krna hai",
        "mujhe sone ki anguthi dikhao",
        "I want a gold ring for my wife",
        "tamari pase ring che?",
        "मुझे अंगूठी चाहिए",
    )

    def test_low_signal_messages_are_recognised(self):
        for text in self.LOW_SIGNAL:
            self.assertTrue(_is_low_language_signal(text), text)

    def test_real_language_evidence_is_not_suppressed(self):
        # Length alone would misfile "Return krna hai" (3 words) as noise.
        for text in self.REAL_EVIDENCE:
            self.assertFalse(_is_low_language_signal(text), text)

    def test_english_session_does_not_drift_to_hinglish(self):
        for text in ("under 50k", "Female", "Gold", "Under 10k ?"):
            profile = {"language": "en"}
            _store_language(profile, "hi", text)
            self.assertEqual(profile["language"], "en", text)

    def test_native_script_session_is_not_demoted_by_one_english_word(self):
        for text in ("Gold", "Female", "under 50k"):
            profile = {"language": "gu"}
            _store_language(profile, "gu", text)
            self.assertEqual(profile["language"], "gu", text)

    def test_a_real_switch_still_applies(self):
        for text, label, expected in (
            ("mujhe sone ki anguthi dikhao bhai", "hi", "hi-Latn"),
            ("मुझे सोने की अंगूठी दिखाओ", "hi", "hi"),
            ("મને સોનાની વીંટી બતાવો", "gu", "gu"),
        ):
            profile = {"language": "en"}
            _store_language(profile, label, text)
            self.assertEqual(profile["language"], expected, text)

    def test_explicit_override_still_wins(self):
        profile = {"language": "hi"}
        _store_language(profile, "hi", "talk to me in English")
        self.assertEqual(profile["language"], "en")


class ComposeModelRoutingTests(unittest.TestCase):
    """P1-6 -- weak languages route to a stronger model; the rest do not."""

    def test_weak_languages_are_routed(self):
        for lang in ("ta", "te", "bn", "pa", "kn", "ml", "gu", "mr"):
            self.assertIsNotNone(resolve_compose_model(lang), lang)

    def test_strong_and_romanized_languages_are_not_routed(self):
        for lang in ("en", "hi", "hi-Latn", "gu-Latn", "ta-Latn", ""):
            self.assertIsNone(resolve_compose_model(lang), lang)


class ScriptPurityTests(unittest.TestCase):
    """P1-6 -- the guard must see the WRONG Indic script, not just 'some'."""

    def test_foreign_indic_script_is_caught(self):
        # Each of these was observed live and passed the old check, which only
        # asked whether the reply contained any character in U+0900-U+0D7F.
        self.assertTrue(_script_violations("te", "మహిళలకి महिला వజ్రమణికలు"))
        self.assertTrue(_script_violations("gu", "તમારું વિશ્વસનીય ആഭൂഷണ સહાયક"))
        self.assertTrue(_script_violations("pa", "ਤੁਸੀਂ آج ਕੀ ਵੇਖਣਾ ਚਾਹੁੰਦੇ ਹੋ?"))
        self.assertTrue(_script_violations("bn", "দ্বন্দ্ব ! এটা کس کے জন্য ?"))

    def test_clean_native_replies_pass(self):
        self.assertFalse(_script_violations("te", "అర్థమైంది వజ్రపు ఉంగరాలు"))
        self.assertFalse(_script_violations("gu", "સોનાની વીંટીઓ"))
        self.assertFalse(_script_violations("hi", "सोने की अंगूठियाँ"))

    def test_latin_digits_and_emoji_are_always_allowed(self):
        # Prices, URLs and SKUs are meant to survive untranslated.
        self.assertFalse(
            _script_violations("hi", "सोने की अंगूठी ₹50,000 👋 https://kisna.com KIS12345")
        )


class WhatsAppMarkdownTests(unittest.TestCase):
    """P1-9 -- WhatsApp renders *bold* only; everything else leaks."""

    def test_headings_become_bold(self):
        self.assertEqual(_fix_whatsapp_markdown("### KMR Overview"), "*KMR Overview*")

    def test_links_lose_their_punctuation(self):
        self.assertEqual(
            _fix_whatsapp_markdown("find it [here](https://kisna.com/store)"),
            "find it here: https://kisna.com/store",
        )
        # A label that is just the domain would read "x.com: https://x.com".
        self.assertEqual(
            _fix_whatsapp_markdown("[meriroshni.kisna.com](https://meriroshni.kisna.com)"),
            "https://meriroshni.kisna.com",
        )

    def test_bullets_and_double_bold(self):
        self.assertEqual(_fix_whatsapp_markdown("- *Variants*: two"), "• *Variants*: two")
        self.assertEqual(_fix_whatsapp_markdown("**Joining**: now"), "*Joining*: now")

    def test_a_bolded_line_is_not_read_as_a_bullet(self):
        self.assertEqual(_fix_whatsapp_markdown("**Note** applies"), "*Note* applies")

    def test_ordinary_text_is_untouched(self):
        for text in (
            "*already bold*",
            "price is 5*4",
            "#1 bestseller",
            "a - b",
            "Colour #FF00AA",
            "_italic_ stays",
            "~strike~ stays",
            "https://kisna.com/x?a=1",
        ):
            self.assertEqual(_fix_whatsapp_markdown(text), text, text)


class BudgetCeilingTests(unittest.TestCase):
    """P1-10 / P1-11 -- a ceiling is a ceiling, and a unit is not money."""

    def test_degenerate_llm_band_defers_to_the_deterministic_parser(self):
        for text, amount in (("under 50k", 50000), ("below 30000", 30000)):
            result = _parse_text_for_step(
                "budget", text, {"min_price": amount, "max_price": amount}
            )
            self.assertEqual(result, (None, float(amount)), text)

    def test_a_genuine_single_amount_still_widens(self):
        result = _parse_text_for_step(
            "budget", "around 50000", {"min_price": 50000, "max_price": 50000}
        )
        self.assertIsNotNone(result[0])
        self.assertNotEqual(result[0], result[1])

    def test_measurements_are_not_budgets(self):
        for text in (
            "Show me rings under 10 carats",
            "rings under 18 kt",
            "under 5 grams",
            "delivery under 7 days",
            "under 1.5 carat solitaire",
        ):
            self.assertEqual(_extract_prices(text), (None, None), text)

    def test_real_budgets_still_parse(self):
        for text, expected in (
            ("Show me rings under 10000", (None, 10000.0)),
            ("under 50k", (None, 50000.0)),
            ("under 1 lakh", (None, 100000.0)),
            ("within budget of 30000", (None, 30000.0)),
        ):
            self.assertEqual(_extract_prices(text), expected, text)


class BareNegationTests(unittest.TestCase):
    """P1-12 -- refusing a metal must not select it."""

    def test_bare_negation_extracts_no_material(self):
        for text in (
            "I am looking for something which is not in gold",
            "I don't know, just not gold",
            "gold nahi chahiye",
            "something without gold",
        ):
            self.assertIsNone(extract_entities(text).get("material_type"), text)

    def test_a_named_alternative_is_kept(self):
        for text, expected in (
            ("I need a diamond ring not gold", "diamond"),
            ("Much gold nahi diamond ki dikhao", "diamond"),
            ("gold nahi, gemstone dikhao", "gemstone"),
        ):
            self.assertEqual(extract_entities(text).get("material_type"), expected, text)

    def test_plain_positive_requests_are_unchanged(self):
        for text, expected in (
            ("I need a gold ring", "gold"),
            ("show me diamond rings", "diamond"),
            ("sone ki anguthi dikhao", "gold"),
        ):
            self.assertEqual(extract_entities(text).get("material_type"), expected, text)


class UnsupportedMaterialTests(unittest.TestCase):
    """P1-7 -- say we don't carry it instead of quietly offering gold."""

    def test_note_is_produced_for_unsupported_material(self):
        note = _unsupported_material_note({"unsupported_material": True})
        self.assertIsNotNone(note)
        self.assertIn("silver", note["text"])
        # Must not promise products — a question follows, not a result list.
        self.assertNotIn("Here are some beautiful options", note["text"])

    def test_no_note_for_supported_material(self):
        self.assertIsNone(_unsupported_material_note({"material_type": "gold"}))
        self.assertIsNone(_unsupported_material_note({}))
        self.assertIsNone(_unsupported_material_note(None))


class TranslationTaggingTests(unittest.TestCase):
    """P1-5 -- untagged replies are never translated."""

    def test_offers_and_gold_rate_builders_tag_their_text(self):
        from kisna_chatbot.processors.gold_rate_handler import (
            build_gold_rate_bot_response,
        )
        from kisna_chatbot.processors.offers_agent import (
            _build_empty_response,
            _build_error_response,
        )

        for builder in (_build_empty_response, _build_error_response):
            responses = builder()
            self.assertTrue(responses[0].get("_compose"), builder.__name__)

        import inspect

        source = inspect.getsource(build_gold_rate_bot_response)
        self.assertIn("_compose", source)

    def test_tags_are_functional_not_personality(self):
        from kisna_chatbot.utils.reply_composer import _PERSONALITY_TAGS

        # Rates and offers must be mirrored faithfully, never re-narrated.
        for tag in ("offers_list", "offers_empty", "offers_error", "gold_rates"):
            self.assertNotIn(tag, _PERSONALITY_TAGS)


if __name__ == "__main__":
    unittest.main()


class KinshipGenderTests(unittest.TestCase):
    """Gender must come from the WORD, not from a hand-maintained list.

    "Show me a diamond ring of 14 KT, around 50k, Make to order for my chachi"
    was answered "diamond rings for men". Two hardcoded lists caused it: the
    prompt enumerated allowed kinship terms and told the model not to guess
    outside them, and _gender_evidenced then discarded anything the model DID
    emit that its own regex did not recognise. "chachi" was on neither list.

    A list cannot cover kinship across nine languages (kaki, atya, athai,
    pinni, pisi, mausi, phupi, chithi...), so the guard now asks a structural
    question -- does this message name a recipient at all -- instead of a
    lexical one. Its real job was only ever to stop the classifier inheriting
    a gender from chat history.
    """

    def test_a_named_recipient_counts_as_evidence(self):
        from kisna_chatbot.processors.entity_extractor import _names_a_recipient

        for text in (
            "I need a ring for my chachi",
            "I need a ring for my athai",
            "meri bua ke liye ring chahiye",
            "મારે મારી ફોઈ માટે વીંટી જોઈએ છે",
        ):
            self.assertTrue(_names_a_recipient(text), text)

    def test_a_message_naming_nobody_is_not_evidence(self):
        from kisna_chatbot.processors.entity_extractor import _names_a_recipient

        # These are the hallucination cases the guard exists for: after a
        # women's search the classifier would happily carry gender forward.
        for text in ("under 20k", "show me necklaces", "aur dikhao", "gold"):
            self.assertFalse(_names_a_recipient(text), text)

    def test_ambiguous_recipients_never_count(self):
        from kisna_chatbot.processors.entity_extractor import is_ambiguous_audience

        # Named, but the word carries no gender -- the wizard must still ask.
        for text in (
            "a ring for my parents",
            "a ring for my cousin",
            "a ring for my sibling",
            "a ring for my in-laws",
            "a ring for a friend",
        ):
            self.assertTrue(is_ambiguous_audience(text), text)


class OpeningBudgetDeclineTests(unittest.TestCase):
    """A budget declined in the FIRST message must be recorded.

    "Show me a diamond ring of 14 KT, any price..." still asked "What's your
    budget?" -- the decline is not a number, so the price branch never saw it.
    advance_wizard handled this mid-funnel; seed_wizard_from_entities did not.
    """

    def test_opening_decline_marks_budget_answered(self):
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            seed_wizard_from_entities,
        )

        for query in (
            "Show me a diamond ring of 14 KT, any price",
            "show me rings, no specific budget",
            "rings dikhao, koi budget nahi",
        ):
            seeded = seed_wizard_from_entities({"category": "ring"}, query=query)
            self.assertEqual(seeded.get("budget"), ANY_SLOT, query)

    def test_a_query_with_no_budget_still_asks(self):
        from kisna_chatbot.processors.shopping_wizard import (
            get_next_step,
            seed_wizard_from_entities,
        )

        seeded = seed_wizard_from_entities(
            {"category": "ring", "gender": "women", "material_type": "diamond"},
            query="show me diamond rings for women",
        )
        self.assertIsNone(seeded.get("budget"))
        self.assertEqual(get_next_step(seeded), "budget")

    def test_more_ways_of_declining_a_budget_up_front(self):
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            seed_wizard_from_entities,
        )

        for query in (
            "14kt diamond rings of any price for men made to order",
            "14kt diamond rings at any price for men",
            "diamond rings for men, price no bar",
            "rings dikhao, price ki koi limit nahi",
        ):
            seeded = seed_wizard_from_entities({"category": "ring"}, query=query)
            self.assertEqual(seeded.get("budget"), ANY_SLOT, query)

    def test_a_stated_range_is_never_read_as_a_decline(self):
        from kisna_chatbot.processors.shopping_wizard import _ANY_ANSWER_RE

        for query in ("under 50k", "around 50k", "15-35k", "1 lakh tak"):
            self.assertIsNone(_ANY_ANSWER_RE.search(query), query)

    def test_llm_budget_any_is_the_primary_signal(self):
        """The LLM says it; the phrase list is only an outage fallback.

        A budget decline has no numeric form, and null cannot distinguish
        "said any price" from "never mentioned money" -- so the contract now
        carries budget="any", the same way it has always carried
        fulfillment="any". Live, the model returns it for Hindi, Tamil, Telugu,
        Bengali, Gujarati, Marathi and Kannada, none of which a phrase list
        reaches.
        """
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            seed_wizard_from_entities,
        )

        seeded = seed_wizard_from_entities(
            {"category": "ring", "budget": "any"},
            query="ตัวอย่าง no phrase list could match this",
        )
        self.assertEqual(seeded.get("budget"), ANY_SLOT)

    def test_llm_budget_field_survives_sanitisation(self):
        from kisna_chatbot.processors.classifier import _sanitize_llm_entities

        self.assertEqual(_sanitize_llm_entities({"budget": "any"})["budget"], "any")
        self.assertIsNone(_sanitize_llm_entities({"budget": "nonsense"})["budget"])
        self.assertIsNone(_sanitize_llm_entities({})["budget"])

    def test_llm_fulfillment_any_is_no_longer_discarded(self):
        # The contract always allowed "any" here; _llm_slot_values dropped it,
        # so "either is fine" in any language re-asked the question.
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            _llm_slot_values,
        )

        self.assertEqual(_llm_slot_values({"fulfillment": "any"})["fulfillment"], ANY_SLOT)
        self.assertEqual(_llm_slot_values({"fulfillment": "mto"})["fulfillment"], "mto")

    def test_a_real_budget_is_not_treated_as_a_decline(self):
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            seed_wizard_from_entities,
        )

        seeded = seed_wizard_from_entities(
            {"category": "ring", "max_price": 50000}, query="rings under 50k"
        )
        self.assertNotEqual(seeded.get("budget"), ANY_SLOT)
        self.assertEqual(seeded.get("max_price"), 50000)


class MultilingualRobustnessTests(unittest.TestCase):
    """Audit of the session's fixes for languages nobody enumerated.

    Several fixes shipped as Latin (or Latin+Devanagari) word lists, which is
    the failure mode this codebase keeps rediscovering: the list covers the
    languages someone thought of and silently breaks for the rest.
    """

    def test_a_stated_ceiling_survives_in_any_script(self):
        """The band-snap heuristic must not fire on text it cannot read.

        An Odia customer asking for rings UNDER Rs 20,000 got
        min=20000/max=30000: the model had read the ceiling correctly and a
        Latin-only heuristic overwrote it into a FLOOR. Direction words can
        only ever list known languages; deferring generalises to all of them.
        """
        from kisna_chatbot.processors.entity_extractor import normalize_price_entities

        for label, query in (
            ("odia", "୨୦ ହଜାରରୁ କମ୍ ମୂଲ୍ୟର ମୁଦି"),
            ("assamese", "২০ হাজাৰতকৈ কম"),
            ("malayalam", "20000 രൂപയ്ക്ക് താഴെ"),
            ("kannada", "20000 ಒಳಗೆ"),
        ):
            out = normalize_price_entities(query, {"max_price": 20000})
            self.assertIsNone(out.get("min_price"), label)
            self.assertEqual(out.get("max_price"), 20000, label)

    def test_the_latin_band_heuristic_still_applies_to_latin(self):
        from kisna_chatbot.processors.entity_extractor import normalize_price_entities

        for query, entities in (
            ("50k ka ring", {"max_price": 50000}),
            ("price 50000", {"max_price": 50000}),
            # Mixed script still bands: the Hinglish cue is readable.
            ("मुझे 50k ka ring chahiye", {"max_price": 50000}),
        ):
            out = normalize_price_entities(query, dict(entities))
            self.assertIsNotNone(out.get("min_price"), query)
            self.assertNotEqual(out.get("min_price"), out.get("max_price"), query)

    def test_budget_decline_mid_funnel_uses_the_llm_not_the_phrase_list(self):
        """_ANY_ANSWER_RE is Latin+Devanagari and misses Dravidian declines.

        The LLM field existed but was only wired into seeding, so the funnel
        re-asked a budget a Tamil customer had already waved away.
        """
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            _parse_text_for_step,
        )

        for label, query in (
            ("tamil", "பட்ஜெட் ஏதும் இல்லை"),
            ("telugu", "బడ్జెట్ ఏమీ లేదు"),
            ("kannada", "ಬಜೆಟ್ ಏನೂ ಇಲ್ಲ"),
            ("malayalam", "ബജറ്റ് ഒന്നുമില്ല"),
        ):
            self.assertEqual(
                _parse_text_for_step("budget", query, {"budget": "any"}),
                ANY_SLOT,
                label,
            )

    def test_a_real_amount_is_never_read_as_a_decline(self):
        from kisna_chatbot.processors.shopping_wizard import (
            ANY_SLOT,
            _parse_text_for_step,
        )

        result = _parse_text_for_step(
            "budget", "under 50k", {"min_price": 50000, "max_price": 50000}
        )
        self.assertNotEqual(result, ANY_SLOT)
        self.assertEqual(result, (None, 50000.0))

    def test_the_any_marker_reaches_the_collected_slots(self):
        # _apply_slot only understood a (min, max) tuple, so the marker
        # returned above was dropped and the step asked again.
        from kisna_chatbot.processors.shopping_wizard import ANY_SLOT, _apply_slot

        collected: dict = {}
        _apply_slot(collected, "budget", ANY_SLOT)
        self.assertEqual(collected.get("budget"), ANY_SLOT)


class QARegressionPassTests(unittest.TestCase):
    """Found by the regression QA pass on HEAD 7a975e4."""

    def test_budget_any_survives_merge_search_entities(self):
        """The LLM-primary field must reach the wizard on the SEARCH path.

        merge_search_entities rebuilds the entity dict from a hardcoded key
        list that had no "budget", so the field was dropped between
        combine_search_entities and start_wizard. Every non-Latin-script
        customer was re-asked a budget they had already declined; English only
        worked because the deterministic phrase regex caught it, i.e. the
        LLM-primary path was not actually doing the work.
        """
        from kisna_chatbot.processors.entity_extractor import merge_search_entities

        merged = merge_search_entities(
            {},
            {"category": "ring", "material_type": "diamond", "budget": "any"},
            "எனக்கு வைர மோதிரம் வேண்டும்",
        )
        self.assertEqual(merged.get("budget"), "any")

    def test_narrate_rejects_an_english_echo(self):
        """An empty model reply fell back to the English source.

        narrate() only checked for a FOREIGN script, which an all-English
        string passes, so 38% of native-script customers got the entire
        English KIA intro as their first message. compose() was already
        protected by the echo check; narrate now asks the same question.
        """
        from kisna_chatbot.utils.reply_composer import (
            _is_native_script_echo,
            _script_violations,
        )

        english = "Hi! I am KIA, your trusted jewellery assistant."
        # The old guard alone: clean, because English has no foreign script.
        self.assertFalse(_script_violations("ta", english))
        # The echo check is what catches it.
        self.assertTrue(_is_native_script_echo("ta", english))
        self.assertFalse(_is_native_script_echo("ta", "வணக்கம்! நான் கியா"))

    def test_narrate_budget_is_scaled_not_flat(self):
        # A flat 200 starved the routed reasoning model into empty output.
        from kisna_chatbot.utils.reply_composer import _compose_token_budget

        self.assertGreaterEqual(_compose_token_budget("short"), 400)
