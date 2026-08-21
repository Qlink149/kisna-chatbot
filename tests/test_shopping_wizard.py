"""Tests for guided shopping wizard smart-skip funnel."""

import asyncio
import os
import time
import unittest

import pytest

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

from kisna_chatbot.models.service_list import ServiceList as SL  # noqa: E402
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    ProductSearchAgentV3,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    advance_wizard,
    build_wizard_summary,
    entities_from_wizard,
    filter_by_fulfillment,
    get_next_step,
    seed_wizard_from_entities,
    should_start_wizard,
    start_wizard,
)


class ShoppingWizardTests(unittest.TestCase):
    def test_seed_and_smart_skip(self):
        seeded = seed_wizard_from_entities(
            {
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "max_price": 20000,
                "min_price": 0,
                "fulfillment": "ready",
            }
        )
        self.assertIsNone(get_next_step(seeded))
        self.assertFalse(should_start_wizard(seeded))
        # Occasion is no longer a wizard step
        self.assertNotIn("occasion", seeded)

    def test_next_step_after_category_only(self):
        seeded = seed_wizard_from_entities({"category": "ring"})
        self.assertEqual(get_next_step(seeded), "gender")
        self.assertTrue(should_start_wizard({"category": "ring"}))

    def test_start_wizard_asks_gender(self):
        profile = {}
        responses = start_wizard(profile, entities={"category": "ring"})
        self.assertTrue(profile["shopping_wizard_active"])
        self.assertEqual(profile["shopping_wizard_step"], "gender")
        self.assertEqual(responses[0]["type"], "quickreply")
        self.assertEqual(responses[0]["msgid"], "wizard$gender")

    def test_advance_gender_then_material(self):
        profile = {}
        start_wizard(profile, entities={"category": "ring"})
        messages = {
            "interactive": {
                "type": "button_reply",
                "button_reply": {
                    "id": "wizard$gender",
                    "title": "Female",
                },
            }
        }
        status, responses = advance_wizard(profile, messages)
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "women")
        self.assertEqual(profile["shopping_wizard_step"], "material")
        self.assertEqual(responses[0]["msgid"], "wizard$material")

    def test_summary_copy(self):
        text = build_wizard_summary(
            {
                "category": "ring",
                "material_type": "diamond",
                "max_price": 20000,
                "min_price": 0,
            }
        )
        self.assertIn("diamond", text.lower())
        self.assertIn("ring", text.lower())
        self.assertIn("20,000", text)

    def test_entities_from_wizard(self):
        ents = entities_from_wizard(
            {
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "min_price": 0,
                "max_price": 20000,
                "fulfillment": "ready",
            }
        )
        self.assertEqual(ents["category"], "ring")
        self.assertEqual(ents["fulfillment"], "ready")
        self.assertEqual(ents["gender"], "women")
        self.assertIsNone(ents.get("occasion"))

    def test_fulfillment_completes_wizard(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
                "min_price": 0,
                "max_price": 20000,
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        messages = {
            "interactive": {
                "type": "button_reply",
                "button_reply": {
                    "id": "wizard$fulfillment",
                    "title": "Ready to ship",
                },
            }
        }
        status, responses = advance_wizard(profile, messages)
        self.assertEqual(status, "complete")
        self.assertIsNone(responses)
        self.assertEqual(profile["shopping_wizard_data"]["fulfillment"], "ready")

    def test_ready_to_ship_filter(self):
        products = [
            {"title": "fast", "shipping": {"edd": 5}},
            {"title": "slow", "shipping": {"edd": 20}},
        ]
        ready, note = filter_by_fulfillment(products, "ready")
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["title"], "fast")
        self.assertIsNone(note)

    def test_mto_does_not_post_filter(self):
        products = [
            {"title": "a", "shipping": {"edd": 5}},
            {"title": "b", "shipping": {"edd": 20}},
        ]
        out, note = filter_by_fulfillment(products, "mto")
        self.assertEqual(len(out), 2)
        self.assertIsNone(note)

    def test_summary_ready_vs_mto(self):
        ready = build_wizard_summary(
            {
                "category": "ring",
                "material_type": "diamond",
                "max_price": 20000,
                "min_price": 0,
                "fulfillment": "ready",
            }
        )
        self.assertIn("ready-to-ship", ready.lower())
        mto = build_wizard_summary(
            {
                "category": "ring",
                "material_type": "gold",
                "fulfillment": "mto",
            }
        )
        self.assertIn("made to order", mto.lower())

    def test_entities_to_api_params_gender_and_availability(self):
        from kisna_chatbot.processors.entity_extractor import entities_to_api_params

        ready = entities_to_api_params(
            {
                "category": "ring",
                "material_type": "diamond",
                "gender": "women",
                "fulfillment": "ready",
                "max_price": 20000,
                "min_price": 0,
            }
        )
        self.assertTrue(ready.get("ready_to_ship"))
        self.assertNotIn("made_to_order", ready)
        self.assertEqual(
            ready.get("tag_manager_id"), "6710b86de3421b6a92589b39"
        )

        mto = entities_to_api_params(
            {"category": "ring", "fulfillment": "mto", "gender": "men"}
        )
        self.assertTrue(mto.get("made_to_order"))
        self.assertNotIn("ready_to_ship", mto)
        self.assertEqual(mto.get("tag_manager_id"), "66ec862c348e37f29673a282")

    def test_ready_to_ship_relaxes_when_empty(self):
        products = [
            {"title": "slow", "shipping": {"edd": 20}},
        ]
        ready, note = filter_by_fulfillment(products, "ready")
        self.assertEqual(len(ready), 1)
        self.assertIsNone(note)

    def test_start_wizard_clears_stale_store_wait(self):
        profile = {
            "awaiting_store_pincode": True,
            "store_pincode_attempts": 2,
        }
        start_wizard(profile, entities={"category": "ring"})
        self.assertTrue(profile.get("shopping_wizard_active"))
        self.assertNotIn("awaiting_store_pincode", profile)
        self.assertNotIn("store_pincode_attempts", profile)

    def test_budget_50k_not_stolen_by_stale_store_wait(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "messages": {"text": {"body": "50k"}},
                "user_profile": {
                    "shopping_wizard_active": True,
                    "shopping_wizard_step": "budget",
                    "shopping_wizard_data": {
                        "category": "ring",
                        "gender": "men",
                        "material_type": "gold",
                    },
                    "awaiting_store_pincode": True,
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "Ring"}],
                    "last_message_at": int(time.time()),
                },
            }
            result = await agent.process(data)
            text = (result.get("bot_response") or [{}])[0].get("text", "")
            self.assertNotIn("pincode", text.lower())
            self.assertNotIn("awaiting_store_pincode", result["user_profile"])
            self.assertEqual(
                result["user_profile"].get("shopping_wizard_step"), "fulfillment"
            )

        asyncio.run(_run())

    def test_budget_text_advance(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "ring",
                "gender": "women",
                "material_type": "diamond",
            },
        )
        self.assertEqual(profile["shopping_wizard_step"], "budget")
        status, responses = advance_wizard(
            profile, {}, text="20000"
        )
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_step"], "fulfillment")
        self.assertIsNotNone(profile["shopping_wizard_data"].get("max_price"))

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
        start_wizard(
            profile,
            entities={"category": "ring", "gender": "women"},
        )
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "women")
        self.assertEqual(profile["shopping_wizard_step"], "material")
        status, _ = advance_wizard(profile, {}, text="for men gold")
        self.assertEqual(status, "prompt")
        self.assertEqual(profile["shopping_wizard_data"]["gender"], "men")
        self.assertEqual(profile["shopping_wizard_data"]["material_type"], "gold")

    def test_explicit_karat_colour_survive_wizard_completion(self):
        profile = {}
        start_wizard(
            profile,
            entities={
                "category": "chain",
                "material_type": "gold",
                "karat": "18KT",
                "metal_colour": "rose",
            },
            query="18kt rose gold chain",
        )
        self.assertEqual(
            profile.get("shopping_wizard_explicit"),
            {"karat": "18KT", "metal_colour": "rose"},
        )
        advance_wizard(
            profile,
            {
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "wizard$gender", "title": "Female"},
                }
            },
        )
        advance_wizard(profile, {}, text="under 50k")
        status, _ = advance_wizard(
            profile,
            {
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {
                        "id": "wizard$fulfillment",
                        "title": "Either is fine",
                    },
                }
            },
        )
        self.assertEqual(status, "complete")
        ents = entities_from_wizard(
            profile["shopping_wizard_data"],
            profile.get("shopping_wizard_explicit"),
        )
        self.assertEqual(ents["category"], "chain")
        self.assertEqual(ents["material_type"], "gold")
        self.assertEqual(ents["karat"], "18KT")
        self.assertEqual(ents["metal_colour"], "rose")
        self.assertEqual(ents["gender"], "women")

    def test_explicit_collection_survives(self):
        ents = entities_from_wizard(
            {
                "category": "bracelet",
                "gender": "women",
                "material_type": "gold",
                "min_price": 0,
                "max_price": 50000,
                "fulfillment": "any",
            },
            {"collection": "evil eye", "title": "evil eye"},
        )
        self.assertEqual(ents["collection"], "evil eye")
        self.assertEqual(ents["title"], "evil eye")

    def test_slot_answer_overrides_seeded_slot_not_explicit(self):
        collected = {
            "category": "ring",
            "gender": "men",
            "material_type": "gold",
            "min_price": 0,
            "max_price": 20000,
            "fulfillment": "ready",
        }
        ents = entities_from_wizard(
            collected,
            {"karat": "18KT", "metal_colour": "rose"},
        )
        self.assertEqual(ents["gender"], "men")
        self.assertEqual(ents["karat"], "18KT")
        self.assertEqual(ents["metal_colour"], "rose")

    def test_mid_wizard_explicit_karat_updates_channel(self):
        profile = {}
        start_wizard(profile, entities={"category": "chain", "material_type": "gold"})
        self.assertEqual(profile.get("shopping_wizard_explicit"), {})
        # Production feeds context-free extractor/LLM entities for THIS turn.
        advance_wizard(
            profile,
            {},
            text="actually make it 18kt",
            llm_entities={"karat": "18KT"},
        )
        self.assertEqual(
            (profile.get("shopping_wizard_explicit") or {}).get("karat"),
            "18KT",
        )

    def test_clear_wizard_clears_explicit(self):
        from kisna_chatbot.processors.shopping_wizard import clear_wizard_state

        profile = {
            "shopping_wizard_active": True,
            "shopping_wizard_explicit": {"karat": "18KT"},
            "shopping_wizard_data": {"category": "chain"},
        }
        clear_wizard_state(profile)
        self.assertNotIn("shopping_wizard_explicit", profile)



