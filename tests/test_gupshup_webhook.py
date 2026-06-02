"""Gupshup webhook tests and manual integration script."""

import hashlib
import hmac
import json
import os
import sys
import unittest
from unittest.mock import Mock

# Minimal env before kisna_chatbot imports (database connects at import time).
os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")
os.environ.setdefault("GUPSHUP_PHONE_NUMBER", "919876543210")
os.environ.setdefault("KISNA_PHONE_NUMBER_ID", "850788844795304")

from kisna_chatbot.config.gupshup import (
    build_phone_number_id_map,
    get_gupshup_source,
    refresh_phone_number_id_map,
)
from pymongo.errors import DuplicateKeyError

import kisna_chatbot.main as main_mod
from kisna_chatbot.main import (
    mark_inbound_processed,
    verify_gupshup_signature,
    verify_webhook_request,
)


class GupshupSignatureTests(unittest.TestCase):
    def test_verify_gupshup_signature_valid(self):
        body = b'{"entry":[]}'
        secret = "test-secret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_gupshup_signature(body, sig, secret))

    def test_verify_gupshup_signature_sha256_prefix(self):
        body = b'{"entry":[]}'
        secret = "test-secret"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_gupshup_signature(body, f"sha256={sig}", secret))

    def test_verify_gupshup_signature_invalid(self):
        body = b'{"entry":[]}'
        self.assertFalse(
            verify_gupshup_signature(body, "bad-signature", "test-secret")
        )

    def test_verify_webhook_request_skips_without_secret(self):
        body = b'{"entry":[]}'
        old = os.environ.pop("GUPSHUP_WEBHOOK_SECRET", None)
        try:
            self.assertTrue(verify_webhook_request(body, None))
        finally:
            if old is not None:
                os.environ["GUPSHUP_WEBHOOK_SECRET"] = old

    def test_verify_webhook_request_requires_signature_when_secret_set(self):
        body = b'{"entry":[]}'
        os.environ["GUPSHUP_WEBHOOK_SECRET"] = "webhook-secret"
        self.assertFalse(verify_webhook_request(body, None))
        sig = hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_webhook_request(body, sig))


class PhoneNumberIdMapTests(unittest.TestCase):
    def test_build_phone_number_id_map(self):
        os.environ["KISNA_PHONE_NUMBER_ID"] = "111"
        os.environ["NKL_PHONE_NUMBER_ID"] = "222"
        refresh_phone_number_id_map()
        mapping = build_phone_number_id_map()
        self.assertEqual(mapping.get("111"), "kisna")
        self.assertEqual(mapping.get("222"), "nkl")

    def test_get_gupshup_source_prefers_phone_number(self):
        os.environ["GUPSHUP_PHONE_NUMBER"] = "919111111111"
        os.environ["GUPSHUP_SOURCE"] = "919222222222"
        self.assertEqual(get_gupshup_source(), "919111111111")


class InboundDedupTests(unittest.TestCase):
    def test_mark_inbound_processed_returns_true_on_insert(self):
        mock_collection = Mock()
        mock_collection.insert_one.return_value = {"ok": 1}
        old = main_mod.processed_inbound_messages
        try:
            main_mod.processed_inbound_messages = mock_collection
            ok = mark_inbound_processed(
                client_id="kisna",
                phone_number="919999999999",
                message_id="wamid.test",
            )
            self.assertTrue(ok)
            self.assertTrue(mock_collection.insert_one.called)
        finally:
            main_mod.processed_inbound_messages = old

    def test_mark_inbound_processed_returns_false_on_duplicate(self):
        mock_collection = Mock()
        mock_collection.insert_one.side_effect = DuplicateKeyError("dup")
        old = main_mod.processed_inbound_messages
        try:
            main_mod.processed_inbound_messages = mock_collection
            ok = mark_inbound_processed(
                client_id="kisna",
                phone_number="919999999999",
                message_id="wamid.dup",
            )
            self.assertFalse(ok)
        finally:
            main_mod.processed_inbound_messages = old


def _build_test_payload(phone_number_id: str) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "919876543210",
                                "phone_number_id": phone_number_id,
                            },
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "wamid.test",
                                    "text": {"body": "Hello Kisna bot"},
                                    "timestamp": "1234567890",
                                    "type": "text",
                                }
                            ],
                            "contacts": [
                                {
                                    "profile": {"name": "Test User"},
                                    "wa_id": "919999999999",
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def run_webhook_integration() -> int:
    """POST a sample webhook payload to the local server."""
    import requests

    webhook_url = os.getenv(
        "WEBHOOK_URL", "http://localhost:8000/gupshup/message/kisna"
    )
    phone_number_id = os.getenv("KISNA_PHONE_NUMBER_ID", "850788844795304")
    secret = os.getenv("GUPSHUP_WEBHOOK_SECRET", "").strip()

    payload = _build_test_payload(phone_number_id)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    if secret:
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Gupshup-Signature"] = signature

    print(f"POST {webhook_url}")
    print(f"phone_number_id={phone_number_id}, signed={bool(secret)}")

    try:
        response = requests.post(webhook_url, data=body, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return 1

    print(f"Status: {response.status_code}")
    try:
        print(f"Response: {response.json()}")
    except Exception:
        print(f"Response: {response.text}")

    return 0 if response.status_code == 200 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "integration":
        sys.exit(run_webhook_integration())
    unittest.main()
