"""
Clara API client for KISNA Diamond & Gold catalogue, promotions, and stores.
"""

import os
from typing import Any, Optional

import httpx

from kisna_chatbot.utils.http_log import log_http_request, log_http_response
from kisna_chatbot.utils.logger_config import logger

_TIMEOUT = 15.0
_USER_TIMEOUT = (
    "We're having trouble reaching our catalogue right now. Please try again in a moment."
)
_USER_GENERIC = (
    "Something went wrong while fetching products. Please try again shortly."
)


class ClaraAPIError(Exception):
    """Raised when a Clara API call fails; user_message is safe to show on WhatsApp."""

    def __init__(self, user_message: str, status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


def _base_url() -> str:
    base = (os.getenv("KISNA_CLARA_BASE_URL") or "").strip().rstrip("/")
    if not base:
        raise ClaraAPIError(
            "Our product catalogue isn't connected yet. Please try again later.",
            status_code=None,
        )
    return base


def _api_key() -> str:
    key = (os.getenv("CLARA_API_KEY") or "").strip()
    if not key:
        raise ClaraAPIError(
            "Our product catalogue isn't connected yet. Please try again later.",
            status_code=None,
        )
    return key


def _headers() -> dict[str, str]:
    return {"x-clara-api-key": _api_key()}


async def _request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
) -> Any:
    url = f"{_base_url()}{path}"
    start = log_http_request("clara", method, url, params=params)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.request(
                method,
                url,
                headers=_headers(),
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            log_http_response(
                "clara",
                method,
                url,
                start=start,
                status_code=response.status_code,
                body_preview=data,
            )
            return data
    except httpx.TimeoutException:
        log_http_response(
            "clara", method, url, start=start, error="timeout"
        )
        logger.error("Clara API timeout", extra={"url": url, "params": params})
        raise ClaraAPIError(_USER_TIMEOUT) from None
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        body_preview = (e.response.text or "")[:200]
        log_http_response(
            "clara",
            method,
            url,
            start=start,
            status_code=status,
            body_preview=body_preview,
            error="http_error",
        )
        logger.error(
            "Clara API HTTP error",
            extra={"url": url, "status": status, "body": body_preview},
        )
        raise ClaraAPIError(_USER_GENERIC, status_code=status) from e
    except ClaraAPIError:
        raise
    except Exception as exc:
        log_http_response(
            "clara", method, url, start=start, error=str(exc)
        )
        logger.exception("Clara API unexpected error", extra={"url": url})
        raise ClaraAPIError(_USER_GENERIC) from None


def _extract_list_payload(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, list):
            return inner
        if isinstance(inner, dict):
            nested = inner.get("data")
            if isinstance(nested, list):
                return nested
    return []


async def search_products(
    category: str | None = None,
    material_type: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    title: str | None = None,
    page_no: int = 1,
    page_size: int = 5,
) -> dict:
    """
    Search products via Clara API. Never cached — pricing changes daily.

    Returns:
        {"products": [...], "total_count": int, "page": int}
    """
    # searchUrl=true returns full product objects including mediaUrl[].image for WhatsApp.
    params: dict[str, Any] = {
        "pageNo": page_no,
        "pageSize": page_size,
        "searchUrl": "true",
    }
    if category is not None:
        params["category"] = category
    if material_type is not None:
        params["materialType"] = material_type
    if min_price is not None:
        params["minPrice"] = min_price
    if max_price is not None:
        params["maxPrice"] = max_price
    if title is not None:
        params["title"] = title

    body = await _request("GET", "/api/v1/clara/products", params=params)
    data_block = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data_block, dict):
        data_block = {}

    products = data_block.get("data")
    if not isinstance(products, list):
        products = []

    total_count = data_block.get("totalCount", 0)
    try:
        total_count = int(total_count)
    except (TypeError, ValueError):
        total_count = len(products)

    logger.info(
        "Clara product search completed",
        extra={
            "page": page_no,
            "page_size": page_size,
            "result_count": len(products),
            "total_count": total_count,
        },
    )
    return {"products": products, "total_count": total_count, "page": page_no}


async def get_promotions() -> list:
    """Fetch promotions; caller is responsible for caching."""
    body = await _request("GET", "/api/v1/clara/promotions")
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            return data
    return []


async def get_stores(
    name: str | None = None,
    pincode: str | None = None,
    page_no: int = 1,
    page_size: int = 5,
) -> dict:
    """Fetch stores by name and/or pincode only."""
    params: dict[str, Any] = {
        "pageNo": page_no,
        "pageSize": page_size,
    }
    if name is not None:
        params["name"] = name
    if pincode is not None:
        params["pincode"] = pincode

    body = await _request("GET", "/api/v1/clara/stores", params=params)
    data_block = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data_block, dict):
        data_block = {}

    stores = data_block.get("data")
    if not isinstance(stores, list):
        stores = _extract_list_payload(body)

    total_count = data_block.get("totalCount", len(stores))
    try:
        total_count = int(total_count)
    except (TypeError, ValueError):
        total_count = len(stores)

    return {"stores": stores, "total_count": total_count}


def get_discount_for_product(product: dict) -> Optional[str]:
    """
    Pure function: match variant price against promotion labour discount ranges.
    Returns e.g. '10% off making charges' or None.
    """
    price_block = product.get("price") or {}
    variant_price = price_block.get("variantPrice")
    if variant_price is None:
        return None

    try:
        price = float(variant_price)
    except (TypeError, ValueError):
        return None

    promotions = product.get("promotions") or []
    if not isinstance(promotions, list):
        return None

    for promo in promotions:
        if not isinstance(promo, dict):
            continue
        disc_on = promo.get("discOn")
        if disc_on != "Labour":
            continue
        try:
            from_amt = float(promo.get("fromAmt", 0))
            to_amt = float(promo.get("toAmt", float("inf")))
        except (TypeError, ValueError):
            continue
        if from_amt <= price <= to_amt:
            disc = promo.get("disc")
            if disc is not None:
                try:
                    disc_val = float(disc)
                    if disc_val == int(disc_val):
                        return f"{int(disc_val)}% off making charges"
                    return f"{disc_val}% off making charges"
                except (TypeError, ValueError):
                    pass
    return None
