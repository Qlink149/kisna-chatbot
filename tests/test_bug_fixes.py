"""Regression tests for all audit bug fixes (B-01 through B-17).

FIX 1+2  awaiting_custom_budget escape + context isolation
FIX 3    Session expiry enforcement
FIX 4    Defensive _NEVER_INHERIT_FIELDS strip (verified via integration)
FIX 5    Store pincode retry escape tip
FIX 6    GeneralAgent catalog follow-up guard
FIX 7    Remove birthday->earring assumption
FIX 8    Complaint None flow token
FIX 10   shown_product_ids trim
FIX 11   pref$cat$any clears preference state
FIX 12   filter_ratio / api_total reset on fresh browse
FIX 13   pending_flow_switch TTL expiry
"""

import asyncio
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.models.enums import QuickReplyId


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_text_msg(body):
    return {"text": {"body": body}}


def _product_search_profile(**extra):
    base = {
        "service_selected": SL.PRODUCT_SEARCH.value,
        "chat_history": [],
        "shown_product_ids": [],
        "last_search_filters": {},
        "last_search_page": 0,
        "last_search_total": 0,
    }
    base.update(extra)
    return base


def _mock_product(pid="p1"):
    return {
        "_id": pid,
        "title": "Gold Ring",
        "price": {"variantPrice": 25000},
        "materialType": "gold",
        "productType": {"category": {"name": "Rings"}},
        "shipping": {"edd": 5},
        "seos": {"slug": "gold-ring"},
        "mediaUrl": [{"isDefault": True, "image": "https://img.example/ring.webp", "type": "image"}],
    }


def _search_return(products=None, total=1):
    return {"products": products or [_mock_product()], "total_count": total, "page": 1}


# ---------------------------------------------------------------------------
# FIX 1+2 — awaiting_custom_budget escape + context isolation
# ---------------------------------------------------------------------------

class CustomBudgetEscapeTests(unittest.TestCase):
    def setUp(self):
        from kisna_chatbot.processors.product_search_agent_v3 import _should_escape_custom_budget
        self._escape = _should_escape_custom_budget

    def test_escape_category_lowercase(self):
        self.assertTrue(self._escape("earrings"))

    def test_escape_category_capitalized(self):
        self.assertTrue(self._escape("Rings"))

    def test_escape_material_keyword(self):
        self.assertTrue(self._escape("show me gold"))

    def test_escape_service_keyword(self):
        self.assertTrue(self._escape("track my order"))

    def test_escape_explicit_cancel(self):
        self.assertTrue(self._escape("cancel"))

    def test_escape_menu(self):
        self.assertTrue(self._escape("menu"))

    def test_no_escape_plain_number(self):
        self.assertFalse(self._escape("25000"))

    def test_no_escape_range(self):
        self.assertFalse(self._escape("15000-35000"))

    def test_no_escape_tak_budget(self):
        self.assertFalse(self._escape("50000 tak"))

    def test_escape_compound_query(self):
        self.assertTrue(self._escape("gold earrings under 10k"))

    def test_escape_hindi_category(self):
        self.assertTrue(self._escape("jhumka dikhao"))

    def test_no_escape_empty(self):
        self.assertFalse(self._escape(""))

    def test_escape_clears_flag_in_should_run(self):
        from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
        agent = ProductSearchAgentV3()
        profile = _product_search_profile(awaiting_custom_budget=True)
        data = {"messages": _make_text_msg("gold earrings under 10k"), "user_profile": profile}
        agent.should_run(data)
        self.assertFalse(profile["awaiting_custom_budget"])

    def test_budget_flag_preserved_for_valid_budget_in_should_run(self):
        from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
        agent = ProductSearchAgentV3()
        profile = _product_search_profile(awaiting_custom_budget=True)
        data = {"messages": _make_text_msg("25000"), "user_profile": profile}
        agent.should_run(data)
        self.assertTrue(profile["awaiting_custom_budget"])


