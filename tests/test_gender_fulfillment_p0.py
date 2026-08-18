"""P0 gender/fulfillment merge, sanitize, evidence, wizard NL — light imports only."""

import os
import unittest

# Satisfy env_load.validate_env before any kisna import (avoids circular logger import).
for _k, _v in {
    "MONGO_URI": "mongodb://localhost:27017",
    "GUPSHUP_APP_ID": "test",
    "GUPSHUP_TOKEN": "test",
    "GUPSHUP_APP_NAME": "test",
    "GUPSHUP_API_KEY": "test",
    "GUPSHUP_WEBHOOK_SECRET": "test",
    "JWT_SECRET_KEY": "test",
    "SYSTEM_API_KEY": "test",
    "KISNA_PRODUCT_API": "http://localhost/products",
    "KISNA_OFFERS_API": "http://localhost/offers",
    "KISNA_STORE_API": "http://localhost/stores",
    "KISNA_VTIGER_BASE": "http://localhost/vtiger",
    "KISNA_VTIGER_TOKEN": "test",
    "KB_ENABLED": "false",
}.items():
    os.environ.setdefault(_k, _v)

from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    _NEVER_INHERIT_FIELDS,
    _gender_evidenced,
    apply_llm_evidence_gate,
    is_ambiguous_audience,
    merge_search_entities,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    _gender_from_text,
    advance_wizard,
    filter_wizard_carryover,
    get_next_step,
    seed_wizard_from_entities,
    start_wizard,
)
from kisna_chatbot.prompts.classifier_kisna import (  # noqa: E402
    kisna_classifier_intent as kisna_classifier,  # noqa: F401  (routing assertions)
    kisna_entity_extractor,
)


class GenderFulfillmentMergeTests(unittest.TestCase):
    def test_sticky_gender_and_fulfillment_on_budget_refinement(self):
        prior = {
            "category": "ring",
            "material_type": "gold",
            "gender": "women",
            "fulfillment": "ready",
            "max_price": 50000,
        }
        new = {
            "category": None,
            "material_type": None,
            "gender": None,
            "fulfillment": None,
            "min_price": None,
            "max_price": 40000,
            "title": None,
        }
        merged = merge_search_entities(prior, new, "I want them under 40000")
        self.assertEqual(merged["category"], "ring")
        self.assertEqual(merged["material_type"], "gold")
        self.assertEqual(merged["gender"], "women")
        self.assertEqual(merged["fulfillment"], "ready")
        self.assertEqual(merged["max_price"], 40000)

    def test_gender_override_keeps_category(self):
        prior = {
            "category": "ring",
            "material_type": "gold",
            "gender": "women",
            "fulfillment": "ready",
            "max_price": 30000,
        }
        new = {
            "category": None,
            "material_type": None,
            "gender": "men",
            "fulfillment": None,
            "min_price": None,
            "max_price": None,
            "title": None,
        }
        for query in ("I want it for men", "for men"):
            merged = merge_search_entities(prior, new, query)
            self.assertEqual(merged["gender"], "men", query)
            self.assertEqual(merged["category"], "ring", query)
            self.assertEqual(merged["material_type"], "gold", query)
            self.assertEqual(merged["fulfillment"], "ready", query)
            self.assertEqual(merged["max_price"], 30000, query)

    def test_fulfillment_override_keeps_category(self):
        prior = {
            "category": "necklace",
            "gender": "women",
            "fulfillment": "ready",
        }
        new = {
            "category": None,
            "gender": None,
            "fulfillment": "mto",
            "title": None,
            "material_type": None,
        }
        merged = merge_search_entities(prior, new, "made to order")
        self.assertEqual(merged["fulfillment"], "mto")
        self.assertEqual(merged["category"], "necklace")
        self.assertEqual(merged["gender"], "women")

    def test_gender_not_in_never_inherit(self):
        self.assertNotIn("gender", _NEVER_INHERIT_FIELDS)
        self.assertNotIn("fulfillment", _NEVER_INHERIT_FIELDS)


