"""Defects from audit/OPEN_DEFECTS_HANDOFF.md, verified live then pinned here.

Every case below was reproduced against the real pipeline first (see the
handoff doc for the transcripts). These tests cover the parts that are
deterministic; the parts that depend on what the LLM reads are verified with
the replay harness instead, because pinning a model's output in a unit test
proves nothing about the next model.

The recurring root cause across all of them: a Latin word list was the primary
reader and the LLM's answer was discarded, OR the model had no field in which
to record what it understood.
"""

import asyncio
import os
import unittest
from unittest import mock

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.main import app  # noqa: F401,E402  (breaks the import cycle)
from kisna_chatbot.processors import ad_flow_agent  # noqa: E402
from kisna_chatbot.processors import product_search_agent_v3  # noqa: E402
from kisna_chatbot.processors.classifier import _sanitize_llm_entities  # noqa: E402
from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    _CLARA_UNSUPPORTED_MATERIALS,
    _latin_price_direction,
    merge_search_entities,
)


class ExcludedMaterialTests(unittest.TestCase):
    """D4 -- "I don't want gold" returned material_type="gold", 6/6 Indic langs.

    The LLM itself was wrong, not our code: it had no field for a refusal, so
    it fell back on the additive mapping table. Giving it one fixed it -- the
    same move that fixed budget="any".
    """

    def test_refusal_is_kept_separately(self):
        out = _sanitize_llm_entities(
            {"category": "ring", "material_type": None, "excluded_material": "gold"}
        )
        self.assertIsNone(out["material_type"])
        self.assertEqual(out["excluded_material"], "gold")

    def test_wanted_and_refused_both_survive(self):
        """The case that made a blanket "negation -> drop material" rule wrong.

        "मुझे सोने की अंगूठी चाहिए, हीरे की नहीं" -- wants gold, refuses
        diamond. Deleting the material here would delete a correct answer.
        """
        out = _sanitize_llm_entities(
            {"material_type": "gold", "excluded_material": "diamond"}
        )
        self.assertEqual(out["material_type"], "gold")
        self.assertEqual(out["excluded_material"], "diamond")

    def test_a_metal_cannot_be_both_wanted_and_refused(self):
        out = _sanitize_llm_entities(
            {"material_type": "gold", "excluded_material": "gold"}
        )
        self.assertIsNone(out["material_type"])
        self.assertEqual(out["excluded_material"], "gold")

    def test_absent_by_default(self):
        self.assertIsNone(_sanitize_llm_entities({})["excluded_material"])

    def test_survives_the_merge_whitelist(self):
        """merge_search_entities is the choke point that once swallowed budget."""
        merged = merge_search_entities(
            {"category": "ring"}, {"excluded_material": "gold"}, "koi bhi"
        )
        self.assertEqual(merged.get("excluded_material"), "gold")


class PearlTests(unittest.TestCase):
    """D5b -- pearl was missing from the material enum, so the model said
    "gemstone" and the funnel accepted an order Clara cannot fulfil."""

    def test_pearl_is_an_unsupported_material(self):
        self.assertIn("pearl", _CLARA_UNSUPPORTED_MATERIALS)

    def test_pearl_survives_sanitisation(self):
        """It must NOT be scrubbed to null -- the unsupported-material notice
        can only fire on a value that reaches the caller."""
        out = _sanitize_llm_entities({"material_type": "pearl"})
        self.assertEqual(out["material_type"], "pearl")

    def test_supported_materials_unchanged(self):
        for material in ("gold", "diamond", "gemstone", "silver", "platinum"):
            self.assertEqual(
                _sanitize_llm_entities({"material_type": material})["material_type"],
                material,
            )


