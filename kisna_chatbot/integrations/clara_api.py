"""
Clara API client for KISNA Diamond & Gold catalogue, promotions, and stores.
"""

import os
from typing import Any, Optional

import httpx

from kisna_chatbot.utils.http_log import log_http_request, log_http_response
from kisna_chatbot.utils.logger_config import logger

_TIMEOUT = 15.0
DEFAULT_API_PAGE_SIZE = 15
CLIENT_SIDE_FILTER_PAGE_SIZE = 50
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
        if status == 400:
            logger.error(
                "Clara API 400",
                extra={
                    "url": str(e.response.url),
                    "params": dict(e.request.url.params) if e.request.url else params,
                    "body": (e.response.text or "")[:500],
                },
            )
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


def _omit_empty_params(params: dict[str, Any]) -> dict[str, Any]:
    """Drop None and blank string values before sending to Clara API."""
    return {
        key: value
        for key, value in params.items()
        if value is not None and (not isinstance(value, str) or value.strip())
    }


# Gender tagManagerId values from GET /api/v1/clara/filters (availability/gender).
# Keys are bot-canonical gender labels (men → Mens slug in Clara).
GENDER_TAG_MANAGER_IDS: dict[str, str] = {
    "women": "6710b86de3421b6a92589b39",
    "men": "66ec862c348e37f29673a282",
    "kids": "66ec7af6cc1fc61e0532a14c",
}


def build_products_query_params(
    *,
    category: str | None = None,
    material_type: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    title: str | None = None,
    tag_manager_id: str | None = None,
    collection_id: str | None = None,
    meta_sub_attribute_value: str | None = None,
    ready_to_ship: bool | None = None,
    made_to_order: bool | None = None,
    page_no: int = 1,
    page_size: int = 5,
) -> dict[str, Any]:
    """
    Build Clara GET /api/v1/clara/products query params.

    Core filters: category, materialType, minPrice, maxPrice, title.
    Extended filters from /clara/filters:
      - tagManagerId (gender)
      - collectionId
      - metaSubAttributeValue (karat / color)
      - readyTOShip / madeToOrder (availability) — note Clara's readyTOShip casing
    """
    params: dict[str, Any] = {
        "pageNo": page_no,
        "pageSize": page_size,
    }
    has_filters = False

    if category is not None and str(category).strip():
        params["category"] = str(category).strip()
        has_filters = True
    if material_type is not None and str(material_type).strip():
        params["materialType"] = str(material_type).strip()
        has_filters = True
    if min_price is not None:
        params["minPrice"] = int(min_price)
        has_filters = True
    if max_price is not None:
        params["maxPrice"] = int(max_price)
        has_filters = True
    if title is not None and str(title).strip():
        params["title"] = str(title).strip()
        has_filters = True
    if tag_manager_id is not None and str(tag_manager_id).strip():
        params["tagManagerId"] = str(tag_manager_id).strip()
        has_filters = True
    if collection_id is not None and str(collection_id).strip():
        params["collectionId"] = str(collection_id).strip()
        has_filters = True
    if meta_sub_attribute_value is not None and str(meta_sub_attribute_value).strip():
        params["metaSubAttributeValue"] = str(meta_sub_attribute_value).strip()
        has_filters = True
    # Availability booleans from /clara/filters (queryParams: readyTOShip, madeToOrder).
    # Semantics (confirmed with Kisna):
    #   - Every product can be made-to-order (MTO is a capability, not a SKU subset).
    #   - readyTOShip=true → in-stock / ready-to-ship subset only.
    #   - madeToOrder=true → full matching catalog (expected; do not treat as a subset filter).
    # Never send both flags together.
    if ready_to_ship:
        params["readyTOShip"] = "true"
        has_filters = True
    elif made_to_order:
        params["madeToOrder"] = "true"
        has_filters = True

    if has_filters:
        params["searchUrl"] = "true"

    return _omit_empty_params(params)


def parse_products_response(body: Any, *, page_no: int = 1) -> dict:
    """
    Parse Clara products API JSON into bot-internal shape.

    Expected: {"data": {"data": [...], "totalCount": N}}
    """
    data_block = body.get("data") if isinstance(body, dict) else {}
    if not isinstance(data_block, dict):
        data_block = {}

    products = data_block.get("data")
    if not isinstance(products, list):
        products = _extract_list_payload(body)

    total_count = data_block.get("totalCount", 0)
    try:
        total_count = int(total_count)
    except (TypeError, ValueError):
        total_count = len(products)

    return {"products": products, "total_count": total_count, "page": page_no}


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
    tag_manager_id: str | None = None,
    collection_id: str | None = None,
    meta_sub_attribute_value: str | None = None,
    ready_to_ship: bool | None = None,
    made_to_order: bool | None = None,
    page_no: int = 1,
    page_size: int = 5,
) -> dict:
    """
    Search products via Clara API. Never cached — pricing changes daily.

    Query params: pageNo, pageSize, materialType, minPrice, maxPrice, category,
    title, tagManagerId, collectionId, metaSubAttributeValue, readyTOShip,
    madeToOrder, searchUrl=true.

    List prices use price.variantPrice; WhatsApp display/MRP use API fields only
    via utils.price_calculator (no computed MRP).

    Returns:
        {"products": [...], "total_count": int, "page": int}
    """
    params = build_products_query_params(
        category=category,
        material_type=material_type,
        min_price=min_price,
        max_price=max_price,
        title=title,
        tag_manager_id=tag_manager_id,
        collection_id=collection_id,
        meta_sub_attribute_value=meta_sub_attribute_value,
        ready_to_ship=ready_to_ship,
        made_to_order=made_to_order,
        page_no=page_no,
        page_size=page_size,
    )

    body = await _request("GET", "/api/v1/clara/products", params=params)
    result = parse_products_response(body, page_no=page_no)

    logger.info(
        "Clara product search completed",
        extra={
            "page": page_no,
            "page_size": page_size,
            "result_count": len(result["products"]),
            "total_count": result["total_count"],
        },
    )
    return result


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
    city: str | None = None,
    page_no: int | None = None,
    page_size: int | None = None,
) -> dict:
    """Fetch stores by pincode, name, or city (city is sent as name filter)."""
    params: dict[str, Any] = {}
    if page_no is not None:
        params["pageNo"] = page_no
    if page_size is not None:
        params["pageSize"] = page_size
    if pincode is not None and str(pincode).strip():
        params["pincode"] = str(pincode).strip()
    elif city is not None and str(city).strip():
        params["name"] = str(city).strip()
    elif name is not None and str(name).strip():
        params["name"] = str(name).strip()
    params = _omit_empty_params(params)

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


async def get_gold_rates() -> Any:
    """Fetch live gold rates; caller is responsible for caching."""
    return await _request("GET", "/api/v1/clara/rates")


def get_discount_for_product(product: dict) -> Optional[str]:
    """
    Pure function: match variant price against promotion labour discount ranges.
    Returns e.g. '10% off making charges' or None.
    """
    from kisna_chatbot.utils.price_calculator import (
        base_listing_price,
        find_matching_labour_promo,
        format_promo_label,
    )

    listing = base_listing_price(product)
    if not listing:
        return None
    promo = find_matching_labour_promo(product, float(listing))
    if not promo:
        return None
    return format_promo_label(promo)
