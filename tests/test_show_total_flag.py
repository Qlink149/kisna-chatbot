"""F2: the product-carousel CTA prefixes "Showing N of TOTAL" whenever the
carousel is a partial page of a larger catalogue result (C1: client saw 3 of
81 matches with no indication more existed). Unconditional -- no flag."""

import os
import unittest

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

from kisna_chatbot.processors.product_search_agent_v3 import (  # noqa: E402
    _build_search_success_response,
)

_PRODUCT = {
    "_id": "p1",
    "title": "Gold Ring",
    "price": {"variantPrice": 45000},
    "materialType": "gold",
    "shipping": {"edd": 5},
    "seos": {"slug": "gold-ring"},
    "mediaUrl": [
        {"isDefault": True, "image": "https://img.example/ring.webp", "type": "image"}
    ],
}
_ENTITIES = {
    "category": "ring",
    "material_type": "gold",
    "min_price": None,
    "max_price": None,
    "title": None,
    "city": None,
    "pincode": None,
}


def _cta_text(response: list[dict]) -> str:
    cta = [r for r in response if r["type"] == "cta_url"]
    assert len(cta) == 1, response
    return cta[0]["text"]


class ShowTotalTests(unittest.TestCase):
    def test_adds_showing_n_of_total(self) -> None:
        response = _build_search_success_response(
            [_PRODUCT], total_count=81, page=1, entities=_ENTITIES, display_total=81
        )
        self.assertEqual(
            _cta_text(response),
            "Showing 1 of 81. Want to explore more? See the full collection 👇",
        )

    def test_no_display_total_keeps_default_copy(self) -> None:
        response = _build_search_success_response(
            [_PRODUCT], total_count=1, page=1, entities=_ENTITIES
        )
        self.assertEqual(_cta_text(response), "Want to explore more? See the full collection 👇")

    def test_display_total_not_greater_than_shown_keeps_default_copy(self) -> None:
        # All results already shown (display_total == images_sent) -- nothing more to point at.
        response = _build_search_success_response(
            [_PRODUCT], total_count=1, page=1, entities=_ENTITIES, display_total=1
        )
        self.assertEqual(_cta_text(response), "Want to explore more? See the full collection 👇")

    def test_cta_still_untagged_response_compliant(self) -> None:
        response = _build_search_success_response(
            [_PRODUCT], total_count=81, page=1, entities=_ENTITIES, display_total=81
        )
        cta = [r for r in response if r["type"] == "cta_url"][0]
        self.assertEqual(cta.get("_compose"), "search_explore_more")


if __name__ == "__main__":
    unittest.main()