class LatinPriceDirectionTests(unittest.TestCase):
    """D2 -- the extractor reads native-script comparatives fine and misses
    romanized ones, returning a bare action="more". This fallback covers
    exactly that gap and never overrides the model."""

    def test_romanized_comparatives(self):
        for text, expected in (
            ("aur premium wale dikhao", "higher"),
            ("show me more premium ones", "higher"),
            ("aur mehnga dikhao", "higher"),
            ("something more expensive", "higher"),
            ("thoda sasta dikhao", "lower"),
            ("show me cheaper ones", "lower"),
            ("anything more affordable", "lower"),
        ):
            self.assertEqual(_latin_price_direction(text), expected, text)

    def test_plain_pagination_is_not_a_direction(self):
        for text in ("aur dikhao", "show more", "next", "kuch aur", "more options"):
            self.assertIsNone(_latin_price_direction(text), text)

    def test_native_script_abstains_so_the_llm_decides(self):
        for text in ("और महंगे दिखाओ", "થોડું સસ્તું બતાવો", "இன்னும் விலை அதிகம்"):
            self.assertIsNone(_latin_price_direction(text), text)

    def test_a_stated_number_is_a_budget_not_a_nudge(self):
        """Otherwise the band would be shifted twice for "under 30k premium"."""
        self.assertIsNone(_latin_price_direction("premium under 30000"))

    def test_contradictory_wording_abstains(self):
        self.assertIsNone(_latin_price_direction("cheaper or more premium, anything"))


class PaginationGateTests(unittest.TestCase):
    """D2 (second half) -- "show me the second one" came back as
    {action:"more", product_reference:2} and the pagination gate answered
    "You have seen all 2 results!" while the LLM had already resolved which
    piece was meant."""

    SHOWN = [{"title": "Ring A"}, {"title": "Ring B"}]

    def _gate(self, entities, shown=None):
        data = {
            "classified_category": "product_search",
            "user_profile": {
                "last_search_filters": {"category": "ring"},
                "last_search_products": self.SHOWN if shown is None else shown,
            },
            "llm_extracted_entities": entities,
        }
        return product_search_agent_v3._is_show_more_request("show me the second one", data)

    def test_a_resolved_reference_is_not_pagination(self):
        self.assertFalse(self._gate({"action": "more", "product_reference": 2}))

    def test_an_out_of_range_reference_still_paginates(self):
        """A stale index must not strand a genuine "aur dikhao"."""
        self.assertTrue(self._gate({"action": "more", "product_reference": 9}))

    def test_plain_more_still_paginates(self):
        self.assertTrue(self._gate({"action": "more"}))

    def test_price_direction_is_not_pagination(self):
        self.assertFalse(self._gate({"action": "more", "price_direction": "higher"}))


class PendingBandShiftTests(unittest.TestCase):
    """D1 -- "show me cheaper ones" during the confirmation card. There is no
    last_search_filters yet, so the recap's own band is the anchor."""

    def test_lower_becomes_a_ceiling(self):
        out = product_search_agent_v3._shift_pending_band(
            {"category": "ring", "max_price": 50000}, "lower"
        )
        self.assertIsNone(out["min_price"])
        self.assertLess(out["max_price"], 50000)
        self.assertEqual(out["category"], "ring")

    def test_higher_becomes_a_floor(self):
        out = product_search_agent_v3._shift_pending_band(
            {"category": "ring", "max_price": 50000}, "higher"
        )
        self.assertGreater(out["min_price"], 50000)
        self.assertIsNone(out["max_price"])

    def test_no_band_to_anchor_on_is_left_alone(self):
        out = product_search_agent_v3._shift_pending_band({"category": "ring"}, "lower")
        self.assertEqual(out, {"category": "ring"})