class DynamicWizardSkipTests(unittest.TestCase):
    """Phase 4 — skip/auto-set gender from cached /filters."""

    def setUp(self):
        from kisna_chatbot.integrations import clara_filters as cf

        cf.reset_filters_cache_for_tests()
        payload = cf._seed_from_snapshot(None)
        self.assertIsNotNone(payload)
        cf._CACHE[None].fetched_at = time.time()
        for cid in (cf._load_snapshot() or {}).get("by_category") or {}:
            cf._seed_from_snapshot(cid)
            if cid in cf._CACHE:
                cf._CACHE[cid].fetched_at = time.time()

    def tearDown(self):
        from kisna_chatbot.integrations import clara_filters as cf

        cf.reset_filters_cache_for_tests()

    def test_chain_skips_gender_auto_set_women(self):
        seeded = seed_wizard_from_entities({"category": "chain"})
        self.assertEqual(get_next_step(seeded), "material")
        self.assertEqual(seeded.get("gender"), "women")

    def test_rings_asks_two_genders_male_female(self):
        from kisna_chatbot.processors.shopping_wizard import build_step_prompt

        seeded = seed_wizard_from_entities({"category": "ring"})
        self.assertEqual(get_next_step(seeded), "gender")
        prompt = build_step_prompt("gender", seeded)
        titles = [o["title"] for o in prompt["options"]]
        self.assertEqual(set(titles), {"Male", "Female"})
        self.assertNotIn("Kids", titles)

    def test_souvenir_skips_gender_as_any(self):
        seeded = seed_wizard_from_entities({"category": "souvenir"})
        self.assertEqual(get_next_step(seeded), "material")
        self.assertEqual(seeded.get("gender"), "any")

    def test_cold_cache_uses_legacy_wizard(self):
        from kisna_chatbot.integrations import clara_filters as cf
        from kisna_chatbot.processors.shopping_wizard import build_step_prompt

        cf.reset_filters_cache_for_tests()
        cf._SNAPSHOT_LOADED = True
        cf._SNAPSHOT = None
        seeded = seed_wizard_from_entities({"category": "chain"})
        self.assertEqual(get_next_step(seeded), "gender")
        prompt = build_step_prompt("gender", seeded)
        titles = [o["title"] for o in prompt["options"]]
        self.assertEqual(titles, ["Female", "Male", "Kids"])


