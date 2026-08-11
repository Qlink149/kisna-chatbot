"""Regressions for the v1-text-flow audit (sticky escape, wizard slots, handoff)."""

import os
import time

import pytest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: E402,F401  (breaks logger/env init cycle)
from kisna_chatbot.models.service_list import ServiceList  # noqa: E402
from kisna_chatbot.processors.classifier import (  # noqa: E402
    Classifier,
    _stash_wizard_carryover,
    _llm_intent_escapes_sticky,
    _programmatic_intent_override,
)
from kisna_chatbot.processors.shopping_wizard import (  # noqa: E402
    _gender_from_text,
    _llm_slot_values,
    advance_wizard,
    seed_wizard_from_entities,
)


def _profile(**flags) -> dict:
    # last_message_at is required: maybe_expire_session() treats a profile
    # without it as expired and wipes every sticky flag.
    base = {"chat_history": [], "service_selected": "", "last_message_at": time.time()}
    base.update(flags)
    return base


def _data(text: str, profile: dict) -> dict:
    return {
        "phone_number": "919999999999",
        "client_id": "kisna",
        "messages": {"type": "text", "text": {"body": text}},
        "user_profile": profile,
    }


# ── #5 wizard gender must not match inside words ───────────────────────────


@pytest.mark.parametrize(
    "text",
    ["ornaments", "1 lakh budget for ornaments", "recommend something nice"],
)
def test_gender_not_inferred_from_substring(text):
    assert _gender_from_text(text) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("for my wife", "women"),
        ("Female", "women"),
        ("mens gold chain", "men"),
        ("kids", "kids"),
    ],
)
def test_gender_still_detected(text, expected):
    assert _gender_from_text(text) == expected


def test_seed_does_not_invent_gender_from_ornaments():
    assert "gender" not in seed_wizard_from_entities({}, query="1 lakh ke ornaments")
    seeded = seed_wizard_from_entities({}, query="gold ring for my wife")
    assert seeded["gender"] == "women"


def test_chosen_gender_survives_a_stray_word():
    profile = {
        "shopping_wizard_active": True,
        "shopping_wizard_step": "budget",
        "shopping_wizard_data": {
            "category": "ring",
            "gender": "women",
            "material_type": "gold",
        },
    }
    advance_wizard(profile, {}, text="kuch recommend karo 50000 tak")
    assert profile["shopping_wizard_data"]["gender"] == "women"


def test_explicit_gender_switch_still_wins():
    profile = {
        "shopping_wizard_active": True,
        "shopping_wizard_step": "budget",
        "shopping_wizard_data": {
            "category": "ring",
            "gender": "women",
            "material_type": "gold",
        },
    }
    advance_wizard(profile, {}, text="actually for my husband, 50000 tak")
    assert profile["shopping_wizard_data"]["gender"] == "men"


# ── #1 native-script slot answers reach the wizard via LLM entities ────────


def test_llm_slot_values_filters_nulls():
    assert _llm_slot_values(
        {
            "category": "ring",
            "material_type": "gold",
            "min_price": 10000,
            "max_price": 30000,
            "gender": None,
        }
    ) == {
        "category": "ring",
        "material_type": "gold",
        "min_price": 10000,
        "max_price": 30000,
    }


def test_devanagari_category_answer_advances_wizard():
    profile = {
        "shopping_wizard_active": True,
        "shopping_wizard_step": "category",
        "shopping_wizard_data": {},
    }
    status, _ = advance_wizard(
        profile, {}, text="अंगूठी", llm_entities={"category": "ring"}
    )
    assert profile["shopping_wizard_data"]["category"] == "ring"
    assert status == "prompt"