class StoreLocationTests(unittest.TestCase):
    """D6 / D8 -- the locator read a Latin-only city list and nothing else, and
    never rendered the storeHours every record carries."""

    STORE = {
        "name": "Maninagar - Ahmedabad",
        "address": {
            "line1": "Silverlake Complex",
            "city": {"name": "Ahmedabad"},
            "state": {"name": "Gujarat"},
            "pincode": "380008",
        },
        "storeHours": {
            day: {"from": "10:30", "to": "21:00", "status": "open"}
            for day in ad_flow_agent._DAY_ORDER
        },
    }

    def test_state_is_read_from_the_record(self):
        self.assertEqual(ad_flow_agent._store_state(self.STORE), "Gujarat")

    def test_state_missing_is_empty_not_an_error(self):
        self.assertEqual(ad_flow_agent._store_state({"address": {}}), "")
        self.assertEqual(ad_flow_agent._store_state({}), "")

    def test_hours_render_in_12_hour_form(self):
        line = ad_flow_agent._store_hours_line(self.STORE)
        self.assertIn("10:30 am", line)
        self.assertIn("9 pm", line)
        self.assertIn("all days", line)

    def test_hours_absent_renders_nothing(self):
        self.assertEqual(ad_flow_agent._store_hours_line({}), "")
        self.assertEqual(
            ad_flow_agent._store_hours_line({"storeHours": "not a dict"}), ""
        )

    def test_closed_days_are_skipped(self):
        store = {
            "storeHours": {
                "monday": {"from": "10:00", "to": "20:00", "status": "closed"},
                "tuesday": {"from": "10:00", "to": "20:00", "status": "open"},
            }
        }
        self.assertIn("10 am - 8 pm", ad_flow_agent._store_hours_line(store))

    def test_unparseable_times_do_not_crash(self):
        store = {"storeHours": {"monday": {"from": "??", "to": "", "status": "open"}}}
        self.assertEqual(ad_flow_agent._store_hours_line(store), "")

    def test_the_card_shows_hours(self):
        text = ad_flow_agent._build_store_text(self.STORE)
        self.assertIn("10:30 am", text)
        self.assertIn("Ahmedabad", text)


class StoreCardTests(unittest.TestCase):
    def test_a_store_without_hours_still_renders(self):
        store = {"name": "X", "address": {"line1": "Y", "city": {"name": "Z"}}}
        text = ad_flow_agent._build_store_text(store)
        self.assertIn("X", text)
        self.assertNotIn("None", text)


if __name__ == "__main__":
    unittest.main()


class WizardUnsupportedMaterialTests(unittest.TestCase):
    """D5a -- answering the MATERIAL question with silver/platinum/pearl was
    silently ignored: the funnel re-asked the same question with no
    explanation, and "pearl" was accepted outright and advanced to budget.

    start_wizard had the notice; advance_wizard never got one.
    """

    def _answer(self, text, material):
        from kisna_chatbot.processors.shopping_wizard import advance_wizard

        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_step": "material",
            "shopping_wizard_data": {"category": "ring", "gender": "women"},
        }
        status, responses = advance_wizard(
            profile,
            {"text": {"body": text}},
            text=text,
            llm_entities={"material_type": material},
        )
        blob = " ".join(r.get("text", "") for r in (responses or []))
        return status, blob, profile

    def test_unsupported_metal_says_why_and_re_asks(self):
        for text, material in (
            ("silver", "silver"),
            ("platinum", "platinum"),
            ("pearl", "pearl"),
            ("चांदी की", "silver"),
            ("பிளாட்டினம்", "platinum"),
        ):
            status, blob, profile = self._answer(text, material)
            self.assertEqual(status, "reask", text)
            self.assertIn("don't carry", blob, text)
            self.assertIn("What type of", blob, text)
            # and it must not have been accepted as the answer
            self.assertIsNone(
                profile["shopping_wizard_data"].get("material_type"), text
            )
            self.assertEqual(profile["shopping_wizard_step"], "material", text)

    def test_a_supported_metal_advances_silently(self):
        for text, material in (("gold", "gold"), ("हीरे की", "diamond")):
            status, blob, profile = self._answer(text, material)
            self.assertEqual(status, "prompt", text)
            self.assertNotIn("don't carry", blob, text)
            self.assertEqual(
                profile["shopping_wizard_data"].get("material_type"), material, text
            )