class CustomBudgetContextIsolationTests(unittest.TestCase):
    def test_budget_search_does_not_inherit_prior_title(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            profile = _product_search_profile(
                awaiting_custom_budget=True,
                pref_category="ring",
                pref_material="gold",
                last_search_filters={"category": "pendant", "title": "set", "material_type": "gold"},
            )
            data = {
                "phone_number": "919999999999",
                "messages": _make_text_msg("25000"),
                "user_profile": profile,
            }
            captured = {}
            original_exec = agent._execute_search

            async def capture_exec(data, phone, entities, **kwargs):
                captured["entities"] = dict(entities)
                return await original_exec(data, phone, entities, **kwargs)

            with patch.object(agent, "_execute_search", side_effect=capture_exec), \
                 patch("kisna_chatbot.processors.product_search_agent_v3.search_products",
                       new_callable=AsyncMock, return_value=_search_return()):
                await agent.process(data)

            ents = captured.get("entities", {})
            self.assertIsNone(ents.get("title"), "title must not bleed from prior session")
            self.assertEqual(ents.get("category"), "ring", "pref_category should be used")
            # _parse_custom_budget_text("25000") → ±10% band (22500–27500)
            self.assertEqual(ents.get("min_price"), 22500)
            self.assertEqual(ents.get("max_price"), 27500)
        asyncio.run(_run())

    def test_three_failures_resets_flag_and_falls_back(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            profile = _product_search_profile(awaiting_custom_budget=True, custom_budget_attempts=2)
            data = {
                "phone_number": "919999999999",
                "messages": _make_text_msg("xyz not a budget"),
                "user_profile": profile,
            }
            with patch("kisna_chatbot.processors.product_search_agent_v3.search_products",
                       new_callable=AsyncMock, return_value=_search_return()):
                result = await agent.process(data)
            self.assertFalse(result["user_profile"].get("awaiting_custom_budget"))
            self.assertEqual(result["user_profile"].get("custom_budget_attempts"), 0)
            self.assertIn("bot_response", result)
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# FIX 3 — Session expiry enforcement
# ---------------------------------------------------------------------------

class SessionExpiryTests(unittest.TestCase):
    def test_expired_session_clears_state(self):
        from kisna_chatbot.processors.product_search_agent_v3 import _clear_session_if_expired
        profile = {
            "last_search_at": int(time.time()) - (3 * 60 * 60),
            "last_search_filters": {"category": "ring"},
            "pref_category": "ring",
            "awaiting_custom_budget": True,
            "custom_budget_attempts": 2,
        }
        _clear_session_if_expired(profile)
        self.assertEqual(profile.get("last_search_filters"), {})
        self.assertFalse(profile.get("awaiting_custom_budget"))
        self.assertEqual(profile.get("custom_budget_attempts"), 0)

    def test_fresh_session_not_cleared(self):
        from kisna_chatbot.processors.product_search_agent_v3 import _clear_session_if_expired
        profile = {
            "last_search_at": int(time.time()) - (30 * 60),
            "last_search_filters": {"category": "ring"},
        }
        _clear_session_if_expired(profile)
        self.assertEqual(profile["last_search_filters"], {"category": "ring"})

    def test_show_more_refreshes_last_search_at(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            old_ts = int(time.time()) - 100
            profile = _product_search_profile(
                last_search_filters={"category": "ring"},
                last_search_page=1,
                last_search_total=10,
                last_search_filter_ratio=1.0,
                last_search_api_total=10,
                last_search_at=old_ts,
            )
            data = {
                "phone_number": "919999999999",
                "messages": {"interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": "search$more", "title": "Show More"},
                }},
                "user_profile": profile,
            }
            with patch("kisna_chatbot.processors.product_search_agent_v3.search_products",
                       new_callable=AsyncMock,
                       return_value={"products": [_mock_product("p2")], "total_count": 10, "page": 2}):
                result = await agent.process(data)
            new_ts = result["user_profile"].get("last_search_at", 0)
            self.assertGreater(new_ts, old_ts, "last_search_at must be updated on Show More")
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# FIX 5 — Store pincode retry escape tip
# ---------------------------------------------------------------------------

class StorePincodeRetryTipTests(unittest.TestCase):
    def test_first_failure_no_escape_tip(self):
        async def _run():
            from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
            agent = AdFlowAgent()
            profile = {"awaiting_store_pincode": True, "service_selected": SL.AD_FLOW.value, "store_pincode_attempts": 0}
            data = {"phone_number": "919999999999", "messages": _make_text_msg("abcdef not a pincode"), "user_profile": profile}
            result = await agent.process(data)
            resp_text = result["bot_response"][0]["text"]
            self.assertNotIn("menu", resp_text.lower())
            self.assertEqual(result["user_profile"].get("store_pincode_attempts"), 1)
        asyncio.run(_run())

    def test_second_failure_reprompts_and_tracks_attempts(self):
        async def _run():
            from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
            agent = AdFlowAgent()
            profile = {"awaiting_store_pincode": True, "service_selected": SL.AD_FLOW.value, "store_pincode_attempts": 1}
            data = {"phone_number": "919999999999", "messages": _make_text_msg("abcdef not a pincode"), "user_profile": profile}
            result = await agent.process(data)
            resp_text = result["bot_response"][0]["text"]
            self.assertIn("pincode", resp_text.lower())
            self.assertEqual(result["user_profile"].get("store_pincode_attempts"), 2)
            self.assertTrue(result["user_profile"].get("awaiting_store_pincode"))
        asyncio.run(_run())

    def test_success_resets_attempt_counter(self):
        async def _run():
            from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
            agent = AdFlowAgent()
            profile = {"awaiting_store_pincode": True, "service_selected": SL.AD_FLOW.value, "store_pincode_attempts": 2}
            data = {"phone_number": "919999999999", "messages": _make_text_msg("400001"), "user_profile": profile, "app_state": None}
            mock_store = {"name": "KISNA Test", "address": "Mumbai 400001", "phone": "9999999999"}
            with patch("kisna_chatbot.processors.ad_flow_agent.get_stores", new_callable=AsyncMock,
                       return_value={"stores": [mock_store], "total_count": 1}):
                result = await agent.process(data)
            self.assertEqual(result["user_profile"].get("store_pincode_attempts"), 0)
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# FIX 6 — GeneralAgent catalog follow-up guard
# ---------------------------------------------------------------------------

class CatalogFollowupGuardTests(unittest.TestCase):
    def test_price_of_gold_stays_in_general(self):
        async def _run():
            from kisna_chatbot.processors.general_agent import GeneralAgent
            agent = GeneralAgent()
            data = {
                "phone_number": "919999999999",
                "messages": _make_text_msg("what is the price of gold?"),
                "user_profile": {"service_selected": SL.GENERAL.value, "last_search_products": [_mock_product()]},
                "client_id": "kisna",
            }
            llm_result = MagicMock()
            llm_result.live_agent_requested = False
            llm_result.message_text = "Gold prices..."
            llm_result.provider = MagicMock(value="openai")
            llm_result.model = "gpt-4o-mini"
            llm_result.latency_ms = 200
            with patch("kisna_chatbot.processors.general_agent.run_general_agent",
                       new_callable=AsyncMock, return_value=llm_result) as mock_llm:
                result = await agent.process(data)
            mock_llm.assert_awaited_once()
            self.assertNotEqual(result.get("classified_category"), "product_info")
        asyncio.run(_run())

    def test_price_of_this_ring_reroutes_to_product_info(self):
        async def _run():
            from kisna_chatbot.processors.general_agent import GeneralAgent
            agent = GeneralAgent()
            data = {
                "phone_number": "919999999999",
                "messages": _make_text_msg("what is the price of this ring?"),
                "user_profile": {"service_selected": SL.GENERAL.value, "last_search_products": [_mock_product()]},
                "client_id": "kisna",
            }
            with patch("kisna_chatbot.processors.general_agent.run_general_agent",
                       new_callable=AsyncMock) as mock_llm:
                result = await agent.process(data)
            mock_llm.assert_not_awaited()
            self.assertEqual(result.get("classified_category"), "product_info")
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# FIX 7 — Remove birthday->earring assumption
# ---------------------------------------------------------------------------

class BirthdayOccasionTests(unittest.TestCase):
    def test_birthday_does_not_set_earring_category(self):
        from kisna_chatbot.processors.entity_extractor import apply_occasion_style_hints
        enhanced, _ = apply_occasion_style_hints({"occasion": "birthday"})
        self.assertIsNone(enhanced.get("category"))

    def test_birthday_with_explicit_category_keeps_it(self):
        from kisna_chatbot.processors.entity_extractor import apply_occasion_style_hints
        enhanced, _ = apply_occasion_style_hints({"occasion": "birthday", "category": "ring"})
        self.assertEqual(enhanced.get("category"), "ring")

    def test_wedding_still_sets_bridal_title(self):
        from kisna_chatbot.processors.entity_extractor import apply_occasion_style_hints
        enhanced, _ = apply_occasion_style_hints({"occasion": "wedding"})
        self.assertEqual(enhanced.get("title"), "bridal")


# ---------------------------------------------------------------------------
# FIX 8 — Complaint None flow token
# ---------------------------------------------------------------------------

class ComplaintNoneTokenTests(unittest.TestCase):
    def test_none_not_in_flow_ids(self):
        from kisna_chatbot.processors.complaint_agent import _complaint_flow_ids
        flow_ids = _complaint_flow_ids()
        self.assertNotIn(None, flow_ids)
        self.assertNotIn("", flow_ids)

    def test_nfm_reply_null_token_not_parsed_when_env_unset(self):
        from kisna_chatbot.processors.complaint_agent import _parse_complaint_flow
        messages = {
            "interactive": {
                "nfm_reply": {
                    "response_json": json.dumps({"flow_token": None, "order_id": "ORD123"})
                }
            }
        }
        with patch.dict(os.environ, {"KISNA_DAMAGE_FLOW_ID": ""}, clear=False):
            result = _parse_complaint_flow(messages)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# FIX 10 — shown_product_ids trim
# ---------------------------------------------------------------------------

class ShownProductIdsTrimTests(unittest.TestCase):
    def test_trim_fires_when_over_100(self):
        from kisna_chatbot.processors.product_search_agent_v3 import (
            _append_shown_product_ids, _MAX_SHOWN_IDS, _SHOWN_IDS_TRIM_TO
        )
        profile = {"shown_product_ids": [str(i) for i in range(98)]}
        new_products = [{"_id": str(i)} for i in range(98, 103)]
        _append_shown_product_ids(profile, new_products)
        self.assertLessEqual(len(profile["shown_product_ids"]), _MAX_SHOWN_IDS)
        self.assertEqual(len(profile["shown_product_ids"]), _SHOWN_IDS_TRIM_TO)

    def test_no_trim_below_100(self):
        from kisna_chatbot.processors.product_search_agent_v3 import _append_shown_product_ids
        profile = {"shown_product_ids": [str(i) for i in range(10)]}
        _append_shown_product_ids(profile, [{"_id": "99"}])
        self.assertEqual(len(profile["shown_product_ids"]), 11)


# ---------------------------------------------------------------------------
# FIX 11 — pref$cat$any clears preference state
# ---------------------------------------------------------------------------

class PrefCatAnyStateClearTests(unittest.TestCase):
    def test_pref_cat_any_clears_pref_state(self):
        async def _run():
            from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
            agent = ProductSearchAgentV3()
            list_id = json.dumps({"msgid": "search$cat$list", "postbackText": "pref$cat$any"})
            profile = _product_search_profile(
                pref_category="ring", pref_material="gold", pref_type="ring", preference_step=1
            )
            data = {
                "phone_number": "919999999999",
                "messages": {"interactive": {"type": "list_reply", "list_reply": {"id": list_id, "title": "Browse All"}}},
                "user_profile": profile,
                "client_config": MagicMock(client_id="kisna"),
            }
            with patch("kisna_chatbot.processors.product_search_agent_v3.search_products",
                       new_callable=AsyncMock, return_value=_search_return()):
                result = await agent.process(data)
            up = result["user_profile"]
            self.assertIsNone(up.get("pref_material"))
            self.assertIsNone(up.get("pref_type"))
            self.assertNotIn("pref_category", up)
        asyncio.run(_run())


# ---------------------------------------------------------------------------
# FIX 12 — filter_ratio / api_total reset on fresh browse
# ---------------------------------------------------------------------------

class FilterRatioClearTests(unittest.TestCase):
    def test_clear_session_resets_exhaustion_counters(self):
        from kisna_chatbot.processors.service_list import _clear_explore_browse_session
        profile = {
            "last_search_filter_ratio": 0.2,
            "last_search_api_total": 500,
            "last_search_filters": {"category": "ring"},
            "last_search_page": 3,
            "last_search_total": 100,
            "last_search_products": [_mock_product()],
            "shown_product_ids": ["p1"],
            "pref_material": "gold",
            "pref_type": "ring",
        }
        _clear_explore_browse_session(profile)
        self.assertEqual(profile["last_search_filter_ratio"], 1.0)
        self.assertEqual(profile["last_search_api_total"], 0)
        self.assertEqual(profile["last_search_filters"], {})
        self.assertEqual(profile["shown_product_ids"], [])


# ---------------------------------------------------------------------------
# FIX 13 — pending_flow_switch TTL expiry
# ---------------------------------------------------------------------------

class PendingFlowSwitchExpiryTests(unittest.TestCase):
    def test_expired_pending_is_discarded(self):
        from kisna_chatbot.processors.service_list import handle_flow_switch_quick_reply
        user_profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "pending_flow_switch": {"intent": "offers", "service": SL.OFFERS.value, "created_at": time.time() - 400},
        }
        data = {"_flow_switch_button_title": "Yes, show offers"}
        handled = handle_flow_switch_quick_reply(QuickReplyId.FLOW_SWITCH_CONFIRM.value, user_profile, data)
        self.assertFalse(handled)
        self.assertNotIn("pending_flow_switch", user_profile)
        self.assertEqual(user_profile["service_selected"], SL.PRODUCT_SEARCH.value)

    def test_fresh_pending_is_handled(self):
        from kisna_chatbot.processors.service_list import handle_flow_switch_quick_reply
        user_profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "last_search_filters": {},
            "shown_product_ids": [],
            "pending_flow_switch": {"intent": "offers", "service": SL.OFFERS.value, "created_at": time.time() - 10},
        }
        data = {"_flow_switch_button_title": "Yes, show offers"}
        handled = handle_flow_switch_quick_reply(QuickReplyId.FLOW_SWITCH_CONFIRM.value, user_profile, data)
        self.assertTrue(handled)
        self.assertEqual(user_profile["service_selected"], SL.OFFERS.value)

    def test_legacy_pending_without_created_at_still_handled(self):
        from kisna_chatbot.processors.service_list import handle_flow_switch_quick_reply
        user_profile = {
            "service_selected": SL.PRODUCT_SEARCH.value,
            "last_search_filters": {},
            "shown_product_ids": [],
            "pending_flow_switch": {"intent": "offers", "service": SL.OFFERS.value},
        }
        data = {"_flow_switch_button_title": "Yes, show offers"}
        handled = handle_flow_switch_quick_reply(QuickReplyId.FLOW_SWITCH_CONFIRM.value, user_profile, data)
        self.assertTrue(handled)

    def test_classifier_silent_switch_no_pending_flow_switch(self):
        async def _run():
            from kisna_chatbot.processors.classifier import Classifier
            clf = Classifier()
            data = {
                "phone_number": "919999999999",
                "messages": _make_text_msg("wapas karna hai"),
                "user_profile": {
                    "service_selected": SL.PRODUCT_SEARCH.value,
                    "chat_history": [{"role": "user", "content": "gold rings"}],
                    "last_search_products": [_mock_product()],
                },
                "client_id": "kisna",
            }
            with patch("kisna_chatbot.processors.classifier.complete_chat", new_callable=AsyncMock,
                       return_value='{"intent": "returns_refund", "confidence": 0.9, "language": "en", "entities": {}}'):
                result = await clf.process(data)
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.RETURNS_REFUND.value,
            )
        asyncio.run(_run())

    def test_ad_flow_silent_switch_no_pending_flow_switch(self):
        async def _run():
            from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
            agent = AdFlowAgent()
            profile = {"awaiting_store_pincode": True, "service_selected": SL.AD_FLOW.value}
            data = {"phone_number": "919999999999", "messages": _make_text_msg("gold rings"), "user_profile": profile}
            result = await agent.process(data)
            self.assertNotIn("pending_flow_switch", result["user_profile"])
            self.assertFalse(result["user_profile"].get("awaiting_store_pincode"))
            self.assertEqual(
                result["user_profile"]["service_selected"],
                SL.PRODUCT_SEARCH.value,
            )
            self.assertEqual(result["bot_response"][0]["type"], "text")
        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
