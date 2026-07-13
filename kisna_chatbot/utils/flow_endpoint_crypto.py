"""WhatsApp Flow endpoint encryption (data_api_version 3.0)."""

from __future__ import annotations

import json
import os
from base64 import b64decode, b64encode

from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import load_pem_private_key


class FlowEndpointCryptoError(Exception):
    """Raised when request decryption fails (return HTTP 421)."""


def _normalize_pem(raw: str) -> bytes:
    text = (raw or "").strip()
    if not text:
        raise FlowEndpointCryptoError("KISNA_FLOW_PRIVATE_KEY is empty")
    # Allow .env style with literal \n
    text = text.replace("\\n", "\n")
    return text.encode("utf-8")


def load_flow_private_key(
    private_key_pem: str | None = None,
    passphrase: str | None = None,
):
    pem = private_key_pem if private_key_pem is not None else os.getenv(
        "KISNA_FLOW_PRIVATE_KEY", ""
    )
    if passphrase is None:
        passphrase = os.getenv("KISNA_FLOW_PRIVATE_KEY_PASSPHRASE") or None
    password = passphrase.encode("utf-8") if passphrase else None
    return load_pem_private_key(_normalize_pem(pem), password=password)


def decrypt_request(
    encrypted_flow_data_b64: str,
    encrypted_aes_key_b64: str,
    initial_vector_b64: str,
    *,
    private_key=None,
) -> tuple[dict, bytes, bytes]:
    """
    Decrypt a Meta Flow endpoint request.

    Returns (decrypted_json, aes_key, iv).
    """
    try:
        flow_data = b64decode(encrypted_flow_data_b64)
        iv = b64decode(initial_vector_b64)
        encrypted_aes_key = b64decode(encrypted_aes_key_b64)
        key = private_key or load_flow_private_key()
        aes_key = key.decrypt(
            encrypted_aes_key,
            OAEP(
                mgf=MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        ciphertext, tag = flow_data[:-16], flow_data[-16:]
        decryptor = Cipher(
            algorithms.AES(aes_key), modes.GCM(iv, tag)
        ).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        return json.loads(plaintext.decode("utf-8")), aes_key, iv
    except FlowEndpointCryptoError:
        raise
    except Exception as e:
        raise FlowEndpointCryptoError(str(e)) from e


def encrypt_response(response: dict | str, aes_key: bytes, iv: bytes) -> str:
    """Encrypt response JSON; return base64 string (Meta expects text/plain body)."""
    flipped_iv = bytes(b ^ 0xFF for b in iv)
    payload = (
        response
        if isinstance(response, str)
        else json.dumps(response, separators=(",", ":"))
    )
    encryptor = Cipher(algorithms.AES(aes_key), modes.GCM(flipped_iv)).encryptor()
    ciphertext = (
        encryptor.update(payload.encode("utf-8"))
        + encryptor.finalize()
        + encryptor.tag
    )
    return b64encode(ciphertext).decode("utf-8")
