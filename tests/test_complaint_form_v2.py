"""Phase 4 — complaint form v2.

The published WhatsApp Flow changed (Order ID optional, category-specific
contact fields added, "Want to Buy" removed). The server side stays
backward-compatible: old-form payloads (screen_0_* keys, no contact fields)
must still parse and register exactly as before; new-form payloads carry
extra fields that flow through to Mongo + the issue text without touching the
Clara event contract.
"""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

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
os.environ.setdefault("KISNA_DAMAGE_COMPLAINT_FLOW_ID", "1527624128967855")

from kisna_chatbot.processors import complaint_agent as ca  # noqa: E402

_FLOW_ID = "1527624128967855"
_ROOT = Path(__file__).resolve().parent.parent


class FlowJsonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.flow = json.loads((_ROOT / "json" / "damage_complaint.json").read_text())
        self.fields = self.flow["screens"][0]["layout"]["children"][0]["children"]
        self.by_name = {f["name"]: f for f in self.fields if "name" in f}

    def test_single_terminal_screen_unchanged_shape(self) -> None:
        screen = self.flow["screens"][0]
        self.assertEqual(screen["id"], "RECOMMEND")
        self.assertTrue(screen["terminal"])
        self.assertEqual(len(self.flow["screens"]), 1)
        # No data_exchange machinery -- pure single-screen form, lowest risk.
        self.assertNotIn("data_api_version", self.flow)
        self.assertNotIn("routing_model", self.flow)

    def test_want_to_buy_removed_from_dropdown(self) -> None:
        opts = [o["id"] for o in self.by_name["complaint_type"]["data-source"]]
        self.assertNotIn("0_Want_to_Buy", opts)
        self.assertIn("1_Order_Related", opts)
        self.assertIn("9_Other", opts)

    def test_order_id_is_no_longer_required(self) -> None:
        self.assertFalse(self.by_name["order_id"]["required"])

    def test_category_specific_fields_present_and_optional(self) -> None:
        for name in ("registered_mobile", "registered_contact", "invoice_number"):
            self.assertIn(name, self.by_name, name)
            self.assertFalse(self.by_name[name]["required"], name)
            self.assertTrue(self.by_name[name].get("helper-text"), name)

    def test_issue_description_still_required(self) -> None:
        self.assertTrue(self.by_name["issue_description"]["required"])

    def test_payload_emits_clean_semantic_keys(self) -> None:
        footer = next(f for f in self.fields if f["type"] == "Footer")
        payload = footer["on-click-action"]["payload"]
        self.assertEqual(set(payload), {
            "complaint_type", "order_id", "registered_mobile",
            "registered_contact", "invoice_number", "issue_description",
        })


class BackwardCompatParsingTests(unittest.TestCase):
    def test_old_screen_0_payload_still_parses(self) -> None:
        old = {
            "flow_token": _FLOW_ID,
            "screen_0_Order_ID_0": "ORD123",
            "screen_0_Issue_Description_1": "Broken clasp",
            "screen_0_complaint_type_2": "1_Order_Related",
        }
        order_id, issue, ctype = ca._extract_complaint_fields(old)
        self.assertEqual((order_id, issue, ctype), ("ORD123", "Broken clasp", "1_Order_Related"))
        self.assertEqual(
            ca._extract_contact_fields(old),
            {"registered_mobile": "", "registered_contact": "", "invoice_number": ""},
        )

    def test_new_payload_parses_core_and_contact_fields(self) -> None:
        new = {
            "flow_token": _FLOW_ID,
            "complaint_type": "3_Stores_Related",
            "order_id": "",
            "registered_mobile": "",
            "registered_contact": "priya@example.com",
            "invoice_number": "INV-9",
            "issue_description": "Wrong ring size given in store",
        }
        order_id, issue, ctype = ca._extract_complaint_fields(new)
        self.assertEqual(order_id, "")
        self.assertEqual(ctype, "3_Stores_Related")
        contact = ca._extract_contact_fields(new)
        self.assertEqual(contact["registered_contact"], "priya@example.com")
        self.assertEqual(contact["invoice_number"], "INV-9")

    def test_augment_issue_is_noop_without_contact_fields(self) -> None:
        # Guards the byte-for-byte Clara event tests.
        self.assertEqual(
            ca._augment_issue_with_contact("Broken clasp", {"registered_mobile": "", "registered_contact": "", "invoice_number": ""}),
            "Broken clasp",
        )

    def test_augment_issue_appends_a_readable_block(self) -> None:
        out = ca._augment_issue_with_contact(
            "Payment failed",
            {"registered_mobile": "9812345678", "registered_contact": "", "invoice_number": ""},
        )
        self.assertIn("Payment failed", out)
        self.assertIn("Registered mobile: 9812345678", out)

    def test_want_to_buy_detection(self) -> None:
        self.assertTrue(ca._is_want_to_buy("0_Want_to_Buy"))
        self.assertTrue(ca._is_want_to_buy("Want to Buy"))
        self.assertFalse(ca._is_want_to_buy("1_Order_Related"))
        self.assertFalse(ca._is_want_to_buy(""))

    def test_confirmation_is_now_compose_tagged(self) -> None:
        resp = ca._build_confirmation("CASE-1")
        self.assertEqual(resp[0].get("_compose"), "complaint_registered")


