"""The two regressions the final end-to-end QA sweep found in `4c8a5e6`.

Both are the same shape as every other defect in this codebase: a layer that
had already produced the right answer, and a later layer that discarded it.

R1  `_location_entities` merged the extractor LLM's `city` over the regex
    layer's. The regex canonicalises through `_CITY_NAME_MAP` ("bengaluru" ->
    "Bangalore"); the model answers with the customer's own spelling. Store
    matching compares against the catalogue's `address.city.name`, so
    "any store in bengaluru?" replied "No KISNA stores found near you" with
    four Bangalore branches in the catalogue -- and the same for Madras,
    Mysuru and Gurgaon. Bombay and Calcutta survived only because the model
    happens to canonicalise those two itself.

R2  The spoken product answer was tagged `_compose: "product_info"` with no
    pinned values, so a Hindi customer was told about "Waida अंगूठी" and
    "झानवी अंगूठी" -- names that match nothing on the card, on kisna.com or in
    their order. Product cards were already protected (`_bold_titles` recovers
    a card's title because a card always bolds it); a spoken answer does not
    reliably bold, so the builder has to declare the names itself.
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
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

from kisna_chatbot.main import app  # noqa: F401,E402
from kisna_chatbot.processors.ad_flow_agent import _location_entities  # noqa: E402
from kisna_chatbot.processors.entity_extractor import canonical_city  # noqa: E402
from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    _title_pins,
)
from kisna_chatbot.utils.reply_composer import localize_bot_responses  # noqa: E402


class CanonicalCityTests(unittest.TestCase):
    def test_alias_spellings_resolve_to_the_catalogue_name(self):
        for spelling, expected in (
            ("Bengaluru", "Bangalore"),
            ("bengaluru", "Bangalore"),
            ("  Madras ", "Chennai"),
            ("Mysuru", "Mysore"),
            ("Gurgaon", "Gurugram"),
            ("Bombay", "Mumbai"),
            ("Calcutta", "Kolkata"),
        ):
            self.assertEqual(canonical_city(spelling), expected, spelling)

    def test_unknown_and_empty_names_stay_unknown(self):
        # None means "the map has no opinion" -- the caller decides what to
        # keep. It must never invent a canonical name.
        self.assertIsNone(canonical_city("Atlantis"))
        self.assertIsNone(canonical_city(""))
        self.assertIsNone(canonical_city(None))


def _merged_city(message: str, llm_city: str | None) -> str | None:
    with patch(
        "kisna_chatbot.processors.entity_extractor.extract_entities_with_llm",
        new_callable=AsyncMock,
        return_value={"city": llm_city, "state": None},
    ):
        merged = asyncio.run(_location_entities({"client_id": "kisna"}, message))
    return merged.get("city")


class LocationMergeTests(unittest.TestCase):
    def test_model_surface_spelling_is_canonicalised(self):
        # The exact live failure: the regex said Bangalore, the model said
        # Bengaluru, and the model's answer overwrote it.
        self.assertEqual(
            _merged_city("any store in bengaluru?", "Bengaluru"), "Bangalore"
        )
        self.assertEqual(
            _merged_city("do you have a showroom in madras", "Madras"), "Chennai"
        )

    def test_city_the_map_does_not_know_keeps_what_the_regex_resolved(self):
        # A hallucinated or unmappable answer must not erase a real match.
        self.assertEqual(_merged_city("store in mumbai", "Some Place"), "Mumbai")

    def test_the_model_still_wins_where_the_regex_is_blind(self):
        # Native script is the whole reason the model was put in front: the
        # Latin city list cannot see it, so its answer must survive.
        self.assertEqual(_merged_city("मुंबई में स्टोर है क्या?", "Mumbai"), "Mumbai")
        self.assertEqual(
            _merged_city("ಬೆಂಗಳೂರಿನಲ್ಲಿ ಅಂಗಡಿ ಇದೆಯೇ?", "Bengaluru"), "Bangalore"
        )


class ProductNamePinTests(unittest.TestCase):
    def test_title_pins_reads_one_product_and_a_shown_set(self):
        self.assertEqual(_title_pins({"title": "Waida Ring"}), ("Waida Ring",))
        self.assertEqual(
            _title_pins([{"title": "Jhanvi Ring"}, {"name": "Lena Ring"}, {}]),
            ("Jhanvi Ring", "Lena Ring"),
        )
        self.assertEqual(_title_pins(None), ())

    def test_declared_names_reach_the_composer(self):
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {"language": "hi"},
            "messages": {"type": "text", "text": {"body": "साइज़ 14 है क्या?"}},
            "bot_response": [
                {
                    "type": "text",
                    "text": "Yes, Waida Ring is size 14.",
                    "_compose": "product_info",
                    "_pin": ("Waida Ring",),
                }
            ],
        }
        with patch(
            "kisna_chatbot.utils.reply_composer.compose",
            new_callable=AsyncMock,
            return_value="हाँ, Waida Ring साइज़ 14 है।",
        ) as composed:
            asyncio.run(localize_bot_responses(data))
        self.assertEqual(composed.await_args.kwargs["pin"], ("Waida Ring",))
        item = data["bot_response"][0]
        self.assertNotIn("_pin", item)
        self.assertNotIn("_compose", item)

    def test_pin_is_stripped_even_when_nothing_is_tagged(self):
        # _pin is ours, not WhatsApp's. An untagged item must not ship it.
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {"language": "hi"},
            "messages": {"type": "text", "text": {"body": "hi"}},
            "bot_response": [
                {"type": "text", "text": "Waida Ring", "_pin": ("Waida Ring",)}
            ],
        }
        asyncio.run(localize_bot_responses(data))
        self.assertNotIn("_pin", data["bot_response"][0])

    def test_a_tagged_reply_without_declared_names_pins_nothing(self):
        # The recap bolds the material, the category and the budget -- all of
        # which MUST translate. Only the builder knows which bold segments are
        # identifiers, so nothing is pinned by default.
        data = {
            "phone_number": "919999999999",
            "client_id": "kisna",
            "user_profile": {"language": "hi"},
            "messages": {"type": "text", "text": {"body": "अंगूठी"}},
            "bot_response": [
                {
                    "type": "text",
                    "text": "Looking for *gold rings under ₹20,000*.",
                    "_compose": "search_recap",
                }
            ],
        }
        with patch(
            "kisna_chatbot.utils.reply_composer.compose",
            new_callable=AsyncMock,
            return_value="...",
        ) as composed:
            asyncio.run(localize_bot_responses(data))
        self.assertEqual(composed.await_args.kwargs["pin"], ())


if __name__ == "__main__":
    unittest.main()
