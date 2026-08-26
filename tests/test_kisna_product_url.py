"""Detect a pasted Kisna product URL (single or multiple) and derive a title
search phrase from its slug -- the only resolvable signal, since Clara has
no lookup-by-id/slug/variant endpoint, only a `title` substring search.
"""

import os
import unittest

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")

from kisna_chatbot.utils.kisna_product_url import (
    extract_kisna_product_urls,
    product_url_to_title_query,
)

_CUSTOMER_URL = (
    "https://www.kisna.com/products/shree-diamond-gold-pendant"
    "?variant=6895d8b1e29b8e133eb53e0a"
)


class ExtractKisnaProductUrlsTests(unittest.TestCase):
    def test_single_url(self):
        text = f"is this available {_CUSTOMER_URL}"
        self.assertEqual(extract_kisna_product_urls(text), [_CUSTOMER_URL])

    def test_multiple_urls(self):
        url2 = "https://www.kisna.com/products/evil-eye-gold-ring"
        text = f"which is better {_CUSTOMER_URL} or {url2}"
        self.assertEqual(extract_kisna_product_urls(text), [_CUSTOMER_URL, url2])

    def test_non_kisna_url_ignored(self):
        text = "I saw this on https://www.tanishq.co.in/products/some-ring"
        self.assertEqual(extract_kisna_product_urls(text), [])

    def test_trailing_punctuation_stripped(self):
        text = f"check this out: {_CUSTOMER_URL}."
        self.assertEqual(extract_kisna_product_urls(text), [_CUSTOMER_URL])

    def test_no_url_returns_empty(self):
        self.assertEqual(extract_kisna_product_urls("show me gold rings"), [])
        self.assertEqual(extract_kisna_product_urls(""), [])
        self.assertEqual(extract_kisna_product_urls(None), [])

    def test_duplicate_url_deduped(self):
        text = f"{_CUSTOMER_URL} {_CUSTOMER_URL}"
        self.assertEqual(extract_kisna_product_urls(text), [_CUSTOMER_URL])

    def test_capped_at_limit(self):
        urls = [f"https://www.kisna.com/products/item-{i}-gold-ring" for i in range(5)]
        text = " ".join(urls)
        self.assertEqual(len(extract_kisna_product_urls(text, limit=3)), 3)

    def test_bare_domain_with_no_scheme_is_detected(self):
        # Very common paste pattern -- no "https://" typed/kept at all.
        text = "check kisna.com/products/shree-diamond-gold-pendant please"
        self.assertEqual(
            extract_kisna_product_urls(text),
            ["https://kisna.com/products/shree-diamond-gold-pendant"],
        )

    def test_bare_www_domain_with_no_scheme_is_detected(self):
        text = "www.kisna.com/products/shree-diamond-gold-pendant"
        self.assertEqual(
            extract_kisna_product_urls(text),
            ["https://www.kisna.com/products/shree-diamond-gold-pendant"],
        )

    def test_lookalike_domain_not_matched(self):
        # "fakekisna.com" contains "kisna.com" as a substring but is not it.
        text = "I saw this on fakekisna.com/products/shree-diamond-gold-pendant"
        self.assertEqual(extract_kisna_product_urls(text), [])

    def test_real_subdomain_not_matched(self):
        # is_kisna_website_url only accepts the bare/www host, not a
        # subdomain -- nothing to gain by detecting one here either.
        text = "shop.kisna.com/products/shree-diamond-gold-pendant"
        self.assertEqual(extract_kisna_product_urls(text), [])


class ProductUrlToTitleQueryTests(unittest.TestCase):
    def test_customer_url_resolves_to_title_phrase(self):
        self.assertEqual(
            product_url_to_title_query(_CUSTOMER_URL),
            "shree diamond gold pendant",
        )

    def test_variant_query_param_is_ignored(self):
        with_variant = product_url_to_title_query(_CUSTOMER_URL)
        without_variant = product_url_to_title_query(
            "https://www.kisna.com/products/shree-diamond-gold-pendant"
        )
        self.assertEqual(with_variant, without_variant)

    def test_catalogue_link_returns_none(self):
        self.assertIsNone(
            product_url_to_title_query("https://www.kisna.com/jewellery/ring+gold")
        )

    def test_bare_category_no_hyphen_returns_none(self):
        self.assertIsNone(product_url_to_title_query("https://www.kisna.com/rings"))

    def test_non_product_pages_are_never_read_as_a_product(self):
        # Real, confirmed non-product kisna.com pages already referenced
        # elsewhere in this codebase -- each has a hyphenated last segment,
        # which is exactly what could make them LOOK like a product slug.
        # Must all resolve to None, not a nonsense title search.
        for url in (
            "https://www.kisna.com/pages/track-order",
            "https://www.kisna.com/digital-gold",
            "https://www.kisna.com/careers-and-job-opportunities",
            "https://www.kisna.com/kisna-authorized-dealers",
            "https://www.kisna.com/store",
        ):
            self.assertIsNone(product_url_to_title_query(url), url)

    def test_products_path_with_no_slug_segment_returns_none(self):
        self.assertIsNone(product_url_to_title_query("https://www.kisna.com/products"))
        self.assertIsNone(product_url_to_title_query("https://www.kisna.com/products/"))

    def test_no_path_returns_none(self):
        self.assertIsNone(product_url_to_title_query("https://www.kisna.com"))

    def test_malformed_url_returns_none(self):
        self.assertIsNone(product_url_to_title_query("not a url at all"))


if __name__ == "__main__":
    unittest.main()
