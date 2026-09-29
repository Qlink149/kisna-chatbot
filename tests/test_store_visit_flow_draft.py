"""scripts/store_visit_flow_draft.py: the interactive preview always carries
phone_number = Kisna's WhatsApp business number from Gupshup (Meta requires
it for flows with an endpoint), cross-checked against the env."""

import os
import sys
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import store_visit_flow_draft as draft  # noqa: E402

PREVIEW = "https://business.facebook.com/wa/manage/flows/1/preview/?token=t"


def _waba(phone):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status": "success", "wabaInfo": {"phone": phone, "phoneId": "x"}}
    return resp


class PreviewLinkTests(unittest.TestCase):
    def test_interactive_link_always_has_the_business_number(self):
        url = draft.interactive_preview(PREVIEW, "917304278561")
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(q["phone_number"], ["917304278561"])
        self.assertEqual(q["interactive"], ["true"])
        self.assertIn("SV_DETAILS", q["flow_action_payload"][0])

    def test_no_number_no_link(self):
        with self.assertRaises(ValueError):
            draft.interactive_preview(PREVIEW, "")

    def test_business_number_comes_from_gupshup_and_must_match_env(self):
        with patch.object(draft.requests, "get", return_value=_waba("917304278561")), patch.dict(
            os.environ, {"GUPSHUP_SOURCE": "917304278561", "GUPSHUP_PHONE_NUMBER": ""}
        ):
            self.assertEqual(draft.business_phone_number("app", "tok"), "917304278561")
        with patch.object(draft.requests, "get", return_value=_waba("917304278561")), patch.dict(
            os.environ, {"GUPSHUP_SOURCE": "919909047798", "GUPSHUP_PHONE_NUMBER": ""}
        ):
            with self.assertRaises(SystemExit):
                draft.business_phone_number("app", "tok")
        with patch.object(draft.requests, "get", return_value=_waba("")), patch.dict(
            os.environ, {"GUPSHUP_SOURCE": "", "GUPSHUP_PHONE_NUMBER": ""}
        ):
            with self.assertRaises(SystemExit):
                draft.business_phone_number("app", "tok")


if __name__ == "__main__":
    unittest.main()