def test_gujarati_budget_answer_advances_wizard():
    profile = {
        "shopping_wizard_active": True,
        "shopping_wizard_step": "budget",
        "shopping_wizard_data": {
            "category": "earring",
            "gender": "women",
            "material_type": "gold",
        },
    }
    advance_wizard(
        profile,
        {},
        text="૧૦,૦૦૦ થી ૩૦,૦૦૦ ની વચ્ચે",
        llm_entities={"min_price": 10000, "max_price": 30000},
    )
    assert profile["shopping_wizard_data"]["min_price"] == 10000
    assert profile["shopping_wizard_data"]["max_price"] == 30000


# ── #1 should_run lets native script through every sticky wait ─────────────


@pytest.mark.parametrize(
    "flag",
    ["shopping_wizard_active", "awaiting_store_pincode", "callback_capture_step"],
)
@pytest.mark.parametrize(
    "text",
    [
        "मुझे एजेंट से बात करनी है",
        "મારે એજન્ટ સાથે વાત કરવી છે",
        "मला एजंटशी बोलायचं आहे",
    ],
)
def test_indic_reaches_classifier_inside_sticky_wait(flag, text):
    profile = _profile(**{flag: True})
    if flag == "shopping_wizard_active":
        profile["shopping_wizard_step"] = "material"
        profile["shopping_wizard_data"] = {"category": "ring"}
    assert Classifier().should_run(_data(text, profile)) is True


@pytest.mark.parametrize("text", ["डाइमंड", "सोना", "સોનું"])
def test_indic_slot_answer_the_wizard_reads_skips_classifier(text):
    """Offline-parseable native answers must not depend on an LLM call."""
    profile = _profile(
        shopping_wizard_active=True,
        shopping_wizard_step="material",
        shopping_wizard_data={"category": "necklace", "gender": "women"},
    )
    assert Classifier().should_run(_data(text, profile)) is False


def test_latin_slot_answer_still_skips_classifier():
    profile = _profile(shopping_wizard_active=True)
    assert Classifier().should_run(_data("Diamond", profile)) is False


# ── #1 LLM verdict decides escape per wait ────────────────────────────────


def test_wizard_keeps_shopping_replies_but_releases_handoff():
    profile = {"shopping_wizard_active": True}
    assert _llm_intent_escapes_sticky(profile, "product_search") is False
    assert _llm_intent_escapes_sticky(profile, "general") is False
    assert _llm_intent_escapes_sticky(profile, "human_handoff") is True
    assert _llm_intent_escapes_sticky(profile, "callback") is True


def test_store_wait_keeps_only_store_answers():
    profile = {"awaiting_store_pincode": True}
    assert _llm_intent_escapes_sticky(profile, "store_info") is False
    assert _llm_intent_escapes_sticky(profile, "product_search") is True
    assert _llm_intent_escapes_sticky(profile, "human_handoff") is True


def test_callback_capture_keeps_free_text_names():
    profile = {"callback_capture_step": 1}
    # A name classifies as low-confidence "general" — must stay in the capture.
    assert _llm_intent_escapes_sticky(profile, "general") is False
    assert _llm_intent_escapes_sticky(profile, "callback") is False
    assert _llm_intent_escapes_sticky(profile, "complaint") is True


# ── #2 button-tapped slots must survive a browse escape ───────────────────


def test_button_tapped_slots_are_carried_for_this_turn():
    data = {}
    profile = {
        "shopping_wizard_data": {
            "category": "ring",
            "gender": "women",
            "material_type": "gold",
        }
    }
    _stash_wizard_carryover(data, profile)
    # category comes from the new message; gender/material came from buttons.
    assert data["_wizard_carryover"] == {"gender": "women", "material_type": "gold"}


def test_carryover_is_absent_without_tapped_slots():
    data = {}
    _stash_wizard_carryover(data, {"shopping_wizard_data": {"category": "ring"}})
    assert "_wizard_carryover" not in data
    _stash_wizard_carryover(data, {})
    assert "_wizard_carryover" not in data


def test_carryover_never_persists_on_the_profile():
    data = {}
    profile = {"shopping_wizard_data": {"gender": "women"}}
    _stash_wizard_carryover(data, profile)
    assert "_wizard_carryover" not in profile