class GeneralAgentModelRoutingTests(unittest.TestCase):
    """D10 -- long FAQ answers are GENERATED by the general agent, not mirrored
    by reply_composer, so the AI_MODEL_COMPOSE_WEAK routing never reached them.
    The default model scored 0/3 in Tamil and emitted Chinese inside Malayalam
    and Bengali answers. Same language set as the composer, one resolver."""

    def test_low_resource_scripts_are_routed_away(self):
        from kisna_chatbot.ai.config import resolve_compose_model

        for lang in ("ta", "te", "bn", "pa", "kn", "ml", "gu", "mr"):
            self.assertEqual(resolve_compose_model(lang), "gpt-5.6-luna", lang)

    def test_english_hindi_and_romanized_keep_the_default(self):
        """English measured BETTER on the default model (3.0 vs 2.5), Hindi too
        close to justify the extra latency, and romanized text is not the
        problem this solves."""
        from kisna_chatbot.ai.config import resolve_compose_model

        for lang in ("en", "hi", "ta-Latn", "hi-Latn", "gu-Latn", "", None):
            self.assertIsNone(resolve_compose_model(lang), repr(lang))

    def test_the_general_agent_accepts_a_language(self):
        """Guards the plumbing: the model choice is useless if language never
        reaches run_openai_general_agent."""
        import inspect

        from kisna_chatbot.ai import run_general_agent
        from kisna_chatbot.ai.openai_responses import run_openai_general_agent

        for fn in (run_general_agent, run_openai_general_agent):
            self.assertIn("language", inspect.signature(fn).parameters, fn.__name__)

    def test_web_search_stays_gated_on_the_configured_model(self):
        """Routing a language to another model must NOT silently switch web
        search on and change what the answer is built from."""
        import inspect

        from kisna_chatbot.ai import openai_responses

        src = inspect.getsource(openai_responses.run_openai_general_agent)
        self.assertIn('"gpt-4o-mini" not in configured_model.lower()', src)


class UrduSupportTests(unittest.TestCase):
    """Urdu is the one supported language NOT in an Indic script, so every
    script rule had to learn about Arabic before it could be routed anywhere.

    The trap these pin: _FOREIGN_SCRIPT_RANGES lists Arabic as a script a reply
    must NEVER contain -- true for every Indic language, and exactly wrong for
    Urdu. Routing Urdu without this would make the composer flag its own
    correct Urdu as entirely contaminated and fall back to English.
    """

    URDU = "ہم 7 دن کی واپسی کی پالیسی پیش کرتے ہیں۔ پروڈکٹ غیر استعمال شدہ ہونا چاہیے۔"
    HINDI = "हम 7 दिन की वापसी नीति प्रदान करते हैं।"

    def test_urdu_script_is_not_foreign_to_urdu(self):
        from kisna_chatbot.utils.reply_composer import _script_violations

        self.assertEqual(_script_violations("ur", self.URDU), [])

    def test_arabic_is_still_foreign_to_every_indic_language(self):
        """The guard must be narrowed for Urdu only, not removed."""
        from kisna_chatbot.utils.reply_composer import _script_violations

        for lang in ("hi", "ta", "gu", "bn", "pa", "kn", "ml", "mr", "te"):
            self.assertTrue(_script_violations(lang, self.URDU), lang)

    def test_devanagari_is_foreign_to_urdu(self):
        from kisna_chatbot.utils.reply_composer import _script_violations

        self.assertTrue(_script_violations("ur", self.HINDI))

    def test_urdu_requires_native_script_but_roman_urdu_does_not(self):
        from kisna_chatbot.utils.reply_composer import _needs_native_script

        self.assertTrue(_needs_native_script("ur"))
        self.assertFalse(_needs_native_script("ur-Latn"))

    def test_urdu_has_a_label_so_it_is_never_nearest_matched(self):
        """An unlisted language falls back to the nearest listed one -- that is
        how a Gurmukhi message once got answered in Gujarati."""
        from kisna_chatbot.utils.reply_composer import _LANGUAGE_LABELS, _language_label

        self.assertIn("ur", _LANGUAGE_LABELS)
        self.assertIn("Urdu", _language_label("ur"))
        self.assertIn("romanized", _language_label("ur-Latn"))

    def test_routing(self):
        from kisna_chatbot.ai.config import resolve_compose_model

        self.assertEqual(resolve_compose_model("ur"), "gpt-5.6-luna")
        self.assertIsNone(resolve_compose_model("ur-Latn"))

    def test_the_script_typed_overrides_a_wrong_label(self):
        from kisna_chatbot.processors.classifier import resolve_reply_language

        # Nastaliq mislabelled as Hindi is corrected by what was actually typed
        self.assertEqual(resolve_reply_language("hi", self.URDU), "ur")
        # ...and the reverse
        self.assertEqual(resolve_reply_language("ur", self.HINDI), "hi")

    def test_latin_script_is_never_answered_in_nastaliq(self):
        from kisna_chatbot.processors.classifier import resolve_reply_language

        self.assertEqual(
            resolve_reply_language("ur", "mujhe angoothi chahiye"), "ur-Latn"
        )
        self.assertEqual(resolve_reply_language("ur", "I want a ring"), "en")


