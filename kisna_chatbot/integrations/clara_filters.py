"""Clara /filters cache and sync accessors.

DEGRADATION CONTRACT
--------------------
When filters are unavailable (cold cache, failed refresh, missing snapshot),
the bot MUST behave EXACTLY as it did before this module existed: same wizard
steps, same client-side filtering, same search results. Dynamic behaviour is
an enhancement layered on top, never a dependency. Callers that receive None
/ [] / False from helpers must fall back to legacy paths. No user-visible
error and no dead end may be caused by a missing filters payload.

GET /filters is slow (~5s p50). Production is a long-lived single-worker
Docker process, so an in-process TTL cache is effective. User turns never
block on a cold or failed live fetch: we return last-good (or snapshot seed)
immediately and refresh in the background.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from kisna_chatbot.utils.logger_config import logger

_FILTERS_PATH = "/api/v1/clara/filters"
_DEFAULT_TTL_SECONDS = 21600  # 6 hours
_COLLECTION_FUZZY_THRESHOLD = 0.82
# Anantam / Evil Eye / Ti Amo all ship this as their collection slug upstream.
# It is a page type, not a filter token, so it must never reach a URL.
_JUNK_COLLECTION_SLUG = "pdp"
_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent / "data" / "clara_filters_snapshot.json"
)
_FETCH_TIMEOUT = 30.0

# Facet names as returned by Clara under data.*
FACET_KARAT = "karat"
FACET_COLOR = "color"
FACET_COLLECTION = "collection"
FACET_GENDER = "gender"
FACET_CATEGORIES = "categories"
FACET_AVAILABILITY = "availability"


@dataclass
class _CacheEntry:
    payload: dict[str, Any]
    etag: str | None = None
    fetched_at: float = field(default_factory=time.time)


# category_id -> entry; None key stores the global filters payload
_CACHE: dict[str | None, _CacheEntry] = {}
_REFRESH_LOCKS: dict[str | None, asyncio.Lock] = {}
_BACKGROUND_TASKS: set[asyncio.Task] = set()
_SNAPSHOT: dict[str, Any] | None = None
_SNAPSHOT_LOADED = False


def _ttl_seconds() -> int:
    raw = (os.getenv("CLARA_FILTERS_TTL_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_TTL_SECONDS
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_TTL_SECONDS
    except ValueError:
        return _DEFAULT_TTL_SECONDS


def _now() -> float:
    return time.time()


def _cache_key(category_id: str | None) -> str | None:
    if category_id is None:
        return None
    cleaned = str(category_id).strip()
    return cleaned or None


def _is_fresh(entry: _CacheEntry | None) -> bool:
    if entry is None:
        return False
    return (_now() - entry.fetched_at) < _ttl_seconds()


def _get_refresh_lock(key: str | None) -> asyncio.Lock:
    """Return a lock for this key, bound to the current running loop.

    asyncio.Lock is loop-bound; pytest creates a new loop per asyncio.run(),
    so we recreate locks when the loop identity changes.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    lock = _REFRESH_LOCKS.get(key)
    if lock is not None and loop is not None:
        try:
            if lock._loop is not loop:  # noqa: SLF001 — loop affinity check
                lock = None
        except AttributeError:
            lock = None
    if lock is None:
        lock = asyncio.Lock()
        _REFRESH_LOCKS[key] = lock
    return lock


def reset_filters_cache_for_tests() -> None:
    """Clear in-process state between unit tests."""
    global _SNAPSHOT, _SNAPSHOT_LOADED
    _CACHE.clear()
    _REFRESH_LOCKS.clear()
    for task in list(_BACKGROUND_TASKS):
        task.cancel()
    _BACKGROUND_TASKS.clear()
    _SNAPSHOT = None
    _SNAPSHOT_LOADED = False


def _load_snapshot() -> dict[str, Any] | None:
    global _SNAPSHOT, _SNAPSHOT_LOADED
    if _SNAPSHOT_LOADED:
        return _SNAPSHOT
    _SNAPSHOT_LOADED = True
    try:
        with open(_SNAPSHOT_PATH, encoding="utf-8") as fh:
            _SNAPSHOT = json.load(fh)
    except FileNotFoundError:
        logger.warning(
            "Clara filters snapshot missing",
            extra={"path": str(_SNAPSHOT_PATH)},
        )
        _SNAPSHOT = None
    except Exception:
        logger.exception("Failed to load Clara filters snapshot")
        _SNAPSHOT = None
    return _SNAPSHOT


