"""KB v2.1: the live GeneralAgent prompt is assembled directly --
wrapper -> KISNA_KNOWLEDGE_BASE_V2 -> live campaigns -> KISNA_VOICE ->
LOCKED VALUES. V1 is no longer a template and must not reach the prompt."""

import os
import unittest
from datetime import date

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
    build_locked_values,
    general_agent_prompt,
)
from kisna_chatbot.prompts.kisna_knowledge_base import (  # noqa: E402
    KISNA_KNOWLEDGE_BASE,
    KISNA_KNOWLEDGE_BASE_V2,
    KISNA_VOICE,
)

_DAY = date(2026, 9, 26)


class KbV21AssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prompt = build_general_agent_prompt(_DAY)

    def test_static_prefix_leads_every_prompt(self) -> None:
        # The large static part is the prefix, so OpenAI prompt caching applies.
        self.assertTrue(self.prompt.startswith(general_agent_prompt))
        self.assertTrue(general_agent_prompt.endswith(KISNA_KNOWLEDGE_BASE_V2))

    def test_order_ends_voice_then_locked_values(self) -> None:
        v2 = self.prompt.index(KISNA_KNOWLEDGE_BASE_V2)
        campaigns = self.prompt.index("# LIVE CAMPAIGNS")
        voice = self.prompt.index(KISNA_VOICE)
        locked = self.prompt.index(build_locked_values())
        self.assertLess(v2, campaigns)
        self.assertLess(campaigns, voice)
        self.assertLess(voice, locked)
        self.assertTrue(self.prompt.rstrip().endswith(build_locked_values().rstrip()))

    def test_v1_kb_is_not_in_the_prompt(self) -> None:
        self.assertNotIn(KISNA_KNOWLEDGE_BASE, self.prompt)

    def test_v2_keeps_grp_section_and_store_count(self) -> None:
        self.assertIn("GOLD RATE PROTECTION PLAN", self.prompt)
        self.assertIn("160+ flagship stores", self.prompt)
        self.assertNotIn("120+ flagship stores", self.prompt)

    def test_every_grp_answer_points_to_the_page(self) -> None:
        # Client-reported gap: "What is GRP?" answered with no pointer to the
        # page. The rule survives; the link itself is carried by the button.
        self.assertIn(
            "Every GRP answer, not just the validity one, must end by pointing the "
            "customer to https://www.kisna.com/pages/gold-rate-protection",
            self.prompt,
        )

    def test_materials_facts(self) -> None:
        self.assertNotIn(
            "The only materials KISNA does NOT sell are silver, platinum, and pearl.",
            self.prompt,
        )
        self.assertIn("sold in select PHYSICAL", self.prompt)
        self.assertIn("is pearl", self.prompt)

    def test_still_forbids_making_charge_percentages(self) -> None:
        self.assertIn("NEVER quote a specific percentage", self.prompt)
        self.assertIn("Never quote a making-charge percentage", self.prompt)


if __name__ == "__main__":
    unittest.main()
