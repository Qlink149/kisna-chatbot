"""Short-TTL read layer over ``stores`` for the Store Visit Flow.

Every State / City / Store tap in the Flow is a data_exchange round trip that
Meta times out, so reads come from an in-process snapshot of the bookable
stores (170 today), refreshed every ``TTL_SECONDS`` or on ``bust()`` -- which
the importer and the dashboard toggles call after every write.
Only ``active && bookable`` stores are ever returned.
"""

from __future__ import annotations

import threading
import time

from pymongo import ASCENDING

TTL_SECONDS = 60

_lock = threading.Lock()
_snapshot: list[dict] | None = None
_loaded_at = 0.0


def _load() -> list[dict]:
    from kisna_chatbot.database.collections import stores

    return list(
        stores.find({"active": True, "bookable": True}, {"_id": 0}).sort(
            [("state", ASCENDING), ("city", ASCENDING), ("name", ASCENDING)]
        )
    )


def bust() -> None:
    global _snapshot, _loaded_at
    with _lock:
        _snapshot = None
        _loaded_at = 0.0


def _all() -> list[dict]:
    global _snapshot, _loaded_at
    now = time.monotonic()
    with _lock:
        if _snapshot is not None and now - _loaded_at < TTL_SECONDS:
            return _snapshot
    rows = _load()
    with _lock:
        _snapshot, _loaded_at = rows, time.monotonic()
    return rows


def _key(value: str | None) -> str:
    return (value or "").strip().lower()


def list_states() -> list[str]:
    """States with at least one bookable store, sorted."""
    return sorted({s["state"] for s in _all() if s.get("state")}, key=str.lower)


def list_cities(state: str) -> list[str]:
    want = _key(state)
    return sorted(
        {s["city"] for s in _all() if _key(s.get("state")) == want and s.get("city")},
        key=str.lower,
    )


def list_stores(state: str, city: str) -> list[dict]:
    ws, wc = _key(state), _key(city)
    rows = [s for s in _all() if _key(s.get("state")) == ws and _key(s.get("city")) == wc]
    return sorted(rows, key=lambda s: s.get("name", "").lower())


def get_store(store_id: str) -> dict | None:
    for s in _all():
        if s.get("store_id") == store_id:
            return s
    return None
