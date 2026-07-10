"""
In-memory cache for Clara promotions and stores (refreshed on TTL or startup).
"""

import time
from typing import Any

from kisna_chatbot.integrations.clara_api import get_gold_rates, get_promotions, get_stores
from kisna_chatbot.utils.logger_config import logger

PROMOTIONS_TTL_SECONDS = 2 * 3600
STORES_TTL_SECONDS = 24 * 3600
GOLD_RATES_TTL_SECONDS = 15 * 60

_EMPTY_STORES = {"stores": [], "total_count": 0}


def _now() -> float:
    return time.time()


def _is_stale(fetched_at: float | None, ttl: int) -> bool:
    if fetched_at is None:
        return True
    return (_now() - fetched_at) >= ttl


async def _refresh_promotions(app_state: Any) -> list:
    promotions = await get_promotions()
    if app_state is not None:
        app_state.promotions_cache = promotions
        app_state.promotions_fetched_at = _now()
    return promotions


async def _refresh_stores(app_state: Any) -> dict:
    result = await get_stores()
    if app_state is not None:
        app_state.stores_cache = result
        app_state.stores_fetched_at = _now()
    return result


async def warm_clara_caches(app_state: Any) -> None:
    """Populate app.state caches on startup; never raises."""
    if app_state is None:
        return

    app_state.promotions_cache = []
    app_state.promotions_fetched_at = None
    app_state.stores_cache = dict(_EMPTY_STORES)
    app_state.stores_fetched_at = None
    app_state.gold_rates_cache = None
    app_state.gold_rates_fetched_at = None

    try:
        app_state.promotions_cache = await get_promotions()
        app_state.promotions_fetched_at = _now()
        logger.info(
            "Promotions cache loaded",
            extra={"count": len(app_state.promotions_cache)},
        )
    except Exception:
        logger.warning("Promotions cache startup failed", exc_info=True)

    try:
        app_state.stores_cache = await get_stores()
        app_state.stores_fetched_at = _now()
        count = len((app_state.stores_cache or {}).get("stores") or [])
        logger.info("Stores cache loaded", extra={"count": count})
    except Exception:
        logger.warning("Stores cache startup failed", exc_info=True)


async def get_cached_promotions(app_state: Any) -> list:
    """Return promotions list; refresh if older than 2 hours."""
    if app_state is None:
        return await get_promotions()

    cache = getattr(app_state, "promotions_cache", None)
    fetched_at = getattr(app_state, "promotions_fetched_at", None)

    if not _is_stale(fetched_at, PROMOTIONS_TTL_SECONDS) and isinstance(cache, list):
        return cache

    try:
        return await _refresh_promotions(app_state)
    except Exception:
        logger.warning("Promotions cache refresh failed", exc_info=True)
        if isinstance(cache, list):
            return cache
        return []


async def get_cached_stores(app_state: Any) -> dict:
    """Return stores dict; refresh if older than 24 hours."""
    if app_state is None:
        return await get_stores()

    cache = getattr(app_state, "stores_cache", None)
    fetched_at = getattr(app_state, "stores_fetched_at", None)

    if not _is_stale(fetched_at, STORES_TTL_SECONDS) and isinstance(cache, dict):
        return cache

    try:
        return await _refresh_stores(app_state)
    except Exception:
        logger.warning("Stores cache refresh failed", exc_info=True)
        if isinstance(cache, dict):
            return cache
        return dict(_EMPTY_STORES)


async def get_cached_gold_rates(app_state: Any) -> Any:
    """Return gold rates payload; refresh if older than 15 minutes."""
    if app_state is None:
        return await get_gold_rates()

    cache = getattr(app_state, "gold_rates_cache", None)
    fetched_at = getattr(app_state, "gold_rates_fetched_at", None)

    if not _is_stale(fetched_at, GOLD_RATES_TTL_SECONDS) and cache is not None:
        return cache

    try:
        rates = await get_gold_rates()
        if app_state is not None:
            app_state.gold_rates_cache = rates
            app_state.gold_rates_fetched_at = _now()
        return rates
    except Exception:
        logger.warning("Gold rates cache refresh failed", exc_info=True)
        if cache is not None:
            return cache
        raise
