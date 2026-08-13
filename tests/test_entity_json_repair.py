"""The extractor must never lose an entire extraction to malformed JSON.

Found by replaying real user messages through the production pipeline: the
model was copying the "...nulls" shorthand out of its own prompt examples:

    {"category":"ring","material_type":"gold","gender":"women",...nulls}

That is invalid JSON. _parse_entity_json raised, extract_entities_with_llm
swallowed the error and returned {}, and the search silently fell back to the
Latin-only regex — so native-script and romanized messages lost every filter
and the funnel re-asked for a category the user had already given.

The batched regression suite never caught it because that runner sets
response_format={"type":"json_object"}, which forces valid JSON. Production's
complete_chat does not.
"""

import os
import unittest

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
    _parse_entity_json,
)
from kisna_chatbot.prompts.classifier_kisna import (  # noqa: E402
    kisna_entity_extractor,
)


class EntityJsonRepairTests(unittest.TestCase):
    def test_ellipsis_shorthand_is_repaired_not_discarded(self):
        raw = '{"category":"ring","material_type":"gold","gender":"women",...nulls}'
        parsed = _parse_entity_json(raw)
        self.assertEqual(parsed["category"], "ring")
        self.assertEqual(parsed["material_type"], "gold")
        self.assertEqual(parsed["gender"], "women")

    def test_other_shorthand_spellings(self):
        for raw in (
            '{"category":"ring",...all others null}',
            '{"category":"ring", ...all other filters null}',
            '{"category":"ring",...all null}',
            '{"min_price":50000,"max_price":50000,...nulls}',
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_parse_entity_json(raw)["category"]
                                 if "category" in raw else 50000,
                                 "ring" if "category" in raw else 50000)

    def test_trailing_comma_is_repaired(self):
        self.assertEqual(
            _parse_entity_json('{"category":"ring","max_price":20000,}')["max_price"],
            20000,
        )

    def test_markdown_fences_still_stripped(self):
        raw = '```json\n{"category":"necklace"}\n```'
        self.assertEqual(_parse_entity_json(raw)["category"], "necklace")

    def test_valid_json_is_untouched(self):
        parsed = _parse_entity_json('{"category":"chain","karat":"18KT"}')
        self.assertEqual(parsed, {"category": "chain", "karat": "18KT"})

    def test_genuinely_broken_json_still_raises(self):
        """Repair must not mask real breakage — the caller logs and falls back."""
        import json

        with self.assertRaises(json.JSONDecodeError):
            _parse_entity_json("this is not json at all {")

    def test_prompt_no_longer_teaches_the_shorthand(self):
        """Root cause: the examples themselves showed invalid JSON.

        Scoped to lines that look like JSON — the prose instruction telling the
        model never to emit "...nulls" naturally contains the string.
        """
        import re

        leaks = [
            line.strip()
            for line in kisna_entity_extractor.splitlines()
            if ("{" in line or "}" in line)
            and re.search(r"\.\.\.\s*[a-z_ ]*null", line, re.I)
        ]
        self.assertEqual(
            leaks, [], f"extractor prompt still shows invalid JSON: {leaks}"
        )
        self.assertIn("strictly valid JSON", kisna_entity_extractor)

    def test_every_json_example_in_the_prompt_parses(self):
        """Stronger than the shorthand check: each example must be real JSON."""
        import json
        import re

        blocks = re.findall(r"\{[^{}]*\}", kisna_entity_extractor)
        unparseable = []
        for block in blocks:
            # Schema blocks use "a|b|c" pseudo-types and <int> placeholders;
            # only worked examples are expected to be literal JSON.
            if "|" in block or "<" in block:
                continue
            try:
                json.loads(block)
            except json.JSONDecodeError:
                unparseable.append(block[:90])
        self.assertEqual(
            unparseable, [], f"prompt contains non-JSON examples: {unparseable}"
        )


if __name__ == "__main__":
    unittest.main()
