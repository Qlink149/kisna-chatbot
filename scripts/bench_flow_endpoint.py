"""p95 latency of the encrypted Flow endpoint, per form (callback, video
call, store visit). Local: an in-process FastAPI app with the real route, a
throwaway RSA key in the env, Mongo reads stubbed -- so this measures the
endpoint code (crypto + handler), not the network.

    python scripts/bench_flow_endpoint.py [--calls 200]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from base64 import b64encode
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.padding import MGF1, OAEP  # noqa: E402
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: E402

STORES = [
    {
        "store_id": "D1", "name": "Karol Bagh - Delhi-NCR - Delhi", "address": "Ajmal Khan Road",
        "city": "Delhi-NCR", "state": "Delhi", "pincode": "110005", "phone": "",
        "open_time": "10:30", "close_time": "20:00", "weekly_off": [], "bookable": True, "active": True,
    }
]


def _encrypt(key, payload):
    aes_key, iv = os.urandom(16), os.urandom(16)
    enc_key = key.public_key().encrypt(
        aes_key, OAEP(mgf=MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
    )
    enc = Cipher(algorithms.AES(aes_key), modes.GCM(iv)).encryptor()
    ct = enc.update(json.dumps(payload).encode()) + enc.finalize() + enc.tag
    return {
        "encrypted_flow_data": b64encode(ct).decode(),
        "encrypted_aes_key": b64encode(enc_key).decode(),
        "initial_vector": b64encode(iv).decode(),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calls", type=int, default=200)
    ap.add_argument(
        "--no-cache",
        action="store_true",
        help="parse the key on every request (the behaviour before the key cache)",
    )
    args = ap.parse_args()
    if args.no_cache:
        from kisna_chatbot.utils import flow_endpoint_crypto as crypto

        crypto.get_flow_private_key = crypto.load_flow_private_key

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    os.environ["KISNA_FLOW_PRIVATE_KEY"] = pem
    os.environ["KISNA_FLOW_PRIVATE_KEY_B64"] = ""

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from kisna_chatbot.routes import whatsapp_flows
    from kisna_chatbot.stores import cache as store_cache
    from kisna_chatbot.utils.support_slots import set_capacity_overrides

    set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)
    app = FastAPI()
    app.include_router(whatsapp_flows.router)
    client = TestClient(app)

    day = (date.today() + timedelta(days=2)).isoformat()
    forms = {
        "callback": {"action": "data_exchange", "screen": "CALLBACK_REQUEST",
                     "data": {"preferred_date": day, "trigger": "date_selected"}, "flow_token": "cb"},
        "video_call": {"action": "data_exchange", "screen": "VIDEO_CALL_REQUEST",
                       "data": {"preferred_date": day, "trigger": "date_selected"}, "flow_token": "vc"},
        "store_visit": {"action": "data_exchange", "screen": "SV_STORE", "flow_token": "sv:1:2",
                        "data": {"step": "city", "state": "Delhi", "city": "Delhi-NCR",
                                 "first_name": "A", "phone": "919812345678", "looking_for": "other"}},
    }
    with patch.object(store_cache, "_load", return_value=STORES):
        for name, payload in forms.items():
            times = []
            for _ in range(args.calls):
                body = _encrypt(key, payload)
                t = time.perf_counter()
                resp = client.post("/whatsapp/flows/data-exchange", json=body)
                times.append((time.perf_counter() - t) * 1000)
                assert resp.status_code == 200, (name, resp.status_code, resp.text[:200])
            p50 = statistics.median(times)
            p95 = statistics.quantiles(times, n=20)[18]
            print(f"{name:12} p50={p50:7.1f} ms  p95={p95:7.1f} ms  ({args.calls} calls)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