def _seed_from_snapshot(category_id: str | None) -> dict[str, Any] | None:
    """Return snapshot payload and optionally seed the cache if empty."""
    snap = _load_snapshot()
    if not isinstance(snap, dict):
        return None
    key = _cache_key(category_id)
    if key is None:
        block = snap.get("global") or {}
        payload = block.get("payload")
        etag = block.get("etag")
    else:
        by_cat = snap.get("by_category") or {}
        block = by_cat.get(key) or {}
        payload = block.get("payload")
        etag = block.get("etag")
    if not isinstance(payload, dict):
        return None
    if key not in _CACHE:
        _CACHE[key] = _CacheEntry(
            payload=payload,
            etag=etag if isinstance(etag, str) else None,
            # Stale immediately so a live refresh is scheduled on first use,
            # but the seed is available for sync accessors during cold start.
            fetched_at=0.0,
        )
    return payload


def _base_url_and_key() -> tuple[str, str] | None:
    base = (os.getenv("KISNA_CLARA_BASE_URL") or "").strip().rstrip("/")
    key = (os.getenv("CLARA_API_KEY") or "").strip()
    if not base or not key:
        return None
    return base, key


async def _fetch_filters_live(
    category_id: str | None,
    *,
    etag: str | None = None,
) -> tuple[dict[str, Any] | None, str | None, bool]:
    """Fetch /filters. Returns (payload, etag, not_modified).

    not_modified=True means HTTP 304 — caller should keep existing payload.
    payload is None on hard failure.
    """
    creds = _base_url_and_key()
    if creds is None:
        return None, None, False
    base, api_key = creds
    params: dict[str, str] = {}
    key = _cache_key(category_id)
    if key:
        params["categoryId"] = key
    headers = {
        "x-clara-api-key": api_key,
        "Accept": "application/json",
    }
    if etag:
        headers["If-None-Match"] = etag
    url = f"{base}{_FILTERS_PATH}"
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=params or None)
            new_etag = response.headers.get("ETag")
            if response.status_code == 304:
                return None, new_etag or etag, True
            response.raise_for_status()
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict):
                logger.warning(
                    "Clara /filters unexpected shape",
                    extra={"status": response.status_code, "keys": list(body) if isinstance(body, dict) else type(body).__name__},
                )
                return None, new_etag, False
            return data, new_etag, False
    except Exception:
        logger.warning(
            "Clara /filters fetch failed",
            extra={"category_id": key},
            exc_info=True,
        )
        return None, None, False


def _store_entry(
    category_id: str | None,
    payload: dict[str, Any],
    etag: str | None,
) -> dict[str, Any]:
    key = _cache_key(category_id)
    _CACHE[key] = _CacheEntry(payload=payload, etag=etag, fetched_at=_now())
    return payload


async def _refresh_entry(category_id: str | None) -> dict[str, Any] | None:
    """Refresh one cache key under a lock. Returns payload or None on failure."""
    key = _cache_key(category_id)
    async with _get_refresh_lock(key):
        existing = _CACHE.get(key)
        if _is_fresh(existing):
            return existing.payload if existing else None
        etag = existing.etag if existing else None
        payload, new_etag, not_modified = await _fetch_filters_live(key, etag=etag)
        if not_modified and existing is not None:
            existing.fetched_at = _now()
            if new_etag:
                existing.etag = new_etag
            return existing.payload
        if payload is not None:
            return _store_entry(key, payload, new_etag)
        return existing.payload if existing else None


