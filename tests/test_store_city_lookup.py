"""Store lookup by city name.

Regression for a real tester session (phone 916376925843, 2026-08-21):
"Do you have a store in Udaipur/Patna/Agra/Bareilly?" all fell back to
"please share your pincode" even though Kisna has a real store in every
one of those cities -- confirmed by then typing the matching pincode,
which worked. Root cause traced to two separate bugs:

1. _CITIES only listed 17 major metros, so any other real city (the vast
   majority of Kisna's actual 99-city footprint, confirmed live via
   GET /api/v1/clara/stores?pageSize=200) never even attempted a lookup.

2. Even for a city that DID resolve, get_stores(city=...) has no real
   city filter to call (?city=X 400s) and falls back to Clara's `name`
   text-search param, which matches broadly and pulls in wrong-city
   stores as false positives -- confirmed live: name=Agra surfaced
   "Agrasen Chowk - Bilaspur", and name=Patna returned 7 Visakhapatnam
   stores alongside the 3 real Patna ones. Fixed by filtering results
   against the store's own real address.city.name field.
"""

import os
import unittest

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
from kisna_chatbot.processors.ad_flow_agent import (  # noqa: E402
    _filter_cached_stores,
    _store_city,
)
from kisna_chatbot.processors.entity_extractor import _extract_city  # noqa: E402


class CityExtractionCoverageTests(unittest.TestCase):
    def test_previously_unsupported_real_cities_now_resolve(self):
        for text, expected in (
            ("Do you have a store in Udaipur?", "Udaipur"),
            ("Do you have a store in Patna?", "Patna"),
            ("Do you have a store in Agra?", "Agra"),
            ("You have a store in Bareilly?", "Bareilly"),
        ):
            self.assertEqual(_extract_city(text), expected, text)

    def test_case_insensitive_on_raw_unnormalized_text(self):
        # Regression: a bare call on raw, capitalized user text ("Mumbai")
        # used to return None -- only worked when the caller had already
        # lowercased the string first.
        self.assertEqual(_extract_city("Do you have a store in Mumbai?"), "Mumbai")
        self.assertEqual(_extract_city("do you have a store in mumbai?"), "Mumbai")

    def test_colloquial_aliases_resolve_to_the_real_city(self):
        self.assertEqual(_extract_city("Do you have a Store in Bombay"), "Mumbai")
        self.assertEqual(_extract_city("store in Bengaluru?"), "Bangalore")
        self.assertEqual(_extract_city("store in Calcutta?"), "Kolkata")

    def test_multiword_and_hyphenated_city_names(self):
        self.assertEqual(_extract_city("store in Delhi?"), "Delhi-NCR")
        self.assertEqual(_extract_city("store in Sri Ganganagar?"), "Sri Ganganagar")

    def test_city_with_no_real_store_still_recognized(self):
        # Recognized (so the bot attempts a real lookup instead of
        # reflexively asking for a pincode) even though Kisna has no store
        # there today -- the zero-results reply is the honest answer.
        self.assertEqual(_extract_city("store in Goa?"), "Goa")
        self.assertEqual(_extract_city("store in Mangalore?"), "Mangalore")

    def test_unrecognized_text_returns_none(self):
        self.assertIsNone(_extract_city("I need a diamond ring"))


class StoreCityFieldTests(unittest.TestCase):
    def test_store_city_reads_dict_shaped_address(self):
        store = {"address": {"city": {"name": "Agra"}}}
        self.assertEqual(_store_city(store), "Agra")

    def test_store_city_reads_string_shaped_city(self):
        store = {"address": {"city": "Agra"}}
        self.assertEqual(_store_city(store), "Agra")

    def test_store_city_handles_missing_address(self):
        self.assertEqual(_store_city({}), "")


class CityFalsePositiveFilterTests(unittest.TestCase):
    """The exact real-data shape confirmed live: name=Agra and name=Patna
    both pull in wrong-city stores that must never reach the user."""

    def test_agra_query_drops_the_bilaspur_false_positive(self):
        cached = {
            "stores": [
                {
                    "name": "Agrasen Chowk - Bilaspur - Chattisgarh",
                    "address": {"city": {"name": "Bilaspur"}},
                },
                {
                    "name": "MG Road - Agra - Uttar Pradesh",
                    "address": {"city": {"name": "Agra"}},
                },
            ]
        }
        result = _filter_cached_stores(cached, city="Agra")
        self.assertEqual(len(result["stores"]), 1)
        self.assertIn("Agra", result["stores"][0]["name"])
        self.assertNotIn("Bilaspur", str(result["stores"]))

    def test_patna_query_drops_visakhapatnam_false_positives(self):
        cached = {
            "stores": [
                {"name": "Madhurawada - Visakhapatnam", "address": {"city": {"name": "Visakhapatnam"}}},
                {"name": "Kankarbagh - Patna - Bihar", "address": {"city": {"name": "Patna"}}},
                {"name": "Patna City - Patna - Bihar", "address": {"city": {"name": "Patna"}}},
            ]
        }
        result = _filter_cached_stores(cached, city="Patna")
        self.assertEqual(len(result["stores"]), 2)
        self.assertTrue(all("Patna" in s["name"] for s in result["stores"]))

    def test_city_filter_is_exact_not_substring(self):
        # Guards against a regression back to substring matching, which is
        # exactly what caused the false positives above.
        cached = {
            "stores": [
                {"name": "X", "address": {"city": {"name": "New Delhi"}}},
                {"name": "Y", "address": {"city": {"name": "Delhi-NCR"}}},
            ]
        }
        result = _filter_cached_stores(cached, city="Delhi-NCR")
        self.assertEqual(len(result["stores"]), 1)
        self.assertEqual(result["stores"][0]["name"], "Y")


if __name__ == "__main__":
    unittest.main()
