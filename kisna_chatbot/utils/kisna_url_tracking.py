"""Append UTM parameters to outbound kisna.com links for GA4/GTM attribution."""

from __future__ import annotations

import os
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


def _utm_enabled() -> bool:
    return os.getenv("KISNA_UTM_ENABLED", "true").lower() in ("1", "true", "yes")


def is_kisna_website_url(url: str) -> bool:
    """True for http(s) URLs on kisna.com / www.kisna.com."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower().removeprefix("www.")
    return host == "kisna.com"


def append_kisna_utm(url: str) -> str:
    """
    Tag a kisna.com URL with utm_source and utm_medium for analytics.

    Skips non-KISNA URLs, disabled mode, and keys already present on the URL.
    """
    if not url or not _utm_enabled():
        return url
    if not is_kisna_website_url(url):
        return url

    parsed = urlparse(url.strip())
    query = parse_qs(parsed.query, keep_blank_values=True)

    source = (os.getenv("KISNA_UTM_SOURCE") or "whatsapp").strip()
    medium = (os.getenv("KISNA_UTM_MEDIUM") or "kia_bot").strip()

    utm_params = {
        "utm_source": source,
        "utm_medium": medium,
    }

    for key, value in utm_params.items():
        if value and key not in query:
            query[key] = [value]

    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def kisna_home_url() -> str:
    """Homepage URL with bot attribution UTMs."""
    base = (os.getenv("KISNA_WEBSITE_HOME_URL") or "https://www.kisna.com").strip()
    return append_kisna_utm(base)