def _schedule_refresh(category_id: str | None) -> None:
    """Fire-and-forget background refresh; never awaited on the request path."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    key = _cache_key(category_id)
    existing = _CACHE.get(key)
    if _is_fresh(existing):
        return

    async def _runner() -> None:
        try:
            await _refresh_entry(key)
        except Exception:
            logger.warning(
                "Background Clara filters refresh failed",
                extra={"category_id": key},
                exc_info=True,
            )

    task = loop.create_task(_runner())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


def _resolve_cached_payload(category_id: str | None) -> dict[str, Any] | None:
    """Sync read: fresh cache, then last-good, then snapshot seed. May schedule refresh."""
    key = _cache_key(category_id)
    entry = _CACHE.get(key)
    if _is_fresh(entry):
        return entry.payload if entry else None
    if entry is not None:
        _schedule_refresh(key)
        return entry.payload
    seeded = _seed_from_snapshot(key)
    if seeded is not None:
        _schedule_refresh(key)
        return seeded
    _schedule_refresh(key)
    return None


async def get_filters(category_id: str | None = None) -> dict[str, Any] | None:
    """Return the parsed /filters payload for global or category scope.

    Never blocks a user turn on a cold live fetch: returns last-good or
    snapshot immediately and refreshes in the background. Returns None only
    when nothing is available (no cache, no snapshot).
    """
    key = _cache_key(category_id)
    entry = _CACHE.get(key)
    if _is_fresh(entry):
        return entry.payload if entry else None
    if entry is not None:
        _schedule_refresh(key)
        return entry.payload
    seeded = _seed_from_snapshot(key)
    if seeded is not None:
        _schedule_refresh(key)
        return seeded
    # No last-good and no snapshot — attempt one live fetch (startup / rare).
    refreshed = await _refresh_entry(key)
    return refreshed


async def warm_filters_cache() -> dict[str, Any]:
    """Warm global + all category scopes concurrently (bounded). Never raises.

    Intended for FastAPI startup: callers should schedule this without awaiting
    the full warm if they need to accept traffic immediately; awaiting is fine
    when the warm itself is already a background task.
    """
    t0 = _now()
    # Seed sync accessors from the committed snapshot first.
    _seed_from_snapshot(None)
    snap = _load_snapshot()
    category_ids: list[str] = []
    if isinstance(snap, dict):
        global_payload = ((snap.get("global") or {}).get("payload") or {})
        for cat in global_payload.get("categories") or []:
            if isinstance(cat, dict) and cat.get("value"):
                category_ids.append(str(cat["value"]))
        for cid in (snap.get("by_category") or {}):
            if cid not in category_ids:
                category_ids.append(cid)
            _seed_from_snapshot(cid)

    sem = asyncio.Semaphore(4)
    ok = 0
    failed = 0

    async def _one(cid: str | None) -> None:
        nonlocal ok, failed
        async with sem:
            result = await _refresh_entry(cid)
            if result is not None:
                ok += 1
            else:
                failed += 1

    await _one(None)
    if category_ids:
        await asyncio.gather(*(_one(cid) for cid in category_ids))

    elapsed_ms = round((_now() - t0) * 1000, 1)
    summary = {
        "warmed": ok,
        "failed": failed,
        "categories": len(category_ids),
        "elapsed_ms": elapsed_ms,
    }
    logger.info(
        "Clara filters cache warm complete",
        extra=summary,
    )
    return summary


# ── Sync accessors (read cache / snapshot only; never I/O) ───────────────────


def _options(payload: dict[str, Any] | None, facet: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get(facet)
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _norm_label(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def _match_option(
    options: list[dict],
    needle: str | None,
    *,
    fuzzy: bool = False,
    threshold: float = _COLLECTION_FUZZY_THRESHOLD,
) -> dict | None:
    if not needle or not options:
        return None
    want = _norm_label(needle)
    if not want:
        return None
    for opt in options:
        for field_name in ("label", "slug", "value"):
            candidate = _norm_label(str(opt.get(field_name) or ""))
            if candidate and candidate == want:
                return opt
        # Strip trailing " collection" for labels like "Evil Eye Collection"
        label = _norm_label(str(opt.get("label") or ""))
        if label.endswith(" collection"):
            label = label[: -len(" collection")].strip()
        if label and label == want:
            return opt
    if not fuzzy:
        return None
    best: dict | None = None
    best_score = 0.0
    for opt in options:
        label = _norm_label(str(opt.get("label") or ""))
        bare = (
            label[: -len(" collection")].strip()
            if label.endswith(" collection")
            else label
        )
        for candidate in (label, bare, _norm_label(str(opt.get("slug") or ""))):
            if not candidate:
                continue
            score = difflib.SequenceMatcher(None, want, candidate).ratio()
            if score > best_score:
                best_score = score
                best = opt
    if best is not None and best_score >= threshold:
        return best
    return None


def get_category_id(internal_category: str) -> str | None:
    """Map bot/internal category name or slug to Clara categoryId."""
    payload = _resolve_cached_payload(None)
    options = _options(payload, FACET_CATEGORIES)
    if not options:
        return None
    needle = _norm_label(internal_category)
    # Common singular/plural + underscore forms
    variants = {
        needle,
        needle.replace("_", " "),
        needle.replace("-", " "),
    }
    if needle.endswith("s") and len(needle) > 1:
        variants.add(needle[:-1])
    else:
        variants.add(needle + "s")
    for variant in variants:
        matched = _match_option(options, variant, fuzzy=False)
        if matched and matched.get("value"):
            return str(matched["value"])
    matched = _match_option(options, needle, fuzzy=True, threshold=0.9)
    if matched and matched.get("value"):
        return str(matched["value"])
    return None


def get_karat_id(category_id: str | None, karat_label: str) -> str | None:
    payload = _resolve_cached_payload(category_id) or _resolve_cached_payload(None)
    matched = _match_option(_options(payload, FACET_KARAT), karat_label)
    if matched and matched.get("value"):
        return str(matched["value"])
    return None


def get_colour_id(category_id: str | None, colour_label: str) -> str | None:
    payload = _resolve_cached_payload(category_id) or _resolve_cached_payload(None)
    # Accept rose / rose gold style labels
    needle = _norm_label(colour_label).replace(" gold", "").strip()
    matched = _match_option(_options(payload, FACET_COLOR), needle)
    if matched and matched.get("value"):
        return str(matched["value"])
    return None


def get_collection_id(collection_name: str) -> str | None:
    """Fuzzy-match a free-text collection guess against the live/global list."""
    payload = _resolve_cached_payload(None)
    matched = _match_option(
        _options(payload, FACET_COLLECTION),
        collection_name,
        fuzzy=True,
        threshold=_COLLECTION_FUZZY_THRESHOLD,
    )
    if matched and matched.get("value"):
        return str(matched["value"])
    return None


def get_collection_slug(
    collection_name: str, *, fuzzy: bool = True
) -> str | None:
    """Site URL slug for a collection, for catalogue deep-links.

    Most collections slug as "<name>-collection", but six are bare (Echo,
    Esme, Heart String, Tiny Tales, Vachan, Valentine 2025) — which is why
    this reads the real slug instead of appending a suffix. Three entries
    (Anantam, Evil Eye, Ti Amo) carry "pdp" as their slug upstream; that is a
    Clara data bug, not a real filter, so fall back to the label.
    """
    payload = _resolve_cached_payload(None)
    matched = _match_option(
        _options(payload, FACET_COLLECTION),
        collection_name,
        fuzzy=fuzzy,
        threshold=_COLLECTION_FUZZY_THRESHOLD,
    )
    if not matched:
        return None
    slug = _norm_label(str(matched.get("slug") or "")).replace(" ", "-")
    if slug and slug != _JUNK_COLLECTION_SLUG:
        return slug
    label = _norm_label(str(matched.get("label") or ""))
    if not label:
        return None
    return re.sub(r"[^a-z0-9]+", "-", label).strip("-") or None


def get_gender_tag_id(gender: str) -> str | None:
    """Map bot-canonical gender (men/women/kids) to Clara tagManagerId."""
    payload = _resolve_cached_payload(None)
    options = _options(payload, FACET_GENDER)
    aliases = {
        "women": ("women", "female", "for her"),
        "men": ("men", "mens", "male", "for him"),
        "kids": ("kids", "children", "child"),
    }
    key = _norm_label(gender)
    needles = aliases.get(key, (key,))
    for needle in needles:
        matched = _match_option(options, needle)
        if matched and matched.get("value"):
            return str(matched["value"])
    # Fall back to hardcoded map used historically (cold-path safety).
    from kisna_chatbot.integrations.clara_api import GENDER_TAG_MANAGER_IDS

    return GENDER_TAG_MANAGER_IDS.get(key)


def get_available_options(
    category_id: str | None,
    facet: str,
    *,
    fallback_global: bool = True,
) -> list[dict]:
    """Return facet options for a category scope.

    When ``fallback_global`` is True (default) and the category payload is
    missing, fall back to the global filters list. Wizard skip logic should
    pass ``fallback_global=False`` so an empty per-category facet (e.g.
    Souvenir gender=0) is not replaced by the global 3-gender list.
    """
    payload = _resolve_cached_payload(category_id) if category_id else None
    if payload is None and category_id and fallback_global:
        payload = _resolve_cached_payload(None)
    elif payload is None and category_id is None:
        payload = _resolve_cached_payload(None)
    return list(_options(payload, facet))


def is_value_available(
    category_id: str | None,
    facet: str,
    value: str,
) -> bool:
    options = get_available_options(category_id, facet)
    if not options:
        # Cold / empty: callers must skip validation (degradation contract).
        return False
    if facet == FACET_GENDER:
        aliases = {
            "women": ("women", "female", "for her"),
            "men": ("men", "mens", "male", "for him"),
            "kids": ("kids", "children", "child"),
        }
        key = _norm_label(value)
        needles = aliases.get(key, (key,))
        return any(_match_option(options, needle) is not None for needle in needles)
    fuzzy = facet == FACET_COLLECTION
    return _match_option(options, value, fuzzy=fuzzy) is not None


def filters_available() -> bool:
    """True when any filters payload (live or snapshot-seeded) can be read."""
    return _resolve_cached_payload(None) is not None