class ExcludedMaterialFilterTests(unittest.TestCase):
    """The refusal now filters results, and is NOT part of the relaxation
    ladder: relaxing "I don't want gold" would put gold back on screen."""

    PRODUCTS = [
        {"title": "A", "materialType": "Gold"},
        {"title": "B", "materialType": "Diamond"},
        {"title": "C", "materialType": "gold"},
        {"title": "D"},  # material not stated
    ]

    def _kept(self, excluded):
        from kisna_chatbot.processors.entity_extractor import drop_excluded_material

        return [p["title"] for p in drop_excluded_material(self.PRODUCTS, excluded)]

    def test_the_refused_metal_is_removed_case_insensitively(self):
        self.assertEqual(self._kept("gold"), ["B", "D"])

    def test_a_record_with_no_material_is_kept(self):
        """Silence is not evidence that it IS the refused metal."""
        self.assertIn("D", self._kept("gold"))
        self.assertIn("D", self._kept("diamond"))

    def test_no_exclusion_changes_nothing(self):
        self.assertEqual(self._kept(None), ["A", "B", "C", "D"])
        self.assertEqual(self._kept(""), ["A", "B", "C", "D"])

    def test_exclusion_is_not_in_the_relaxation_ladder(self):
        """The guard that keeps a refusal from being traded away for results."""
        from kisna_chatbot.processors.entity_extractor import (
            _CLIENT_FILTER_KEYS,
            _EXTRA_RELAXATION_ORDER,
        )

        self.assertNotIn("excluded_material", _EXTRA_RELAXATION_ORDER)
        self.assertNotIn("excluded_material", _CLIENT_FILTER_KEYS)

    def test_it_survives_every_return_path_of_the_extras_filter(self):
        from kisna_chatbot.processors.entity_extractor import (
            filter_products_by_extracted_extras,
        )

        # karat=9KT matches nothing here, so the ladder relaxes and would
        # normally hand back the full original list -- gold included.
        kept, _note = filter_products_by_extracted_extras(
            self.PRODUCTS, {"excluded_material": "gold", "karat": "9KT"}
        )
        self.assertTrue(all(p["title"] != "A" for p in kept))
        self.assertTrue(all(p["title"] != "C" for p in kept))


class WizardRespectsRefusalTests(unittest.TestCase):
    """Offering a metal the customer just ruled out reads as not listening."""

    def _options(self, excluded):
        from kisna_chatbot.processors.shopping_wizard import build_step_prompt

        collected = {"category": "ring", "gender": "women"}
        if excluded:
            collected["excluded_material"] = excluded
        return [o["title"] for o in build_step_prompt("material", collected)["options"]]

    def test_the_refused_metal_is_not_offered(self):
        self.assertEqual(self._options("gold"), ["Diamond", "Gemstone"])
        self.assertEqual(self._options("diamond"), ["Gold", "Gemstone"])
        self.assertEqual(self._options("gemstone"), ["Gold", "Diamond"])

    def test_all_three_offered_when_nothing_was_refused(self):
        self.assertEqual(self._options(None), ["Gold", "Diamond", "Gemstone"])

    def test_the_refusal_is_seeded_and_carried(self):
        from kisna_chatbot.processors.shopping_wizard import (
            WIZARD_CARRYOVER_KEYS,
            seed_wizard_from_entities,
        )

        seeded = seed_wizard_from_entities(
            {"category": "ring", "excluded_material": "gold"}
        )
        self.assertEqual(seeded.get("excluded_material"), "gold")
        self.assertIn("excluded_material", WIZARD_CARRYOVER_KEYS)

    def test_it_is_a_constraint_not_an_answer(self):
        """It must never fill the material slot or let the funnel skip it."""
        from kisna_chatbot.processors.shopping_wizard import get_next_step

        collected = {"category": "ring", "gender": "women",
                     "excluded_material": "gold"}
        self.assertEqual(get_next_step(collected), "material")


