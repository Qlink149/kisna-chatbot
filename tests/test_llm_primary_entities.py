"""LLM-primary entity extraction: structured regex + semantic LLM."""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from kisna_chatbot.processors.entity_extractor import (  # noqa: E402
    combine_search_entities,
    extract_entities,
    extract_structured_fields,
    merge_llm_and_regex_entities,
)


class LlmPrimaryEntityTests(unittest.TestCase):
    def test_structured_fields_price_only(self):
        structured = extract_structured_fields("gold rings under 50k")
        self.assertEqual(structured["max_price"], 50000)
        self.assertIsNone(structured.get("category"))
        self.assertIsNone(structured.get("title"))

    def test_combine_ignores_regex_category(self):
        llm = {"category": "ring", "material_type": "gold", "title": None}
        regex_only = extract_entities("gold rings under 50k")
        combined = combine_search_entities(llm, extract_structured_fields("gold rings under 50k"))
        self.assertEqual(combined["category"], "ring")
        self.assertEqual(combined["max_price"], 50000)
        self.assertIsNone(combined.get("title"))
        self.assertEqual(regex_only.get("category"), "ring")
        bare_combine = combine_search_entities({}, extract_structured_fields("gold rings under 50k"))
        self.assertIsNone(bare_combine.get("category"))

    def test_combine_llm_title_not_from_regex(self):
        regex_full = extract_entities("Show me Nitara ring")
        combined = combine_search_entities(
            {"title": "elysia", "category": "ring"},
            extract_structured_fields("Show me Nitara ring"),
        )
        self.assertEqual(combined["title"], "elysia")
        self.assertIsNone(regex_full.get("title"))

    def test_merge_alias_matches_combine(self):
        llm = {"category": "earring", "max_price": None}
        regex = extract_entities("earrings under 30k")
        merged = merge_llm_and_regex_entities(llm, regex)
        combined = combine_search_entities(llm, extract_structured_fields("earrings under 30k"))
        self.assertEqual(merged["category"], combined["category"])
        self.assertEqual(merged["max_price"], combined["max_price"])
        self.assertIsNone(merged.get("title"))


if __name__ == "__main__":
    unittest.main()
