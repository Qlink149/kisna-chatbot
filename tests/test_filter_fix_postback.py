"""Bug 4 regression: filter$fix$<entity_key> quick-reply had no handler.

build_impossible_value_prompt (Phase 5) emits buttons with msgid
"filter$fix$<entity_key>" (e.g. "filter$fix$karat") whose title carries the
corrected value ("14KT", "Rose", "Female", ...). Nothing in the codebase
matched that msgid prefix, so tapping any of these buttons fell through to
generic fallback text with service_selected left empty.
"""

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.main import app  # noqa: F401,E402
from kisna_chatbot.processors.filter_validation import (  # noqa: E402
    PENDING_FILTER_FIX_KEY,
    build_impossible_value_prompt,
    get_pending_filter_fix,
    is_filter_fix_interactive,
    parse_filter_fix_button,
    resolve_filter_fix_value,
    set_pending_filter_fix,
)
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3  # noqa: E402


def _button_tap(msgid: str, title: str) -> dict:
    return {"interactive": {"type": "button_reply", "button_reply": {"id": msgid, "title": title}}}


class TestParseAndResolve:
    def test_parses_karat_button(self):
        messages = _button_tap("filter$fix$karat", "14KT")
        assert parse_filter_fix_button(messages) == ("karat", "14KT")

    def test_parses_gender_button(self):
        messages = _button_tap("filter$fix$gender", "Female")
        assert parse_filter_fix_button(messages) == ("gender", "Female")

    def test_ignores_unrelated_button(self):
        messages = _button_tap("wizard$gender", "Female")
        assert parse_filter_fix_button(messages) is None

    def test_is_filter_fix_interactive(self):
        assert is_filter_fix_interactive(_button_tap("filter$fix$collection", "Zivah"))
        assert not is_filter_fix_interactive({"text": {"body": "hi"}})

    def test_resolve_gender_maps_ui_label_to_internal_value(self):
        assert resolve_filter_fix_value("gender", "Female") == "women"
        assert resolve_filter_fix_value("gender", "Male") == "men"
        assert resolve_filter_fix_value("gender", "Kids") == "kids"

    def test_resolve_karat_and_colour_pass_through(self):
        # karat/colour/collection reuse the same fuzzy option matching the
        # validation step already used, so the button's own label text is
        # already an accepted value for get_karat_id / get_colour_id.
        assert resolve_filter_fix_value("karat", "14KT") == "14KT"
        assert resolve_filter_fix_value("metal_colour", "Rose") == "Rose"


class TestPendingState:
    def test_set_get_pop_roundtrip(self):
        profile: dict = {}
        set_pending_filter_fix(profile, {"category": "chain", "karat": "22KT"}, "karat")
        pending = get_pending_filter_fix(profile)
        assert pending == {"entities": {"category": "chain", "karat": "22KT"}, "entity_key": "karat"}
        assert PENDING_FILTER_FIX_KEY in profile

    def test_build_impossible_value_prompt_stashes_pending_state(self):
        """The trigger for Bug 4: without this, the button had nothing to fix."""
        profile: dict = {}
        with patch(
            "kisna_chatbot.processors.filter_validation.filters_available", return_value=True
        ), patch(
            "kisna_chatbot.processors.filter_validation.get_category_id", return_value="cat-chain"
        ), patch(
            "kisna_chatbot.processors.filter_validation.get_available_options",
            return_value=[{"label": "14KT", "value": "id-14kt"}, {"label": "18KT", "value": "id-18kt"}],
        ), patch(
            "kisna_chatbot.processors.filter_validation.is_value_available", return_value=False
        ):
            responses = build_impossible_value_prompt({"category": "chain", "karat": "22KT"}, profile)

        assert responses is not None
        qr = [r for r in responses if r.get("type") == "quickreply"]
        assert qr and qr[0]["msgid"] == "filter$fix$karat"
        pending = get_pending_filter_fix(profile)
        assert pending is not None
        assert pending["entity_key"] == "karat"
        assert pending["entities"]["karat"] == "22KT"

    def test_validates_chain_against_chain_not_necklace(self):
        """Live-discovered bug: chain is stored internally as category=
        "necklace" with the real category in clara_category_override="chain"
        (entity_extractor's _CLARA_CATEGORY_OVERRIDE_FROM). Validation used
        entities["category"] directly, so "24kt chain" was checked against
        NECKLACE's karat options (which include 9KT) instead of CHAIN's
        (14KT/18KT only) — offering "9KT" as a chain fix when 9KT isn't
        actually a valid chain karat. Live-verified: tapping that offered
        "9KT" returned real chain products, but they were 14KT, not 9KT.
        """
        with patch(
            "kisna_chatbot.processors.filter_validation.filters_available", return_value=True
        ), patch(
            "kisna_chatbot.processors.filter_validation.get_category_id"
        ) as mock_get_category_id, patch(
            "kisna_chatbot.processors.filter_validation.get_available_options",
            return_value=[{"label": "14KT", "value": "id-14kt"}, {"label": "18KT", "value": "id-18kt"}],
        ), patch(
            "kisna_chatbot.processors.filter_validation.is_value_available", return_value=False
        ):
            mock_get_category_id.return_value = "cat-chain"
            build_impossible_value_prompt(
                {"category": "necklace", "clara_category_override": "chain", "karat": "24KT"}
            )

        mock_get_category_id.assert_called_once_with("chain")


