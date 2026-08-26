"""Product-title search: generic-noun stripping and spelling-variant retry.

Regression context: live testing proved two failures in how a free-text
product name becomes the `title` query param sent to Clara.

1. Generic jewellery nouns ("locket", "pendant", ...) sometimes stayed in the
   extracted title ("Shree locket") and sometimes didn't ("Shree") for
   word-for-word identical messages -- LLM extraction non-determinism, not a
   real signal. Fix: a deterministic FALLBACK rung that strips them, tried
   only after the literal title has already had its shot.
2. "Sri"/"Shri"/"Shree" are three standard spellings of the same word, but
   Clara's own catalogue has REAL, DIFFERENT products under more than one of
   them (Shree Pendant vs. Shri Lakshmi Pendant) -- so spelling can never be
   blindly rewritten, only tried as an ADDITIONAL attempt. Fix: a lazy,
   on-demand LLM call (mirroring confirm_reply_gate's fail-safe shape) that
   only fires once the literal + stripped title have both already failed.
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

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

from kisna_chatbot.models.service_list import ServiceList as SL  # noqa: E402
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    ProductSearchAgentV3,
    _build_fallback_strategies,
    _strip_generic_title_words,
    _suggest_title_spelling_variants,
)


def _product(pid="p1", title="Shree Pendant"):
    return {
        "_id": pid,
        "title": title,
        "price": {"variantPrice": 8637},
        "materialType": "diamond",
        "productType": {"category": {"name": "Pendants"}},
        "shipping": {"edd": 5},
        "seos": {"slug": "shree-pendant"},
        "mediaUrl": [{"isDefault": True, "image": "https://img.example/p.webp", "type": "image"}],
    }


def _profile(**extra):
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


class TestStripGenericTitleWords(unittest.TestCase):
    def test_strips_a_trailing_generic_noun(self):
        self.assertEqual(_strip_generic_title_words("Shree locket"), "Shree")

    def test_case_insensitive_match_original_casing_preserved(self):
        self.assertEqual(_strip_generic_title_words("Shree LOCKET"), "Shree")
        self.assertEqual(_strip_generic_title_words("SHREE locket"), "SHREE")

    def test_single_word_title_untouched(self):
        self.assertIsNone(_strip_generic_title_words("Shree"))
        self.assertIsNone(_strip_generic_title_words("locket"))

    def test_no_generic_word_present_returns_none(self):
        self.assertIsNone(_strip_generic_title_words("Nitara Shreeya"))

    def test_stripping_everything_returns_none_not_empty_string(self):
        # "pendant" and "locket" are both generic -- nothing distinctive left.
        self.assertIsNone(_strip_generic_title_words("pendant locket"))


class TestBuildFallbackStrategiesTitleStripped(unittest.TestCase):
    def test_adds_title_stripped_rung_right_after_full(self):
        labels = [
            label
            for _ent, _note, label in _build_fallback_strategies(
                {"title": "Shree locket", "category": "pendant"}
            )
        ]
        self.assertEqual(labels[0], "full")
        self.assertEqual(labels[1], "title_stripped")

    def test_title_stripped_rung_carries_the_stripped_title(self):
        strategies = _build_fallback_strategies({"title": "Shree locket", "category": "pendant"})
        stripped = next(ent for ent, _note, label in strategies if label == "title_stripped")
        self.assertEqual(stripped["title"], "Shree")

    def test_no_generic_noun_no_extra_rung(self):
        labels = [
            label
            for _ent, _note, label in _build_fallback_strategies(
                {"title": "Shreeya", "category": "ring"}
            )
        ]
        self.assertNotIn("title_stripped", labels)

    def test_other_constraints_carried_through_unchanged(self):
        strategies = _build_fallback_strategies(
            {
                "title": "Shree locket",
                "category": "pendant",
                "material_type": "diamond",
                "max_price": 30000,
                "fulfillment": "ready",
            }
        )
        stripped = next(ent for ent, _note, label in strategies if label == "title_stripped")
        self.assertEqual(stripped["material_type"], "diamond")
        self.assertEqual(stripped["max_price"], 30000)
        self.assertEqual(stripped["fulfillment"], "ready")


class TestSuggestTitleSpellingVariants(unittest.TestCase):
    def test_parses_comma_separated_list(self):
        async def _run():
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                return_value="Shri, Sri",
            ):
                return await _suggest_title_spelling_variants("Shree")

        self.assertEqual(asyncio.run(_run()), ["Shri", "Sri"])

    def test_none_response_returns_empty_list(self):
        async def _run():
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                return_value="none",
            ):
                return await _suggest_title_spelling_variants("Solitaire")

        self.assertEqual(asyncio.run(_run()), [])

    def test_capped_at_three(self):
        async def _run():
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                return_value="Shri, Sri, Shree, Shreee",
            ):
                return await _suggest_title_spelling_variants("Shree")

        self.assertEqual(len(asyncio.run(_run())), 3)

    def test_any_failure_returns_empty_list_never_raises(self):
        async def _run():
            with patch(
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("provider down"),
            ):
                return await _suggest_title_spelling_variants("Shree")

        self.assertEqual(asyncio.run(_run()), [])


class TestExecuteSearchSplicesVariants(unittest.TestCase):
    """End-to-end through the real fallback loop in _execute_search."""

    def test_llm_variant_recovers_a_match_the_literal_title_missed(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "user_profile": _profile(),
            }
            entities = {
                "category": "pendant",
                "title": "Shree locket",
                "max_price": 30000,
            }

            async def fake_search(**kwargs):
                title = (kwargs.get("title") or "")
                if title.lower() == "shri":
                    return {"products": [_product(title="Shri Lakshmi Pendant")], "total_count": 1, "page": 1}
                return {"products": [], "total_count": 0, "page": 1}

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ), patch(
                "kisna_chatbot.processors.product_search_agent_v3._suggest_title_spelling_variants",
                new_callable=AsyncMock,
                return_value=["Shri"],
            ) as variant_mock:
                result = await agent._execute_search(
                    data, "919999999999", entities, query_label="test", confirm=False
                )

            self.assertIn("bot_response", result)
            variant_mock.assert_awaited_once()
            products = data["user_profile"].get("last_search_products") or []
            self.assertTrue(products)
            self.assertEqual(products[0]["title"], "Shri Lakshmi Pendant")

        asyncio.run(_run())

    def test_llm_variant_only_called_once_per_search(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "user_profile": _profile(),
            }
            entities = {"category": "pendant", "title": "Shree locket"}

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": [], "total_count": 0, "page": 1},
            ), patch(
                "kisna_chatbot.processors.product_search_agent_v3._suggest_title_spelling_variants",
                new_callable=AsyncMock,
                return_value=[],
            ) as variant_mock:
                await agent._execute_search(
                    data, "919999999999", entities, query_label="test", confirm=False
                )

            variant_mock.assert_awaited_once()

        asyncio.run(_run())

    def test_no_title_never_calls_variant_lookup(self):
        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "user_profile": _profile(),
            }
            entities = {"category": "ring"}

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                return_value={"products": [_product(pid="r1", title="Gold Ring")], "total_count": 1, "page": 1},
            ), patch(
                "kisna_chatbot.processors.product_search_agent_v3._suggest_title_spelling_variants",
                new_callable=AsyncMock,
            ) as variant_mock:
                await agent._execute_search(
                    data, "919999999999", entities, query_label="test", confirm=False
                )

            variant_mock.assert_not_awaited()

        asyncio.run(_run())

    def test_variant_lookup_failure_still_reaches_category_only(self):
        """No regression: an LLM outage must not break the existing ladder."""

        async def _run():
            agent = ProductSearchAgentV3()
            data = {
                "phone_number": "919999999999",
                "client_id": "kisna",
                "user_profile": _profile(),
            }
            entities = {
                "category": "pendant",
                "title": "Sri locket",
                "material_type": "gemstone",
                "max_price": 20000,
            }

            async def fake_search(**kwargs):
                # Only the broadest, category-only call succeeds -- exactly
                # the shape of the real failing transcripts before this fix.
                if kwargs.get("materialType") or kwargs.get("title") or kwargs.get("maxPrice"):
                    return {"products": [], "total_count": 0, "page": 1}
                return {"products": [_product(pid="c1", title="Some Pendant")], "total_count": 500, "page": 1}

            with patch(
                "kisna_chatbot.processors.product_search_agent_v3.search_products",
                new_callable=AsyncMock,
                side_effect=fake_search,
            ), patch(
                # The real, unmocked _suggest_title_spelling_variants must itself
                # absorb this and return [] -- exercising its actual fail-safe
                # try/except, not a mock standing in for it.
                "kisna_chatbot.ai.factory.complete_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("provider down"),
            ):
                result = await agent._execute_search(
                    data, "919999999999", entities, query_label="test", confirm=False
                )

            self.assertIn("bot_response", result)
            products = data["user_profile"].get("last_search_products") or []
            self.assertTrue(products)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
