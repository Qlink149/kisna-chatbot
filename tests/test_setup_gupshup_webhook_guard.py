"""scripts/setup_gupshup_webhook.py must not move prod's inbound webhook off
kisna-api.claraai.tech (e.g. to the retired Vercel URL) without --force, and
must print the current subscriptions before changing anything."""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import setup_gupshup_webhook as hook  # noqa: E402

LIVE = [{"id": "10880260", "tag": "kisna-chatbot", "url": "https://kisna-api.claraai.tech/gupshup/message/kisna",
         "active": True, "version": 3, "modes": ["MESSAGE"], "secret": "never-printed"}]


class WebhookGuardTests(unittest.TestCase):
    def test_check_url(self):
        self.assertIsNone(hook.check_webhook_url("https://kisna-api.claraai.tech/gupshup/message/kisna", force=False))
        for bad in (
            "https://kisna-chatbot.vercel.app/gupshup/message/kisna",
            "http://kisna-api.claraai.tech/gupshup/message/kisna",
            "https://kisna-api.claraai.tech.evil.com/x",
        ):
            self.assertIn("REFUSED", hook.check_webhook_url(bad, force=False), bad)
            self.assertIsNone(hook.check_webhook_url(bad, force=True), bad)

    def _run(self, argv, url):
        out, err = io.StringIO(), io.StringIO()
        env = {"GUPSHUP_APP_ID": "app", "WEBHOOK_URL": url}
        with patch.dict(os.environ, env), patch.object(sys, "argv", ["x", *argv]), patch.object(
            hook, "get_app_token", return_value="tok"
        ), patch.object(hook, "get_existing_subscriptions", return_value=LIVE), patch.object(
            hook, "upsert_subscription", return_value={"action": "updated", "subscription": {"id": "1"}}
        ) as upsert, redirect_stdout(out), redirect_stderr(err):
            try:
                hook.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue(), upsert

    def test_refuses_vercel_and_prints_current_first(self):
        code, out, err, upsert = self._run([], "https://kisna-chatbot.vercel.app/gupshup/message/kisna")
        self.assertEqual(code, 2)
        self.assertIn("current_subscriptions", out)
        self.assertIn("kisna-api.claraai.tech/gupshup/message/kisna", out)
        self.assertNotIn("never-printed", out)
        self.assertIn("REFUSED", err)
        upsert.assert_not_called()

    def test_force_allows_it(self):
        code, _, _, upsert = self._run(["--force"], "https://kisna-chatbot.vercel.app/gupshup/message/kisna")
        self.assertEqual(code, 0)
        upsert.assert_called_once()

    def test_live_host_is_set_after_printing_current(self):
        code, out, _, upsert = self._run([], "https://kisna-api.claraai.tech/gupshup/message/kisna")
        self.assertEqual(code, 0)
        self.assertLess(out.index("current_subscriptions"), out.index('"status": "success"'))
        upsert.assert_called_once()

    def test_list_changes_nothing(self):
        code, out, _, upsert = self._run(["--list"], "https://kisna-chatbot.vercel.app/x")
        self.assertEqual(code, 0)
        self.assertIn("current_subscriptions", out)
        upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