class ProcessEndToEndTests(unittest.IsolatedAsyncioTestCase):
    def _data(self, payload: dict) -> dict:
        cfg = MagicMock()
        cfg.client_id = "kisna"
        return {
            "phone_number": "919812345678",
            "client_id": "kisna",
            "client_config": cfg,
            "whatsapp_username": "Priya",
            "user_profile": {"username": "Priya"},
            "messages": {
                "interactive": {
                    "nfm_reply": {"response_json": json.dumps({"flow_token": _FLOW_ID, **payload})}
                }
            },
        }

    async def _run(self, payload: dict):
        inserted = {}

        def _insert(doc):
            inserted.update(doc)

        with patch.object(ca.complaints, "insert_one", side_effect=_insert), patch.object(
            ca, "enqueue_clara_event", new_callable=AsyncMock
        ), patch.object(ca, "CRMAdapter") as crm_cls:
            crm = crm_cls.return_value
            crm.create_case = AsyncMock(return_value={"id": ""})
            crm.aclose = AsyncMock()
            agent = ca.ComplaintAgent()
            out = await agent.process(self._data(payload))
        return out, inserted

    async def test_want_to_buy_routes_to_sales_not_a_complaint(self):
        out, inserted = await self._run({"complaint_type": "0_Want_to_Buy", "issue_description": "rings"})
        self.assertEqual(inserted, {})  # nothing logged
        self.assertIn("buy something", out["bot_response"][0]["text"])
        self.assertEqual(out["bot_response"][0].get("_compose"), "complaint_want_to_buy_redirect")

    async def test_payment_complaint_with_no_order_id_still_registers(self):
        out, inserted = await self._run({
            "complaint_type": "2_Payment_Related",
            "order_id": "",
            "registered_mobile": "9812345678",
            "issue_description": "Money debited, no order. Txn TXN99, 15000, 2026-09-08.",
        })
        self.assertEqual(inserted["order_id"], "")
        self.assertEqual(inserted["type"], "2_Payment_Related")
        self.assertEqual(inserted["registered_mobile"], "9812345678")
        self.assertIn("Registered mobile: 9812345678", inserted["issue"])
        self.assertIn("Money debited", inserted["issue"])

    async def test_old_form_submission_unchanged(self):
        out, inserted = await self._run({
            "screen_0_Order_ID_0": "ORD777",
            "screen_0_Issue_Description_1": "Damaged on arrival",
            "screen_0_complaint_type_2": "1_Order_Related",
        })
        self.assertEqual(inserted["order_id"], "ORD777")
        self.assertEqual(inserted["issue"], "Damaged on arrival")  # no contact block appended
        self.assertEqual(inserted["registered_mobile"], "")


if __name__ == "__main__":
    unittest.main()
