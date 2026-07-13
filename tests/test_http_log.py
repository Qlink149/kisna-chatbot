"""Tests for http_log helpers (path + query params, no base URL)."""

import unittest

from kisna_chatbot.utils.http_log import format_params_for_log, path_from_url


class TestHttpLogHelpers(unittest.TestCase):
    def test_format_params(self):
        self.assertEqual(format_params_for_log(None), "(none)")
        self.assertEqual(format_params_for_log({}), "(none)")
        self.assertEqual(
            format_params_for_log({"pageNo": 1, "category": "Rings", "empty": ""}),
            "pageNo=1 category=Rings",
        )

    def test_path_from_url_strips_host(self):
        self.assertEqual(
            path_from_url("https://example.com/api/v1/clara/products"),
            "/api/v1/clara/products",
        )
        self.assertEqual(
            path_from_url("https://example.com/api/v1/clara/stores?pincode=400001"),
            "/api/v1/clara/stores?pincode=400001",
        )


if __name__ == "__main__":
    unittest.main()