@pytest.mark.live
@pytest.mark.no_search_recap
class BudgetStepIntegrationTests(unittest.TestCase):
    """Full ProductSearchAgentV3.process() through the text-based budget step.

    NOT a re-test of maybe_expire_session (that's covered directly by
    TtlMissingTimestampTests in test_sticky_state_hygiene.py — missing
    last_message_at clearing sticky flags is intentional, documented
    behavior, proven there already). This is closing a DIFFERENT gap: the
    wizard's explicit-value survival through the budget step had only ever
    been exercised by feeding advance_wizard()/entities_from_wizard() a
    hand-built collected dict directly, never through the real should_run()
    -> process() integration a live inbound message actually takes. A test
    harness that calls Classifier/ProductSearchAgentV3 without stamping
    last_message_at between turns (as the real db_utils.py persistence
    layer always does before the next turn loads the profile) hits
    maybe_expire_session's missing-timestamp path and wipes the wizard —
    a false alarm in the harness, not a reachable production state. This
    test stamps last_message_at exactly like production does, so it
    exercises the real code path rather than reproducing that false alarm.
    """

    def _profile_after_wizard_start(self) -> dict:
        profile: dict = {}
        start_wizard(
            profile,
            entities={
                "category": "chain",
                "material_type": "gold",
                "karat": "18KT",
                "metal_colour": "rose",
            },
            query="18kt rose gold chain",
        )
        profile["last_message_at"] = int(time.time())
        return profile

    async def _agent_turn(self, agent, profile: dict, phone: str, *, text: str | None = None, interactive: dict | None = None):
        messages: dict = {}
        if text is not None:
            messages["text"] = {"body": text}
        if interactive is not None:
            messages["interactive"] = interactive
        data = {"phone_number": phone, "user_profile": profile, "messages": messages}
        if agent.should_run(data):
            data = await agent.process(data)
        profile["last_message_at"] = int(time.time())
        return data

    def test_budget_text_does_not_reset_wizard(self):
        # A single asyncio.run() for the whole test — the async OpenAI/httpx
        # client used by the wizard's live budget-text extraction is bound
        # to whichever event loop created it; calling asyncio.run() more
        # than once per test (a fresh loop each time) makes its connection
        # cleanup fire against an already-closed loop. One loop, all turns.
        async def _run():
            from unittest.mock import AsyncMock, patch

            profile = self._profile_after_wizard_start()
            self.assertEqual(profile.get("shopping_wizard_step"), "budget")
            self.assertEqual(
                profile.get("shopping_wizard_explicit"),
                {"karat": "18KT", "metal_colour": "rose"},
            )

            async def fake_search(**kwargs):
                return {"products": [], "total_count": 0, "page": 1}

            agent = ProductSearchAgentV3()
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ):
                await self._agent_turn(agent, profile, "919900001111", text="under 50k")

            self.assertNotEqual(profile.get("shopping_wizard_step"), "category")
            wizard_data = profile.get("shopping_wizard_data") or {}
            # start_wizard() is called directly here (bypassing the chain->
            # necklace bookkeeping normalization that happens upstream in
            # normalize_internal_category during full-pipeline runs), so
            # category stays exactly as given.
            self.assertEqual(wizard_data.get("category"), "chain")
            self.assertEqual(wizard_data.get("material_type"), "gold")
            self.assertEqual(wizard_data.get("gender"), "women")  # chain auto-skip, C2
            self.assertEqual(
                profile.get("shopping_wizard_explicit"),
                {"karat": "18KT", "metal_colour": "rose"},
                "explicit karat/colour must survive the budget turn",
            )

        asyncio.run(_run())

    def test_explicit_karat_reaches_outbound_clara_params(self):
        async def _run():
            from unittest.mock import AsyncMock, patch

            from kisna_chatbot.integrations import clara_filters as cf

            await cf.warm_filters_cache()
            profile = self._profile_after_wizard_start()
            # _execute_search tries a LADDER of fallback strategies (strict
            # first, progressively relaxed) — capture EVERY call, not just
            # the last, since a later .update() on one shared dict would
            # silently overwrite the strict first attempt with a relaxed
            # later one that has already dropped the karat filter.
            all_calls: list[dict] = []

            async def fake_search(**kwargs):
                all_calls.append(dict(kwargs))
                return {"products": [], "total_count": 0, "page": 1}

            agent = ProductSearchAgentV3()
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ):
                await self._agent_turn(agent, profile, "919900001112", text="under 50k")
                for _ in range(3):
                    if not profile.get("shopping_wizard_active"):
                        break
                    step = profile.get("shopping_wizard_step")
                    if step is None:
                        break
                    # "Ready to ship" (not "Either is fine") to match the
                    # exact fulfillment choice already live-verified to
                    # carry karat through to the first search attempt.
                    interactive = {
                        "type": "button_reply",
                        "button_reply": {"id": f"wizard${step}", "title": "Ready to ship"},
                    }
                    await self._agent_turn(agent, profile, "919900001112", interactive=interactive)
                    if all_calls:
                        break

            self.assertTrue(all_calls, "wizard never reached a real search_products call")
            first_call = all_calls[0]
            # category/gender/price must always survive regardless of live
            # catalogue state — these don't depend on Chain's own facets.
            self.assertEqual(first_call.get("category_id"), self._chain_category_id())
            self.assertEqual(first_call.get("tag_manager_id"), self._women_tag_id())
            self.assertEqual(first_call.get("max_price"), 50000)

            # meta_sub_attribute_value (karat/colour) additionally requires
            # Chain's OWN category-scoped karat/colour facets to be
            # populated upstream on Clara right now — see
            # audit/CLARA_FILTERS_INSTABILITY.md: this has been observed
            # empty for Chain specifically, sustained across sessions, as
            # a live UAT catalogue issue unrelated to this codebase. When
            # that facet is genuinely empty, get_karat_id/get_colour_id
            # correctly return None and the meta filter is correctly
            # omitted (same designed behavior test_filters_guardrails.py's
            # test_cold_skips_impossible_validation pins down) — that is
            # not a regression to fail this test over.
            chain_karat_options = cf._resolve_cached_payload(self._chain_category_id())
            karat_facet_populated = bool((chain_karat_options or {}).get("karat"))
            if not karat_facet_populated:
                self.skipTest(
                    "Chain's live karat facet is currently empty upstream on "
                    "Clara (audit/CLARA_FILTERS_INSTABILITY.md) — "
                    "meta_sub_attribute_value cannot resolve regardless of "
                    "what this codebase does; not a code regression."
                )
            self.assertIsNotNone(
                first_call.get("meta_sub_attribute_value"),
                "explicit 18KT must reach the outbound Clara search call's "
                f"first (strictest) attempt (got: {first_call})",
            )

        asyncio.run(_run())

    @staticmethod
    def _chain_category_id() -> str:
        return "66ec057581b26b00081b3fae"

    @staticmethod
    def _women_tag_id() -> str:
        return "6710b86de3421b6a92589b39"