class ComposerEmphasisTests(unittest.TestCase):
    """A rewrite must not invent emphasis the source never had.

    The wizard's material question has no asterisks, yet the rewrite bolded the
    category in Hindi, Kannada and Marathi and not in English, Tamil or
    Gujarati -- the same prompt reading differently to different customers.
    """

    def _match(self, source, rewritten):
        from kisna_chatbot.utils.reply_composer import _match_source_emphasis

        return _match_source_emphasis(source, rewritten)

    def test_invented_emphasis_is_stripped(self):
        self.assertEqual(
            self._match("What type of rings are you interested in?",
                        "आप किस प्रकार की *अंगूठियों* में रुचि रखते हैं?"),
            "आप किस प्रकार की अंगूठियों में रुचि रखते हैं?",
        )

    def test_deliberate_emphasis_survives(self):
        source = "What's your budget? (or say *no specific budget*)"
        rewritten = "आपका बजट क्या है? (या कहें *कोई विशेष बजट नहीं*)"
        self.assertEqual(self._match(source, rewritten), rewritten)

    def test_a_clean_rewrite_is_untouched(self):
        self.assertEqual(self._match("plain source", "सादा अनुवाद"), "सादा अनुवाद")

    def test_empty_inputs_do_not_crash(self):
        self.assertEqual(self._match("", ""), "")
        self.assertEqual(self._match("a", ""), "")


class SecondaryIntentTests(unittest.TestCase):
    """A second request in the same message is no longer dropped in silence."""

    def _parse(self, primary, secondary):
        import json

        from kisna_chatbot.processors.classifier import _parse_classifier_json

        return _parse_classifier_json(
            json.dumps({"intent": primary, "confidence": 0.9,
                        "language": "en", "secondary_intent": secondary,
                        "entities": {}})
        )["secondary_intent"]

    def test_the_supported_secondaries_survive(self):
        for value in ("offers", "gold_rate", "store_info", "general"):
            self.assertEqual(self._parse("product_search", value), value)

    def test_a_flow_starting_intent_is_refused(self):
        """order_tracking needs an id, returns needs a reason, complaint needs
        a conversation -- none can be bolted onto another turn."""
        for value in ("order_tracking", "returns_refund", "complaint",
                      "human_handoff", "video_call", "callback"):
            self.assertIsNone(self._parse("product_search", value), value)

    def test_naming_the_same_intent_twice_is_not_two_requests(self):
        self.assertIsNone(self._parse("offers", "offers"))

    def test_absent_by_default(self):
        self.assertIsNone(self._parse("product_search", None))
        self.assertIsNone(self._parse("product_search", ""))

    def test_the_appender_leaves_a_single_intent_turn_alone(self):
        from kisna_chatbot.processors.secondary_intent import append_secondary_answer

        original = [{"type": "text", "text": "Here are some rings"}]
        data = {"bot_response": list(original), "secondary_intent": None}
        asyncio.run(append_secondary_answer(data))
        self.assertEqual(data["bot_response"], original)

    def test_the_appender_never_invents_a_reply(self):
        """It runs after the primary; with no primary there is nothing to
        add to, and inventing one would answer the wrong half."""
        from kisna_chatbot.processors.secondary_intent import (
            append_secondary_answer,
        )

        data = {"secondary_intent": "offers"}
        asyncio.run(append_secondary_answer(data))
        self.assertNotIn("bot_response", data)


