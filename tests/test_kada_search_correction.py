"""Kisna tester, 2026-10-13: "looking for kada" was searched as bracelets, a
bare "90000" after "No, change it" was never applied (no reply), and the
GeneralAgent then promised "I'll search for kadas... Just a moment!" for a
search that never ran.

A. kada is its own catalogue category ("Kadas"), not bracelet.
B. A budget-only correction is applied and the search read back again.
C. A correction nothing could apply re-shows the recap; it never reaches the
   GeneralAgent."""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")

from kisna_chatbot.processors import product_search_agent_v3 as psa  # noqa: E402
from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    CATEGORY_NORMALIZATION_MAP,
    extract_entities,
    normalize_category_for_api,
)
from kisna_chatbot.processors.search_confirmation import (  # noqa: E402
    AWAITING_CORRECTION_KEY,
    build_search_recap,
    set_pending_search,
)

_NO_ENTITIES = {k: None for k in ("category", "material_type", "gender", "min_price", "max_price", "fulfillment")}


class KadaCategoryTests(unittest.TestCase):
    def test_kada_words_are_kada_not_bracelet(self):
        for text in ("looking for kada", "kadas for men", "kadi", "mens gold kada under 90000"):
            with self.subTest(text=text):
                self.assertEqual(extract_entities(text).get("category"), "kada")
        for text in ("bracelet for men", "gold bracelets"):
            with self.subTest(text=text):
                self.assertEqual(extract_entities(text).get("category"), "bracelet")

    def test_catalogue_category_maps_back(self):
        # Products come back with productType.category.name == "Kadas".
        self.assertEqual(normalize_category_for_api("Kadas"), "kada")
        self.assertEqual(normalize_category_for_api("Bracelets"), "bracelet")
        self.assertEqual(CATEGORY_NORMALIZATION_MAP["kada"], "kada")

    def test_category_id_and_site_slug(self):
        from kisna_chatbot.integrations.clara_filters import get_category_id
        from kisna_chatbot.utils.catalogue_facets import CATEGORY_SLUGS

        self.assertEqual(get_category_id("kada"), "6aa38eac98114ff359d41230")
        self.assertEqual(CATEGORY_SLUGS["kada"], ("kadas",))

    def test_llm_may_return_kada(self):
        from kisna_chatbot.processors.classifier import _LLM_ENTITY_CATEGORIES
        from kisna_chatbot.prompts.classifier_kisna import kisna_entity_extractor

        self.assertIn("kada", _LLM_ENTITY_CATEGORIES)
        self.assertIn("kada/kadi → kada (NOT bracelet)", kisna_entity_extractor)

    def test_recap_reads_kadas(self):
        recap = build_search_recap({"category": "kada", "gender": "men", "min_price": 30000, "max_price": 40000})
        self.assertIn("kadas for men", recap)
        self.assertNotIn("bracelet", recap)


class BudgetCorrectionTests(unittest.TestCase):
    """After "No, change it": the tester's exact state (bracelet, men, 30-40k)."""

    def _run(self, text, llm=None):
        profile = {"service_selected": "product_search"}
        set_pending_search(
            profile,
            {"category": "kada", "gender": "men", "min_price": 30000.0, "max_price": 40000.0},
            query_label="wizard:kada:None:None",
            occasion_prefix="Perfect! Let me show you the best kadas ₹30,000–₹40,000.",
        )
        profile[AWAITING_CORRECTION_KEY] = True
        data = {"phone_number": "919999999999", "client_id": "kisna",
                "messages": {"text": {"body": text}}, "user_profile": profile}
        agent = psa.ProductSearchAgentV3()
        executed = AsyncMock(side_effect=lambda d, p, entities, **k: {**d, "bot_response": [{"type": "text", "text": "recap"}], "_entities": entities, "_kwargs": k})
        with patch.object(psa, "_current_message_entities", AsyncMock(return_value={**_NO_ENTITIES, **(llm or {})})), \
                patch.object(psa, "parse_confirm_reply_async", AsyncMock(return_value=None)), \
                patch.object(agent, "_execute_search", executed):
            out = asyncio.run(agent._handle_search_confirmation(data, "919999999999"))
        return out, data

    def test_bare_amount_gets_the_wizard_band(self):
        for text, llm in (("90000", None), ("90000", {"max_price": 90000}), ("90k", None)):
            with self.subTest(text=text, llm=llm):
                out, _ = self._run(text, llm)
                self.assertIsNotNone(out)
                ents = out["_entities"]
                self.assertEqual((ents["min_price"], ents["max_price"]), (80000.0, 100000.0))
                self.assertEqual((ents["category"], ents["gender"]), ("kada", "men"))
                # The old "₹30,000–₹40,000" opener is not reused.
                self.assertIsNone(out["_kwargs"]["occasion_prefix"])

    def test_under_amount_sets_only_the_ceiling(self):
        out, _ = self._run("under 90000")
        self.assertEqual((out["_entities"]["min_price"], out["_entities"]["max_price"]), (None, 90000.0))

    def test_other_corrections_keep_their_path(self):
        # A new metal / gender is left to the normal pipeline, as before.
        out, data = self._run("in gold", {"material_type": "gold"})
        self.assertIsNone(out)
        self.assertEqual(data["_unapplied_search_correction"]["entities"]["min_price"], 30000.0)


class UnappliedCorrectionNeverReachesGeneralAgentTests(unittest.TestCase):
    def test_recap_is_shown_again(self):
        from kisna_chatbot import main as main_mod

        request_data = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "850788844795304"},
            "contacts": [{"profile": {"name": "Test"}}],
            "messages": [{"from": "919999999999", "id": "wamid.kada.test", "type": "text", "text": {"body": "something odd"}}],
        }}]}]}
        entities = {"category": "kada", "gender": "men", "min_price": 80000.0, "max_price": 100000.0}

        async def _run():
            profile = {"chat_history": [], "service_selected": "product_search"}

            async def initial(data):
                return data

            async def search(data):
                data["_unapplied_search_correction"] = {"entities": entities, "query_label": "correction"}
                return data

            with (
                patch.object(main_mod, "mark_inbound_processed", return_value=True),
                patch.object(main_mod, "get_takeover_status", return_value=None),
                patch.object(main_mod, "UserRegistration") as reg_cls,
                patch.object(main_mod, "InitialPipeline") as initial_cls,
                patch.object(main_mod, "_pipeline_for_service") as pipe_for,
                patch.object(main_mod, "save_to_mongo"),
                patch.object(main_mod, "save_response_time"),
                patch("kisna_chatbot.utils.message_trace.persist_message_trace"),
                patch("kisna_chatbot.processors.handoff_sweep.trigger_opportunistic_sweep"),
                patch.object(main_mod.ResponseManager, "handle_responses") as send,
                patch("kisna_chatbot.processors.general_agent.GeneralAgent.process", new_callable=AsyncMock) as general,
            ):
                reg = MagicMock()
                reg.process = AsyncMock(side_effect=lambda d: {**d, "user_profile": profile})
                reg_cls.return_value = reg
                initial_cls.return_value.run = AsyncMock(side_effect=initial)
                pipe_for.return_value = MagicMock(run=AsyncMock(side_effect=search))
                await main_mod.process_message(request_data, app_state=None)
                general.assert_not_awaited()
                sent = send.call_args.kwargs.get("data") or send.call_args[0][0]
                texts = " ".join(r.get("text", "") for r in sent["bot_response"])
                self.assertIn("couldn't apply that change", texts)
                self.assertIn("kadas for men between ₹80,000 and", texts)
                self.assertTrue(profile.get("pending_search"))  # Yes / No work again

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
