"""KISNA website filter vocabulary for catalogue deep-links.

Every segment in a /jewellery/<a>+<b>+<c> URL is a filter token the site
already publishes. Category, karat, colour, gender, availability and
collection slugs come verbatim from Clara's /filters payload (bundled at
integrations/data/clara_filters_snapshot.json); price bands and material are
not in that payload and are transcribed from the site's own filter sidebar.

Nothing here derives a slug from an entity value — the site does not
pluralise ("Necklace" is `necklace`, "Rings" is `rings`), so guessing produced
dead links. An unrecognised value returns None and its segment is dropped:
a URL with fewer filters still works, a URL with a fake filter does not.
"""

from __future__ import annotations

import re
from typing import Any

from kisna_chatbot.processors.entity_extractor import (
    PRICE_BANDS,
    _OPEN_BAND_FLOOR,
)

# Internal category -> site slug(s). Values are the `slug` field of the
# /filters `categories` facet; tests/test_catalogue_url.py asserts they still
# match the bundled snapshot. "bangle_bracelet" is the bot's own union
# category and maps onto both real filters, the way the site stacks
# multi-select categories (necklace+rings+bangles).
CATEGORY_SLUGS: dict[str, tuple[str, ...]] = {
    "ring": ("rings",),
    "solitaire": ("solitaire",),
    "earring": ("earrings",),
    "necklace": ("necklace",),
    "necklace_set": ("necklace-sets",),
    "pendant": ("pendants",),
    "pendant_set": ("pendant-sets",),
    "bangle": ("bangles",),
    "bracelet": ("bracelets",),
    "bangle_bracelet": ("bangles", "bracelets"),
    "mangalsutra": ("mangalsutra",),
    "mangalsutra_bracelet": ("mangalsutra-bracelets",),
    "maang_tikka": ("maang-tikka",),
    "nosewear": ("nose-wear",),
    "nose_wear": ("nose-wear",),
    "watchwear": ("watch-wear",),
    "watch_wear": ("watch-wear",),
    "chain": ("chain",),
    "souvenir": ("souvenir",),
    # anklet / hathphool / kamarband have no filter on the site (and no Clara
    # category either — see _CLARA_UNSUPPORTED_CATEGORIES), "any" is the
    # absence of a category. All four drop their segment.
}

# The site's price sidebar, in the same order as PRICE_BANDS. Slugs for the
# lakh bands and the open top are client-confirmed from live URLs
# (/jewellery/diamond+1l-to-1.5l, +1.5l-to-2l, +80k-to-1l, +above-2l).
_BAND_SLUGS: dict[tuple[float, float], str] = {
    (0.0, 10000.0): "under-10k",
    (10000.0, 20000.0): "10k-to-20k",
    (20000.0, 30000.0): "20k-to-30k",
    (30000.0, 40000.0): "30k-to-40k",
    (40000.0, 50000.0): "40k-to-50k",
    (50000.0, 60000.0): "50k-to-60k",
    (60000.0, 70000.0): "60k-to-70k",
    (70000.0, 80000.0): "70k-to-80k",
    (80000.0, 100000.0): "80k-to-1l",
    (100000.0, 150000.0): "1l-to-1.5l",
    (150000.0, 200000.0): "1.5l-to-2l",
}
_OPEN_BAND_SLUG = "above-2l"

_KARAT_SLUGS = {9: "9kt", 14: "14kt", 18: "18kt", 24: "24kt"}
_KARAT_DIGITS_RE = re.compile(r"\d{1,2}")

_COLOUR_SLUGS = {"yellow": "yellow", "white": "white", "rose": "rose"}

# The sidebar offers Gold / Diamond / Gemstone only. White and rose gold are
# gold on the site; silver, platinum and pearl have no filter of their own.
_MATERIAL_SLUGS = {
    "gold": "gold",
    "white_gold": "gold",
    "rose_gold": "gold",
    "diamond": "diamond",
    "gemstone": "gemstone",
}

# Live-confirmed against the real site (client-verified, not guessed):
# .../earrings+mens+... and .../earrings+women+... -- asymmetric on purpose,
# "mens" carries the trailing s, "women" does not.
_GENDER_SLUGS = {"men": "mens", "women": "women", "kids": "kids"}

_FULFILLMENT_SLUGS = {"ready": "ready-to-ship", "mto": "made-to-order"}

# Only the occasions that exist as filters. The bot also extracts wedding,
# anniversary, birthday and gift, which the site has no token for.
_OCCASION_SLUGS = {
    "engagement": "engagement",
    "daily_wear": "daily-wear",
    "casual": "casual",
    "religious": "religious",
}


