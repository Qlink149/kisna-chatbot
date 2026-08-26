"""Detect inbound Kisna product-page URLs and derive a title-search phrase.

Clara's product API has no lookup-by-id/slug/variant endpoint (see
clara_api.build_products_query_params) -- only a `title` substring-search
param. So a pasted product URL is resolved by turning its slug into the same
kind of free-text title phrase a customer would type, and letting it flow
through the existing, already-tested title-search pipeline unchanged.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from kisna_chatbot.utils.kisna_url_tracking import is_kisna_website_url

# Scheme and "www." are both optional -- customers commonly paste a bare
# "kisna.com/products/..." with no "https://" at all. The lookbehind blocks
# a match starting mid-word (e.g. "fakekisna.com") or on a real subdomain
# (e.g. "shop.kisna.com" -- is_kisna_website_url only accepts the bare/www
# host anyway, so there's nothing to gain by matching those here).
_URL_RE = re.compile(
    r"(?<![\w.-])(?:https?://)?(?:www\.)?kisna\.com(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)

# A real product slug is a multi-word, hyphen-joined name (e.g.
# "shree-diamond-gold-pendant", per build_product_url's reverse transform).
# Anything shorter than this is more likely a bare category/collection page
# than an actual product -- don't guess.
_MIN_SLUG_HYPHENS = 1


def extract_kisna_product_urls(text: str, *, limit: int = 3) -> list[str]:
    """Return up to `limit` distinct kisna.com URLs found in `text`."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.findall(text):
        url = match.rstrip(").,!?\"'")
        if not url.lower().startswith(("http://", "https://")):
            url = f"https://{url}"
        if not is_kisna_website_url(url):
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(url)
        if len(found) >= limit:
            break
    return found


def product_url_to_title_query(url: str) -> str | None:
    """Reverse of build_product_url(): URL path -> space-separated title phrase.

    The `variant=<id>` query param is intentionally ignored -- there is no
    Clara API param for it, so it cannot be resolved exactly, only the
    slug's words can be text-searched via the existing `title` param.
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return None
    path = (parsed.path or "").strip("/")
    if not path:
        return None
    segments = [s for s in path.split("/") if s]
    # Allow-list, not block-list: only a literal /products/<slug> path is
    # treated as a single product page. kisna.com has plenty of OTHER
    # hyphenated, non-jewellery paths that must NOT be read as a product
    # title -- confirmed real ones already referenced in this codebase:
    # /pages/track-order, /digital-gold, /careers-and-job-opportunities,
    # /kisna-authorized-dealers. Catalogue deep-links (/jewellery/...) are
    # excluded the same way, for free, by only accepting "products".
    if len(segments) < 2 or segments[0].lower() != "products":
        return None
    slug = segments[-1]
    if slug.count("-") < _MIN_SLUG_HYPHENS:
        return None
    phrase = re.sub(r"\s+", " ", slug.replace("-", " ").replace("_", " ")).strip()
    return phrase or None