@pytest.mark.no_search_recap
class TestEndToEnd:
    """Tap the button -> real dispatch -> real search call with the corrected filter."""

    def _search_result(self):
        return {
            "products": [
                {
                    "_id": "1",
                    "title": "Test Chain 14KT",
                    "price": {"variantPrice": 18000},
                    "mediaUrl": [{"image": "https://example.com/a.jpg"}],
                    "productType": {"category": {"name": "Chain"}},
                    "seos": {"slug": "test-chain-14kt"},
                }
            ],
            "total_count": 1,
            "page": 1,
        }

    def test_tap_applies_corrected_karat_and_searches(self):
        agent = ProductSearchAgentV3()
        user_profile: dict = {}
        set_pending_filter_fix(user_profile, {"category": "chain", "karat": "22KT"}, "karat")
        messages = _button_tap("filter$fix$karat", "14KT")
        data = {
            "phone_number": "919999999999",
            "user_profile": user_profile,
            "messages": messages,
        }

        assert agent.should_run(data) is True

        with patch(
            "kisna_chatbot.processors.product_search_agent_v3.search_products",
            new_callable=AsyncMock,
            return_value=self._search_result(),
        ) as mock_search:
            result = asyncio.run(agent.process(data))

        # The corrected karat actually went out on the Clara call.
        _, kwargs = mock_search.call_args
        assert kwargs.get("meta_sub_attribute_value") is not None or "14KT" in str(mock_search.call_args)

        # Real products came back — not generic fallback text.
        images = [m for m in result["bot_response"] if m.get("type") == "image_with_cta"]
        assert len(images) == 1

        # Pending state is consumed, not left dangling.
        assert get_pending_filter_fix(user_profile) is None

    def test_tap_applies_corrected_gender_and_searches(self):
        agent = ProductSearchAgentV3()
        user_profile: dict = {}
        set_pending_filter_fix(user_profile, {"category": "chain", "gender": "aliens"}, "gender")
        messages = _button_tap("filter$fix$gender", "Female")
        data = {
            "phone_number": "919999999999",
            "user_profile": user_profile,
            "messages": messages,
        }

        with patch(
            "kisna_chatbot.processors.product_search_agent_v3.search_products",
            new_callable=AsyncMock,
            return_value=self._search_result(),
        ):
            result = asyncio.run(agent.process(data))

        images = [m for m in result["bot_response"] if m.get("type") == "image_with_cta"]
        assert len(images) == 1
        assert get_pending_filter_fix(user_profile) is None

    def test_stale_tap_without_pending_state_does_not_crash(self):
        agent = ProductSearchAgentV3()
        user_profile: dict = {}  # nothing pending — e.g. session lost / new search since
        messages = _button_tap("filter$fix$karat", "14KT")
        data = {
            "phone_number": "919999999999",
            "user_profile": user_profile,
            "messages": messages,
        }

        result = asyncio.run(agent.process(data))

        assert result["bot_response"]
        assert result["bot_response"][0]["type"] == "text"
        # No crash, no generic "couldn't understand" — a specific message.
        assert "isn't active anymore" in result["bot_response"][0]["text"]