class GenderFulfillmentEvidenceTests(unittest.TestCase):
    def test_strips_invented_fulfillment(self):
        gated = apply_llm_evidence_gate(
            "gold rings under 20000",
            {"category": "ring", "material_type": "gold", "fulfillment": "ready"},
        )
        self.assertIsNone(gated["fulfillment"])

    def test_keeps_ready_when_evidenced(self):
        gated = apply_llm_evidence_gate(
            "ready to ship diamond rings",
            {"category": "ring", "fulfillment": "ready"},
        )
        self.assertEqual(gated["fulfillment"], "ready")

    def test_strips_invented_gender(self):
        gated = apply_llm_evidence_gate(
            "gold rings",
            {"category": "ring", "gender": "women"},
        )
        self.assertIsNone(gated["gender"])

    def test_keeps_gender_for_her(self):
        gated = apply_llm_evidence_gate(
            "for her gold rings",
            {"category": "ring", "gender": "women"},
        )
        self.assertEqual(gated["gender"], "women")

    def test_gender_evidenced_mom_dad(self):
        self.assertTrue(_gender_evidenced("for mom", "women"))
        self.assertTrue(_gender_evidenced("gold ring for mother", "women"))
        self.assertTrue(_gender_evidenced("for dad", "men"))
        self.assertTrue(_gender_evidenced("bracelet for father", "men"))
        self.assertTrue(_gender_evidenced("gift for sister", "women"))
        self.assertTrue(_gender_evidenced("for brother", "men"))

    def test_gender_not_evidenced_for_ambiguous_audience(self):
        for query in (
            "for parents",
            "necklace for parents",
            "gift for a friend",
            "for family",
            "for a couple",
        ):
            self.assertFalse(_gender_evidenced(query, "women"), query)
            self.assertFalse(_gender_evidenced(query, "men"), query)

    def test_keeps_gender_for_mom(self):
        gated = apply_llm_evidence_gate(
            "ring for mom",
            {"category": "ring", "gender": "women"},
        )
        self.assertEqual(gated["gender"], "women")

    def test_keeps_gender_for_dad(self):
        gated = apply_llm_evidence_gate(
            "bracelet for dad",
            {"category": "bracelet", "gender": "men"},
        )
        self.assertEqual(gated["gender"], "men")

    def test_strips_guessed_gender_for_parents(self):
        gated = apply_llm_evidence_gate(
            "gift for parents",
            {"category": "necklace", "gender": "women"},
        )
        self.assertIsNone(gated["gender"])

    def test_strips_guessed_gender_for_friend(self):
        gated = apply_llm_evidence_gate(
            "gift for a friend",
            {"occasion": "gift", "gender": "men"},
        )
        self.assertIsNone(gated["gender"])

    def test_ambiguous_audience_helper(self):
        self.assertTrue(is_ambiguous_audience("I need a ring for my parents"))
        self.assertTrue(is_ambiguous_audience("gift for a friend"))
        self.assertFalse(is_ambiguous_audience("ring for mom"))
        self.assertFalse(is_ambiguous_audience("couple rings for her"))

    def test_parents_ask_skips_sticky_gender_in_wizard(self):
        """Prior Female carryover must not skip 'Who is it for?' for parents."""
        query = "I need a ring for my parents"
        carryover = {"gender": "women", "material_type": "gold"}
        gated = filter_wizard_carryover(
            carryover,
            {"category": "ring"},
            {"category": "ring", "gender": "women"},
            query=query,
        )
        self.assertNotIn("gender", gated)
        seeded = seed_wizard_from_entities(
            {"category": "ring", "gender": "women"},
            query=query,
        )
        self.assertEqual(seeded.get("category"), "ring")
        self.assertIsNone(seeded.get("gender"))
        self.assertEqual(get_next_step(seeded), "gender")

    def test_wizard_gender_from_relationship_text(self):
        self.assertEqual(_gender_from_text("mom"), "women")
        self.assertEqual(_gender_from_text("for mom"), "women")
        self.assertEqual(_gender_from_text("dad"), "men")
        self.assertEqual(_gender_from_text("for dad"), "men")
        self.assertEqual(_gender_from_text("sister"), "women")
        self.assertIsNone(_gender_from_text("parents"))
        self.assertIsNone(_gender_from_text("friend"))


class GenderSanitizeAndPromptTests(unittest.TestCase):
    def test_gender_sanitizer_aliases(self):
        from kisna_chatbot.processors.classifier import _sanitize_llm_entities

        self.assertEqual(
            _sanitize_llm_entities({"gender": "female"})["gender"], "women"
        )
        self.assertEqual(_sanitize_llm_entities({"gender": "male"})["gender"], "men")
        self.assertEqual(
            _sanitize_llm_entities({"gender": "ladies"})["gender"], "women"
        )
        self.assertEqual(_sanitize_llm_entities({"gender": "gents"})["gender"], "men")
        self.assertEqual(_sanitize_llm_entities({"gender": "kid"})["gender"], "kids")
        self.assertIsNone(_sanitize_llm_entities({"gender": "unisex"})["gender"])

    def test_prompt_null_first_and_override(self):
        # Gender / fulfillment extraction is owned by the extractor alone —
        # the classifier no longer emits either field.
        for assertion in (
            "CURRENT MESSAGE FIRST",
            "I want it for men",
            "fulfillment",
            "gold ring for mom",
            "bracelet for dad",
            "necklace for parents",
            "AMBIGUOUS",
        ):
            with self.subTest(assertion=assertion):
                self.assertIn(assertion, kisna_entity_extractor)
        self.assertIn("never female", kisna_entity_extractor.lower())


class WizardFulfillmentGenderNLTests(unittest.TestCase):
    def test_fulfillment_text_in_stock(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "gold",
                "max_price": 20000,
                "min_price": 0,
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        status, _ = advance_wizard(profile, {}, text="in stock please")
        self.assertEqual(status, "complete")
        self.assertEqual(profile["shopping_wizard_data"]["fulfillment"], "ready")

    def test_mid_wizard_gender_restate_overwrites(self):
        profile = {}
        start_wizard(profile, entities={"category": "ring", "gender": "women"})
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "women")
        status, _ = advance_wizard(profile, {}, text="for men gold")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "men")
        self.assertEqual(profile["shopping_wizard_data"]["material_type"], "gold")


if __name__ == "__main__":
    unittest.main()