def test_escape_stashes_carryover_and_clears_wizard():
    import asyncio
    from unittest.mock import AsyncMock, patch

    profile = _profile(
        shopping_wizard_active=True,
        shopping_wizard_step="budget",
        shopping_wizard_data={
            "category": "ring",
            "gender": "women",
            "material_type": "gold",
        },
        service_selected=ServiceList.PRODUCT_SEARCH.value,
        chat_history=[{"role": "user", "content": "rings"}],
    )
    data = _data("rings under 30k", profile)
    with patch(
        "kisna_chatbot.processors.classifier.complete_chat",
        new_callable=AsyncMock,
        return_value='{"intent":"product_search","confidence":0.95,'
        '"entities":{"category":"ring","max_price":30000}}',
    ):
        result = asyncio.run(Classifier().process(data))
    assert not result["user_profile"].get("shopping_wizard_active")
    assert result["_wizard_carryover"] == {"gender": "women", "material_type": "gold"}


# ── #4 competitor comparison is no longer a hard override ─────────────────


@pytest.mark.parametrize(
    "text",
    ["is this better than the other one?", "which one is better than the second?"],
)
def test_bare_better_than_no_longer_hard_overrides(text):
    assert _programmatic_intent_override(text) is None


@pytest.mark.parametrize("text", ["why buy from kisna and not tanishq?", "kalyan vs kisna"])
def test_named_competitor_still_overrides(text):
    override = _programmatic_intent_override(text)
    assert override is not None and override[0] == "general"


# ── #8 custom jewellery: escapes sticky waits, respects support hours ──────


@pytest.mark.parametrize(
    "text",
    ["custom design chahiye", "custom ring banwana hai", "engraving chahiye"],
)
def test_custom_jewellery_escapes_a_sticky_wait(text):
    from kisna_chatbot.processors.classifier import _sticky_wait_escape_intent

    assert _sticky_wait_escape_intent(text) == "human_handoff"


def test_personal_no_longer_over_matches():
    # "personalised" is bespoke; "personally"/"person" must not hijack a search.
    assert _programmatic_intent_override("personalised ring for my wife") == (
        "human_handoff",
        0.95,
    )
    assert _programmatic_intent_override("show me rings personally picked") is None


def test_custom_jewellery_handoff_uses_support_hours():
    from unittest.mock import patch

    from kisna_chatbot.processors.classifier import _handle_custom_jewellery_handoff

    data, profile = {}, {"username": "Asha"}
    with patch(
        "kisna_chatbot.processors.classifier.build_expert_support_bot_response",
        return_value=[{"type": "text", "text": "OFFLINE + CALLBACK"}],
    ) as handler:
        _handle_custom_jewellery_handoff(data, profile, "919999999999")
    handler.assert_called_once()
    # Bespoke opener is tagged so it reaches the user in their language...
    assert data["bot_response"][0]["_compose"] == "custom_jewellery_handoff"
    # ...and the support handler's own response follows it.
    assert data["bot_response"][1]["text"] == "OFFLINE + CALLBACK"


# ── #3 GeneralAgent handoff must page a human ─────────────────────────────


def test_general_agent_handoff_calls_support_handler():
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import patch

    from kisna_chatbot.processors.general_agent import GeneralAgent

    data = {
        "phone_number": "919999999999",
        "client_id": "kisna",
        "messages": {"type": "text", "text": {"body": "do you do platinum resizing?"}},
        "user_profile": {"username": "Asha", "chat_history": []},
    }
    result = SimpleNamespace(
        live_agent_requested=True,
        message_text="Let me connect you with a Kisna representative.",
        provider=SimpleNamespace(value="openai"),
        model="gpt",
        latency_ms=1,
    )
    with patch(
        "kisna_chatbot.processors.general_agent.run_general_agent",
        return_value=result,
    ) as run, patch(
        "kisna_chatbot.processors.support_handler.build_expert_support_bot_response",
        return_value=[{"type": "text", "text": "PAGED"}],
    ) as handoff:
        run.return_value = result

        async def _fake(*a, **k):
            return result

        with patch(
            "kisna_chatbot.processors.general_agent.run_general_agent", new=_fake
        ):
            out = asyncio.run(GeneralAgent().process(data))
    handoff.assert_called_once()
    assert out["bot_response"] == [{"type": "text", "text": "PAGED"}]


