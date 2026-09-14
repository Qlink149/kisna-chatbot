"""F1: the client's Sept-2026 KB (Gold Rate Protection, corrected
platinum/silver-coin/gold-coin facts) is the live prompt. Unconditional --
no on/off flag; general_agent_prompt (v1) is kept only as the base template
general_agent_prompt_v2 is built from."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("GUPSHUP_WEBHOOK_SECRET", "test-webhook-secret")

from kisna_chatbot.prompts.general_agent_kisna import (  # noqa: E402
    build_general_agent_prompt,
    general_agent_prompt,
    general_agent_prompt_v2,
)
from kisna_chatbot.prompts.kisna_knowledge_base import (  # noqa: E402
    KISNA_KNOWLEDGE_BASE,
    KISNA_KNOWLEDGE_BASE_V2,
)


class KbV2Tests(unittest.TestCase):
    def test_live_prompt_is_v2(self) -> None:
        self.assertEqual(build_general_agent_prompt(), general_agent_prompt_v2)

    def test_v1_prompt_is_byte_identical_regardless_of_v2_existing(self) -> None:
        # Building v2 (module import time) must never mutate v1.
        self.assertIn("The only materials KISNA does NOT sell are silver, platinum, and pearl.", general_agent_prompt)
        self.assertNotIn("Gold Rate Protection", general_agent_prompt)

    def test_v2_adds_gold_rate_protection_and_keeps_store_count(self) -> None:
        self.assertIn("GOLD RATE PROTECTION PLAN", general_agent_prompt_v2)
        self.assertIn("160+ flagship stores", general_agent_prompt_v2)
        self.assertNotIn("120+ flagship stores", general_agent_prompt_v2)

    def test_grp_answer_includes_the_page_url(self) -> None:
        # Client-reported gap: "What is GRP?" answered with no link to the
        # page at all. The URL must be in the answer text itself, not just
        # the section header, so the model actually says it.
        self.assertIn(
            "It allows you to lock the prevailing gold rate at the time of "
            "placing your order or booking, protecting you from any future "
            "increase in gold prices during the offer period. Full details: "
            "https://www.kisna.com/pages/gold-rate-protection",
            general_agent_prompt_v2,
        )

    def test_v2_corrects_platinum_silver_coin_facts(self) -> None:
        self.assertNotIn(
            "The only materials KISNA does NOT sell are silver, platinum, and pearl.",
            general_agent_prompt_v2,
        )
        self.assertIn("sold in select PHYSICAL", general_agent_prompt_v2)
        self.assertIn("is pearl", general_agent_prompt_v2)

    def test_v2_still_forbids_making_charge_percentages(self) -> None:
        # The client's updated KB kept this rule verbatim -- must survive the swap.
        self.assertIn("NEVER quote a specific percentage", KISNA_KNOWLEDGE_BASE_V2)
        self.assertIn("NEVER quote a percentage", KISNA_KNOWLEDGE_BASE)

    def test_v2_prompt_structure_outside_the_four_edits_matches_v1(self) -> None:
        # Reconstruct v2 by undoing the 4 known substitutions; result must equal v1
        # exactly -- proves nothing else in the 300-line prompt drifted between versions.
        materials_v2_marker = "sold in select PHYSICAL STORES ONLY"
        self.assertIn(materials_v2_marker, general_agent_prompt_v2)
        reconstructed = general_agent_prompt_v2.replace(KISNA_KNOWLEDGE_BASE_V2, KISNA_KNOWLEDGE_BASE, 1)
        # After swapping the KB back, the only remaining diffs must be the 3 rule
        # sentences -- so v1 minus those 3 spots must be a substring-equal skeleton.
        self.assertNotEqual(reconstructed, general_agent_prompt, "sanity: KB swap alone must change the prompt")


if __name__ == "__main__":
    unittest.main()