class NonLatinScriptTests(unittest.TestCase):
    """Seven places encoded "non-Latin means Indic" as a U+0900-U+0D7F range.

    That held while every supported language was Latin or Indic. Urdu is Arabic
    script, so adding it made all seven wrong at once, and severely: an Urdu
    product search was classified as SPAM, the evidence gate deleted the metal
    and audience the model had read correctly, and every composed Urdu reply
    was rejected as an echo and fell back to English.

    These pin the predicate, not the seven call sites -- the point is that the
    NEXT language added cannot recreate this.
    """

    URDU = "خواتین کے لیے سونے کی انگوٹھیاں دکھائیں"
    HINDI = "महिलाओं के लिए सोने की अंगूठियां दिखाओ"

    def test_every_supported_script_counts_as_non_latin(self):
        from kisna_chatbot.utils.script_detect import has_non_latin_letters

        for label, text in (
            ("hi/mr", "अंगूठी"), ("bn/as", "আংটি"), ("pa", "ਮੁੰਦਰੀ"),
            ("gu", "વીંટી"), ("or", "ଅଙ୍ଗୁଠି"), ("ta", "மோதிரம்"),
            ("te", "ఉంగరం"), ("kn", "ಉಂಗುರ"), ("ml", "മോതിരം"),
            ("ur", "انگوٹھی"),
        ):
            self.assertTrue(has_non_latin_letters(text), label)

    def test_latin_digits_and_emoji_are_not(self):
        from kisna_chatbot.utils.script_detect import has_non_latin_letters

        for text in ("show me gold rings", "50000", "😍", "", "?!.", "15-35k"):
            self.assertFalse(has_non_latin_letters(text), repr(text))

    def test_real_language_in_any_script_is_not_gibberish(self):
        from kisna_chatbot.processors.entity_extractor import is_unrecognizable_input

        for label, text in (("urdu", self.URDU), ("hindi", self.HINDI),
                            ("english", "show me gold rings")):
            self.assertFalse(is_unrecognizable_input(text), label)

    def test_the_evidence_gate_treats_urdu_like_hindi(self):
        """It stripped material_type and gender from Urdu while keeping them
        for Hindi -- the Latin regex overriding what the model read."""
        from kisna_chatbot.processors.entity_extractor import apply_llm_evidence_gate

        llm = {"category": "ring", "material_type": "gold", "gender": "women"}
        for text in (self.URDU, self.HINDI):
            out = apply_llm_evidence_gate(text, dict(llm))
            self.assertEqual(out.get("material_type"), "gold", text[:20])
            self.assertEqual(out.get("gender"), "women", text[:20])

    def test_a_reply_in_its_own_script_is_not_an_echo(self):
        from kisna_chatbot.utils.reply_composer import (
            _is_native_script_echo,
            _is_unusable_rewrite,
        )

        for lang, text in (("ur", "ہم 7 دن کی واپسی کی پالیسی پیش کرتے ہیں۔"),
                           ("hi", "हम 7 दिन की वापसी नीति देते हैं।"),
                           ("ta", "நாங்கள் 7 நாள் கொள்கை வழங்குகிறோம்.")):
            self.assertFalse(_is_native_script_echo(lang, text), lang)
            self.assertFalse(_is_unusable_rewrite(lang, text), lang)

    def test_a_reply_in_the_wrong_script_is_still_an_echo(self):
        """Narrowing the check must not disable it."""
        from kisna_chatbot.utils.reply_composer import _is_native_script_echo

        self.assertTrue(_is_native_script_echo("ur", "हम 7 दिन की वापसी नीति देते हैं।"))
        self.assertTrue(_is_native_script_echo("ta", "ہم واپسی کی پالیسی پیش کرتے ہیں۔"))
        self.assertTrue(_is_native_script_echo("hi", "We offer a 7-day return window."))


class LocalisedCtaTests(unittest.TestCase):
    """cta_url carries prose in "text" just like a plain message, but was
    skipped by the localiser -- so an Urdu customer was told "Click below to
    track your order" in English."""

    def test_a_tagged_cta_is_localised(self):
        from kisna_chatbot.utils import reply_composer

        item = {"type": "cta_url", "text": "Click below to track your order.",
                "display_text": "Track Your Order", "url": "https://x",
                "_compose": "order_tracking_cta"}
        data = {"bot_response": [item], "user_profile": {"language": "hi"},
                "messages": {}}

        async def fake_compose(template_key, text, **kw):
            return "TRANSLATED"

        with mock.patch.object(reply_composer, "compose", fake_compose):
            asyncio.run(reply_composer.localize_bot_responses(data))
        self.assertEqual(item["text"], "TRANSLATED")
        # Button labels stay English: WhatsApp caps them at 20 characters.
        self.assertEqual(item["display_text"], "Track Your Order")

    def test_the_tracking_cta_is_tagged(self):
        from kisna_chatbot.processors.order_tracking_agent import (
            _build_generic_tracking_response,
        )

        responses = _build_generic_tracking_response("https://kisna.com/track")
        self.assertEqual(responses[0].get("_compose"), "order_tracking_cta")

    def test_support_messages_are_tagged(self):
        """Both handoff branches reached non-English customers in English."""
        import inspect

        from kisna_chatbot.processors import support_handler

        src = inspect.getsource(support_handler)
        self.assertIn('"_compose": "support_offline"', src)
        self.assertIn('"_compose": "support_handoff"', src)


