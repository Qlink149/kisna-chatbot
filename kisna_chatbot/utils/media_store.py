"""Backblaze B2 (S3-compatible) object storage for WhatsApp media.

Durable, private storage for customer-sent and agent-sent media. The bucket is
never public — every read goes through a short-lived presigned GET, minted at
request time (see ``presign_get``). Configured entirely via env vars, read
lazily at call time so tests can monkeypatch them and a redeploy with the vars
unset is provably a no-op: ``is_configured()`` is the feature's on/off switch,
there is no separate boolean flag to keep in ``.env``.

Uses B2's S3-compatible API via boto3's plain ``s3`` client -- same calls as
any S3-compatible provider. B2's endpoint is per-region (there is no way to
derive it from the bucket or key alone) and its SigV4 signing requires the
real region name -- so both are explicit env vars here.

Env vars (all required together, see ``.env.example``):
    B2_ENDPOINT, B2_REGION, B2_KEY_ID, B2_APPLICATION_KEY, B2_BUCKET
"""

import os
import threading
import time
from functools import lru_cache

from kisna_chatbot.utils.logger_config import logger

_DEFAULT_MAX_BYTES = 20 * 1024 * 1024  # 20 MB


def _env(key: str) -> str:
    return (os.getenv(key) or "").strip()


def is_configured() -> bool:
    """True when every required B2 credential is set. The feature's kill switch:
    unset any of these and media capture/send silently falls back to today's
    behaviour everywhere it's called."""
    return bool(
        _env("B2_ENDPOINT")
        and _env("B2_REGION")
        and _env("B2_KEY_ID")
        and _env("B2_APPLICATION_KEY")
        and _env("B2_BUCKET")
    )


def max_bytes() -> int:
    try:
        return int(os.getenv("KISNA_MEDIA_MAX_BYTES", str(_DEFAULT_MAX_BYTES)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_BYTES


def _bucket() -> str:
    return _env("B2_BUCKET")


# The boto3 client is cheap to construct but not free (parses botocore's model
# files). Cache one per unique credential set -- in practice exactly one, but
# the cache key covers a credential rotation without a restart. Cleared
# automatically if the env changes are never observed mid-process; that's fine,
# a rotation is a redeploy anyway.
@lru_cache(maxsize=1)
def _client(endpoint: str, region: str, key_id: str, application_key: str):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=application_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 2}),
        region_name=region,
    )


def _get_client():
    return _client(
        _env("B2_ENDPOINT"), _env("B2_REGION"), _env("B2_KEY_ID"), _env("B2_APPLICATION_KEY")
    )


def put_bytes(data: bytes, key: str, content_type: str) -> bool:
    """Upload bytes to B2 under ``key``. Sync (boto3) -- callers on the async
    request path must run this via ``asyncio.to_thread``, same as every
    Gupshup sender in this repo keeps sync httpx off the event loop.

    Returns True on success, False on any failure (never raises) -- callers
    treat a storage failure exactly like a fetch failure: fall through to
    today's behaviour, never break the turn over it.
    """
    if not is_configured():
        return False
    try:
        _get_client().put_object(
            Bucket=_bucket(), Key=key, Body=data, ContentType=content_type or "application/octet-stream"
        )
        return True
    except Exception:
        logger.exception("B2 upload failed", extra={"key": key})
        return False


def presign_get(key: str, ttl_seconds: int) -> str | None:
    """Mint a short-lived signed GET URL for ``key``. None on failure or if
    B2 isn't configured -- callers must handle a missing URL (e.g. skip the
    outbound send, or render an "unavailable" placeholder)."""
    if not is_configured():
        return None
    try:
        return _get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": _bucket(), "Key": key},
            ExpiresIn=int(ttl_seconds),
        )
    except Exception:
        logger.exception("B2 presign failed", extra={"key": key})
        return None


# Display links, reused per (key, ttl) while more than half their life is left.
# A fresh signature on every call gave the same file a new URL on every
# 5-second dashboard refresh, so browsers downloaded every image and video in
# the open chat again each time -- 1 GB/day against 229 MB stored, and the B2
# daily download cap ran out (2026-10-07: every file "Media unavailable", agent
# media not fetchable by WhatsApp). One uvicorn worker, so one cache serves
# every request.
_STABLE_MAX_ENTRIES = 5000
_stable_links: dict[tuple[str, int], tuple[str, float]] = {}
_stable_lock = threading.Lock()


def presign_get_stable(key: str | None, ttl_seconds: int) -> str | None:
    """``presign_get`` for showing a file: the same URL for the same key until
    less than half of ``ttl_seconds`` remains, then a new one. Not for links
    handed to WhatsApp -- those use ``presign_get`` directly."""
    if not key:
        return None
    cache_key = (key, int(ttl_seconds))
    now = time.time()
    with _stable_lock:
        hit = _stable_links.get(cache_key)
        if hit and hit[1] - now > ttl_seconds / 2:
            return hit[0]
    url = presign_get(key, ttl_seconds)
    if url:
        with _stable_lock:
            if cache_key not in _stable_links and len(_stable_links) >= _STABLE_MAX_ENTRIES:
                _stable_links.pop(next(iter(_stable_links)))  # oldest insert
            _stable_links[cache_key] = (url, now + ttl_seconds)
    return url