def _key(value: Any) -> str:
    return str(value or "").strip().lower()


def category_slugs(category: Any) -> tuple[str, ...]:
    """Site filter slug(s) for a category; empty when the site has no filter.

    Accepts the spelling variants that reach here from different paths --
    internal keys ("nosewear"), postback keys ("nose_wear"), spaced or
    hyphenated labels ("nose wear"), and plurals ("rings") -- but only ever
    returns a slug that is in the table.
    """
    key = _key(category).replace("-", "_").replace(" ", "_")
    if not key:
        return ()
    for candidate in (key, key[:-1] if key.endswith("s") else f"{key}s"):
        slugs = CATEGORY_SLUGS.get(candidate)
        if slugs:
            return slugs
    return ()


def _price_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _band_slug_at(amount: float | None) -> str | None:
    """Slug of the band a single amount falls in."""
    if amount is None or amount >= _OPEN_BAND_FLOOR:
        return _OPEN_BAND_SLUG
    for band in PRICE_BANDS:
        if amount < band[1]:
            return _BAND_SLUGS.get(band)
    return _OPEN_BAND_SLUG


def price_band_slug(min_price: Any, max_price: Any) -> str | None:
    """Pick the single price filter that best covers the customer's budget.

    The site applies only the first price token in a URL, so a range spanning
    several bands still has to choose one: take the band overlapping the range
    most, and on a tie the higher one, so "under 30000" lands on 20k-to-30k
    rather than the bottom of the budget. A budget the wizard already snapped
    (_snap_single_price_to_band) matches a band exactly and is unaffected.
    """
    low = _price_float(min_price)
    high = _price_float(max_price)
    if low is None and high is None:
        return None

    if high is None:
        # Open-ended top: the band the floor sits in.
        return _band_slug_at(low)

    low = 0.0 if low is None else low
    if low > high:
        low, high = high, low
    if low >= _OPEN_BAND_FLOOR:
        return _OPEN_BAND_SLUG
    if low == high:
        # A single stated amount that never got widened into a range.
        return _band_slug_at(low)

    best_slug: str | None = None
    best_overlap = 0.0
    for band in PRICE_BANDS:
        overlap = min(high, band[1]) - max(low, band[0])
        # >= keeps the higher band on a tie (bands are ordered ascending).
        if overlap > 0 and overlap >= best_overlap:
            best_overlap = overlap
            best_slug = _BAND_SLUGS.get(band)
    if high > _OPEN_BAND_FLOOR and (high - _OPEN_BAND_FLOOR) >= best_overlap:
        return _OPEN_BAND_SLUG
    return best_slug


def karat_slug(karat: Any) -> str | None:
    """9KT / 14KT / 18KT / 24KT only — 22KT exists at KISNA but has no filter."""
    match = _KARAT_DIGITS_RE.search(_key(karat))
    if not match:
        return None
    return _KARAT_SLUGS.get(int(match.group(0)))


def colour_slug(colour: Any) -> str | None:
    return _COLOUR_SLUGS.get(_key(colour))


def material_slug(material_type: Any) -> str | None:
    return _MATERIAL_SLUGS.get(_key(material_type))


def gender_slug(gender: Any) -> str | None:
    return _GENDER_SLUGS.get(_key(gender))


def fulfillment_slug(fulfillment: Any) -> str | None:
    return _FULFILLMENT_SLUGS.get(_key(fulfillment))


def occasion_slug(occasion: Any) -> str | None:
    return _OCCASION_SLUGS.get(_key(occasion).replace(" ", "_").replace("-", "_"))


def collection_slug(collection: Any, *, fuzzy: bool = True) -> str | None:
    """Real slug for a named collection, or None when it isn't one.

    Resolved against the live/snapshot filters list rather than derived,
    because six collections slug bare (echo, esme, heart-string, tiny-tales,
    vachan, valentine-2025) while the rest carry "-collection". Free text that
    matches no collection — a product title riding along in entities — drops
    its segment instead of inventing one.

    ``fuzzy`` off for free text: an exact name ("Sparkle", "Sparkle
    Collection") still resolves, but a near-miss like "charm" must not narrow
    the catalogue to Charms Collection on its own.
    """
    name = str(collection or "").strip()
    if not name:
        return None
    from kisna_chatbot.integrations.clara_filters import get_collection_slug

    return get_collection_slug(name, fuzzy=fuzzy)