@pytest.mark.live
class MidWizardCorrectionTests(unittest.TestCase):
    """D8 — does a mid-wizard explicit correction land, get ignored, or
    restart the funnel? Confirmed live, 3/3: it lands cleanly. Pinning
    down the confirmed-correct behavior so a future regression is caught.
    """

    def test_correction_updates_value_without_restarting(self):
        from unittest.mock import AsyncMock, patch

        async def fake_search(**kwargs):
            return {"products": [], "total_count": 0, "page": 1}

        async def _run():
            phone = "919900002222"
            profile: dict = {}
            start_wizard(
                profile,
                entities={
                    "category": "chain",
                    "material_type": "gold",
                    "karat": "18KT",
                    "metal_colour": "rose",
                },
                query="18kt rose gold chain",
            )
            profile["last_message_at"] = int(time.time())

            agent = ProductSearchAgentV3()
            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ):
                data = {
                    "phone_number": phone,
                    "user_profile": profile,
                    "messages": {"text": {"body": "under 50k"}},
                }
                if agent.should_run(data):
                    await agent.process(data)
                profile["last_message_at"] = int(time.time())

                budget_before_correction = dict(profile.get("shopping_wizard_data") or {})
                data = {
                    "phone_number": phone,
                    "user_profile": profile,
                    "messages": {"text": {"body": "actually make it 14kt"}},
                }
                if agent.should_run(data):
                    await agent.process(data)

            self.assertTrue(
                profile.get("shopping_wizard_active"),
                "correction must not end/restart the wizard",
            )
            self.assertNotEqual(
                profile.get("shopping_wizard_step"),
                "category",
                "correction must not restart the funnel",
            )
            self.assertEqual(
                (profile.get("shopping_wizard_explicit") or {}).get("karat"),
                "14KT",
                "the correction must land",
            )
            self.assertEqual(
                (profile.get("shopping_wizard_explicit") or {}).get("metal_colour"),
                "rose",
                "unrelated explicit values must survive the correction",
            )
            self.assertEqual(
                dict(profile.get("shopping_wizard_data") or {}),
                budget_before_correction,
                "budget already captured must survive an unrelated correction",
            )

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()