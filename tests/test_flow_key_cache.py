"""The Flow endpoint's private key is parsed once and reused, reloaded only
when the env value changes (key rotation), and safe under concurrent first
use. The encrypted round trips for callback / video / store visit live in
tests/test_flow_data_exchange.py and tests/test_store_visit.py."""

import os
import threading
import unittest
from base64 import b64encode
from unittest.mock import patch

os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from kisna_chatbot.utils import flow_endpoint_crypto as crypto  # noqa: E402


def _pem(passphrase: bytes | None = None) -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    enc = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase
        else serialization.NoEncryption()
    )
    return key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, enc
    ).decode()


def _public_numbers(key):
    return key.public_key().public_numbers()


class FlowKeyCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pem_a, cls.pem_b = _pem(), _pem()

    def setUp(self):
        crypto._cached_key = None
        crypto._cached_fingerprint = None
        self._env = patch.dict(
            os.environ,
            {
                "KISNA_FLOW_PRIVATE_KEY": self.pem_a,
                "KISNA_FLOW_PRIVATE_KEY_B64": "",
                "KISNA_FLOW_PRIVATE_KEY_PASSPHRASE": "",
            },
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        crypto._cached_key = None
        crypto._cached_fingerprint = None

    def test_parsed_once_then_reused(self):
        with patch.object(crypto, "load_flow_private_key", wraps=crypto.load_flow_private_key) as load:
            k1 = crypto.get_flow_private_key()
            for _ in range(20):
                self.assertIs(crypto.get_flow_private_key(), k1)
        self.assertEqual(load.call_count, 1)

    def test_rotation_via_env_reloads(self):
        k1 = crypto.get_flow_private_key()
        os.environ["KISNA_FLOW_PRIVATE_KEY"] = self.pem_b
        k2 = crypto.get_flow_private_key()
        self.assertNotEqual(_public_numbers(k1), _public_numbers(k2))
        self.assertIs(crypto.get_flow_private_key(), k2)

    def test_b64_env_takes_precedence_and_rotates(self):
        k1 = crypto.get_flow_private_key()
        os.environ["KISNA_FLOW_PRIVATE_KEY_B64"] = b64encode(self.pem_b.encode()).decode()
        k2 = crypto.get_flow_private_key()
        self.assertNotEqual(_public_numbers(k1), _public_numbers(k2))

    def test_passphrase_protected_key(self):
        pem = _pem(b"s3cret")
        os.environ["KISNA_FLOW_PRIVATE_KEY"] = pem
        os.environ["KISNA_FLOW_PRIVATE_KEY_PASSPHRASE"] = "s3cret"
        self.assertIsNotNone(crypto.get_flow_private_key())

    def test_concurrent_first_use_parses_once(self):
        results = []
        barrier = threading.Barrier(16)
        with patch.object(crypto, "load_flow_private_key", wraps=crypto.load_flow_private_key) as load:
            def worker():
                barrier.wait()
                results.append(crypto.get_flow_private_key())

            threads = [threading.Thread(target=worker) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(load.call_count, 1)
        self.assertTrue(all(r is results[0] for r in results))

    def test_bad_key_is_not_cached(self):
        os.environ["KISNA_FLOW_PRIVATE_KEY"] = "not a pem"
        with self.assertRaises(Exception):
            crypto.get_flow_private_key()
        self.assertIsNone(crypto._cached_key)
        os.environ["KISNA_FLOW_PRIVATE_KEY"] = self.pem_a
        self.assertIsNotNone(crypto.get_flow_private_key())

    def test_decrypt_request_uses_the_cache(self):
        with patch.object(crypto, "get_flow_private_key", wraps=crypto.get_flow_private_key) as get:
            with self.assertRaises(crypto.FlowEndpointCryptoError):
                crypto.decrypt_request("AAAA", "AAAA", "AAAA")
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
