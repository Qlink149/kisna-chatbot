"""Tests for WhatsApp Flow endpoint crypto + data_exchange handler."""

import json
import os
import unittest
from base64 import b64encode
from datetime import datetime, timedelta, timezone

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("GROQ_API_KEY", "test")

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP

from kisna_chatbot.processors.flow_data_exchange import build_flow_response
from kisna_chatbot.utils.flow_endpoint_crypto import (
    decrypt_request,
    encrypt_response,
)

_IST = timezone(timedelta(hours=5, minutes=30))


def _generate_key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return private_key, private_pem


def _encrypt_request(private_key, payload: dict):
    """Produce a Meta-shaped encrypted body using the matching public key."""
    public_key = private_key.public_key()
    aes_key = os.urandom(16)
    iv = os.urandom(16)
    encrypted_aes_key = public_key.encrypt(
        aes_key,
        OAEP(
            mgf=MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(iv)).encryptor()
    ciphertext = (
        encryptor.update(json.dumps(payload).encode("utf-8"))
        + encryptor.finalize()
        + encryptor.tag
    )
    return {
        "encrypted_flow_data": b64encode(ciphertext).decode("utf-8"),
        "encrypted_aes_key": b64encode(encrypted_aes_key).decode("utf-8"),
        "initial_vector": b64encode(iv).decode("utf-8"),
    }, aes_key, iv


class TestFlowEndpointCrypto(unittest.TestCase):
    def test_round_trip(self):
        private_key, private_pem = _generate_key_pair()
        body, _, _ = _encrypt_request(
            private_key, {"action": "ping", "version": "3.0"}
        )
        from kisna_chatbot.utils.flow_endpoint_crypto import load_flow_private_key

        key = load_flow_private_key(private_pem, passphrase=None)
        decrypted, aes_key, iv = decrypt_request(
            body["encrypted_flow_data"],
            body["encrypted_aes_key"],
            body["initial_vector"],
            private_key=key,
        )
        self.assertEqual(decrypted["action"], "ping")
        encrypted = encrypt_response({"data": {"status": "active"}}, aes_key, iv)
        self.assertTrue(isinstance(encrypted, str) and len(encrypted) > 20)


class TestFlowDataExchange(unittest.TestCase):
    def test_ping(self):
        self.assertEqual(
            build_flow_response({"action": "ping"}),
            {"data": {"status": "active"}},
        )

    def test_date_selected_filters_slots(self):
        # Freeze "now" by monkeypatching screen_data_for_date's now via preferred date
        # and asserting structure; filter math is covered in test_support_slots.
        resp = build_flow_response(
            {
                "action": "data_exchange",
                "screen": "CALLBACK_REQUEST",
                "flow_token": "flow_callback_test",
                "data": {
                    "preferred_date": "2099-01-15",
                    "trigger": "date_selected",
                },
            }
        )
        self.assertEqual(resp["screen"], "CALLBACK_REQUEST")
        self.assertEqual(len(resp["data"]["time_slots"]), 7)
        self.assertEqual(resp["data"]["time_slots"][0]["id"], "10-11")

    def test_init_returns_min_date_and_slots(self):
        resp = build_flow_response(
            {
                "action": "INIT",
                "flow_token": "flow_callback_test",
            }
        )
        self.assertIn("min_date", resp["data"])
        self.assertIn("time_slots", resp["data"])
        self.assertEqual(resp["screen"], "CALLBACK_REQUEST")


if __name__ == "__main__":
    unittest.main()