class ShownProductQuestionTests(unittest.TestCase):
    """"do you have size 14?" after a product list RESET the conversation.

    The classifier sets product_question for most phrasings but missed that
    one, and a size with no category starts a fresh wizard — so the customer
    was answered with "Hi! What are you looking for today?" and the whole
    search was gone. Every other phrasing was answered correctly, which is
    exactly why this cannot rest on the flag alone.
    """

    def _asks(self, entities, shown=1):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _asks_about_shown_products,
        )

        return _asks_about_shown_products({
            "llm_extracted_entities": entities,
            "user_profile": {"last_search_products": [{"title": "A"}] * shown},
        })

    def test_an_attribute_only_message_is_a_question(self):
        for entities in ({"size": 14}, {"karat": "18KT"}, {"metal_colour": "rose"}):
            self.assertTrue(self._asks(entities), entities)

    def test_naming_a_product_is_still_a_new_search(self):
        """"size 14 rings dikhao" is a search, not a question."""
        for entities in (
            {"size": 14, "category": "ring"},
            {"size": 14, "material_type": "gold"},
            {"size": 14, "collection": "evil eye"},
            {"size": 14, "title": "Flossie"},
        ):
            self.assertFalse(self._asks(entities), entities)

    def test_a_budget_is_a_refinement_not_a_question(self):
        self.assertFalse(self._asks({"size": 14, "max_price": 50000}))
        self.assertFalse(self._asks({"size": 14, "min_price": 10000}))

    def test_nothing_shown_means_nothing_to_ask_about(self):
        self.assertFalse(self._asks({"size": 14}, shown=0))

    def test_no_attribute_is_not_a_question(self):
        self.assertFalse(self._asks({}))
        self.assertFalse(self._asks({"action": "more"}))


class FlowAndCtaLocalisationTests(unittest.TestCase):
    """cta_url and flow carry prose in "text" exactly as a plain message does,
    and the localiser only ever looked at type == "text" — so the complaint,
    callback and video-call prompts reached every customer in English."""

    def _localise(self, item):
        from kisna_chatbot.utils import reply_composer

        data = {"bot_response": [item], "user_profile": {"language": "hi"},
                "messages": {}}

        async def fake_compose(template_key, text, **kw):
            return "TRANSLATED"

        with mock.patch.object(reply_composer, "compose", fake_compose):
            asyncio.run(reply_composer.localize_bot_responses(data))
        return item

    def test_flow_bodies_are_localised(self):
        item = self._localise({
            "type": "flow", "flow": "callback_request",
            "text": "Please share your details for a callback.",
            "_compose": "callback_flow_prompt",
        })
        self.assertEqual(item["text"], "TRANSLATED")

    def test_cta_bodies_are_localised(self):
        item = self._localise({
            "type": "cta_url", "text": "Click below.", "display_text": "Track",
            "url": "https://x", "_compose": "order_tracking_cta",
        })
        self.assertEqual(item["text"], "TRANSLATED")
        self.assertEqual(item["display_text"], "Track")

    def test_the_three_flow_prompts_are_tagged(self):
        from kisna_chatbot.processors import service_list

        for builder in (
            service_list.build_complaint_flow_bot_response,
            service_list.build_callback_flow_bot_response,
            service_list.build_video_call_flow_bot_response,
        ):
            self.assertIn("_compose", builder(), builder.__name__)

    def test_the_cta_sender_tolerates_either_key(self):
        """A producer passed "body" instead of "text"; a KeyError there takes
        down the whole outbound message."""
        import inspect

        from kisna_chatbot.whatsapp_functions.cta import send_cta

        # Look at the assignment itself, not the comment above it that
        # quotes the old form.
        body_lines = [
            ln.strip()
            for ln in inspect.getsource(send_cta).splitlines()
            if '"body":' in ln and not ln.strip().startswith('#')
        ]
        self.assertTrue(body_lines)
        for ln in body_lines:
            self.assertIn('.get(', ln)