# ── #3 save_to_mongo must not revert a mid-turn live-agent flag ────────────


def test_save_to_mongo_drops_falsy_live_agent_flags():
    from unittest.mock import MagicMock, patch

    from kisna_chatbot.database import db_utils

    captured = {}

    def _capture(_filter, update, **kwargs):
        captured["set"] = update["$set"]
        return {}

    with patch.object(db_utils.users, "find_one_and_update", side_effect=_capture), \
         patch.object(db_utils, "dual_write_chat_entries", MagicMock()):
        db_utils.save_to_mongo(
            {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "messages": {"type": "text", "text": {"body": "hi"}},
                "bot_response": [{"type": "text", "text": "hello"}],
                # Stale False loaded at turn start — request_live_agent may have
                # written True to Mongo since.
                "user_profile": {"chat_history": [], "live_agent_required": False},
            }
        )
    assert "live_agent_required" not in captured["set"]


def test_save_to_mongo_still_persists_a_raised_flag():
    from unittest.mock import MagicMock, patch

    from kisna_chatbot.database import db_utils

    captured = {}

    def _capture(_filter, update, **kwargs):
        captured["set"] = update["$set"]
        return {}

    with patch.object(db_utils.users, "find_one_and_update", side_effect=_capture), \
         patch.object(db_utils, "dual_write_chat_entries", MagicMock()):
        db_utils.save_to_mongo(
            {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "messages": {"type": "text", "text": {"body": "agent"}},
                "bot_response": [{"type": "text", "text": "connecting"}],
                "user_profile": {"chat_history": [], "live_agent_required": True},
            }
        )
    assert captured["set"]["live_agent_required"] is True


# ── #9 policy questions keep their KB answer ──────────────────────────────


@pytest.mark.parametrize(
    "text,should_reroute",
    [
        ("making charges kitna per gram?", False),
        ("EMI 10k per month possible?", False),
        ("show me something under 30k", True),
    ],
)
def test_policy_questions_are_not_hijacked_by_budget_regex(text, should_reroute):
    from kisna_chatbot.processors.classifier import _POLICY_TOPIC_RE
    from kisna_chatbot.processors.general_agent import _VARIANT_OR_BUDGET_RE

    reroutes = bool(_VARIANT_OR_BUDGET_RE.search(text)) and not bool(
        _POLICY_TOPIC_RE.search(text)
    )
    assert reroutes is should_reroute


# ── #6 quick-reply prompts get localized ──────────────────────────────────


def test_quick_reply_prompt_is_localized_but_titles_are_not():
    import asyncio
    from unittest.mock import AsyncMock, patch

    from kisna_chatbot.utils.reply_composer import localize_bot_responses

    data = {
        "phone_number": "919999999999",
        "client_id": "kisna",
        "user_profile": {"language": "gu"},
        "messages": {"type": "text", "text": {"body": "રિંગ"}},
        "bot_response": [
            {
                "type": "quickreply",
                "text": "Great! Who is it for?",
                "options": [{"title": "Female"}, {"title": "Male"}],
                "msgid": "wizard$gender",
                "_compose": "wizard_gender",
            }
        ],
    }
    with patch(
        "kisna_chatbot.utils.reply_composer.complete_chat",
        new_callable=AsyncMock,
        return_value="આ કોના માટે છે?",
    ):
        asyncio.run(localize_bot_responses(data))
    item = data["bot_response"][0]
    assert item["text"] == "આ કોના માટે છે?"
    # Titles are the only value carrier on the way back — must stay English.
    assert [o["title"] for o in item["options"]] == ["Female", "Male"]
    assert "_compose" not in item
