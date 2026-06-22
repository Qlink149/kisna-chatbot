"""
Universal API adapter for per-client catalog, offers, and store APIs.

Abstracts client-specific HTTP implementations behind a single async interface.
Kisna REST endpoints are implemented first; other clients raise NotImplementedError
on critical paths until their backends are added.
"""

from typing import Any

import httpx

from kisna_chatbot.config.base import ClientConfig
from kisna_chatbot.utils.kisna_url_tracking import append_kisna_utm
from kisna_chatbot.utils.logger_config import logger


class ClientAPIError(Exception):
    """Raised when a critical client API call fails."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class ClientAPIAdapter:
    """
    Async HTTP adapter for client-specific product, offers, and store APIs.

    Constructed with ClientConfig; uses product_api_base, offers_api_base,
    and store_api_base from the config for Kisna REST calls.
    """

    def __init__(self, config: ClientConfig) -> None:
        self._config = config
        self.client_id = config.client_id
        self._client = httpx.AsyncClient(timeout=30.0)

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _is_kisna(self) -> bool:
        return self.client_id == "kisna"

    def _unsupported(self) -> None:
        raise NotImplementedError(
            f"API adapter not implemented for client: {self.client_id}"
        )

    def _require_base(self, url: str, name: str) -> str:
        base = (url or "").rstrip("/")
        if not base:
            raise ValueError(f"{name} is not configured for client {self.client_id}")
        return base

    def _extract_list(
        self,
        payload: Any,
        keys: tuple[str, ...] = ("results", "products", "data", "items", "offers", "stores"),
    ) -> list:
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []

    def _normalize_product(self, item: dict) -> dict:
        return {
            "id": item.get("id") or item.get("product_id") or "",
            "title": item.get("title") or item.get("name") or "",
            "price": item.get("price"),
            "image": item.get("image") or item.get("image_url") or item.get("thumbnail"),
            "availability": item.get("availability") or item.get("in_stock"),
            "category": item.get("category"),
            "rating": item.get("rating"),
            "variants": item.get("variants") or [],
        }

    def _normalize_product_detail(self, data: dict) -> dict:
        return {
            "id": data.get("id") or data.get("product_id") or "",
            "title": data.get("title") or data.get("name") or "",
            "description": data.get("description") or "",
            "price": data.get("price"),
            "availability": data.get("availability") or data.get("in_stock"),
            "variants": data.get("variants") or [],
            "images": data.get("images") or data.get("image_urls") or [],
            "specs": data.get("specs") or data.get("specifications") or {},
            "rating": data.get("rating"),
            "reviews_count": data.get("reviews_count") or data.get("review_count"),
        }

    def _normalize_variant(self, variant: dict) -> dict:
        return {
            "id": variant.get("id") or variant.get("variant_id") or "",
            "label": variant.get("label") or variant.get("title") or variant.get("name") or "",
            "price": variant.get("price"),
            "available": variant.get("available", variant.get("in_stock", True)),
        }

    def _normalize_offer(self, offer: dict) -> dict:
        return {
            "id": offer.get("id") or offer.get("offer_id") or "",
            "title": offer.get("title") or offer.get("name") or "",
            "description": offer.get("description") or "",
            "code": offer.get("code") or offer.get("coupon_code"),
            "start_date": offer.get("start_date"),
            "end_date": offer.get("end_date"),
            "discount_percent": offer.get("discount_percent") or offer.get("discount"),
            "min_order_value": offer.get("min_order_value"),
        }

    def _normalize_store(self, store: dict) -> dict:
        return {
            "id": store.get("id") or store.get("store_id") or "",
            "name": store.get("name") or store.get("title") or "",
            "address": store.get("address") or "",
            "phone": store.get("phone") or store.get("phone_number"),
            "hours": store.get("hours") or store.get("opening_hours"),
            "latitude": store.get("latitude") or store.get("lat"),
            "longitude": store.get("longitude") or store.get("lng") or store.get("lon"),
        }

    def _normalize_pre_order(self, data: dict) -> dict:
        return {
            "id": data.get("id") or data.get("pre_order_id") or "",
            "payment_url": data.get("payment_url") or data.get("payment_link"),
            "confirmation_id": data.get("confirmation_id") or data.get("order_id"),
            "estimated_delivery": data.get("estimated_delivery"),
        }

    async def _get_json(self, url: str, params: dict | None = None) -> Any:
        try:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            raise ClientAPIError(
                f"GET {url} failed"
                + (f" with status {status}" if status else ""),
                cause=e,
            ) from e

    async def _post_json(self, url: str, json_body: dict) -> Any:
        try:
            response = await self._client.post(url, json=json_body)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            raise ClientAPIError(
                f"POST {url} failed"
                + (f" with status {status}" if status else ""),
                cause=e,
            ) from e

    async def search_products(
        self,
        query: str,
        category: str | None = None,
        price_min: float | None = None,
        price_max: float | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        Search the product catalog for the configured client.

        Args:
            query: Search text.
            category: Optional category filter.
            price_min: Optional minimum price.
            price_max: Optional maximum price.
            limit: Maximum number of results.

        Returns:
            List of normalized product dicts.

        Raises:
            NotImplementedError: If the client is not supported.
            ClientAPIError: If the HTTP request fails.
            ValueError: If product_api_base is not configured.

        HTTP contract (Kisna): GET {product_api_base}/search?q=<query>&limit=<n>.
        JSON must expose a list under results, products, data, or items.
        """
        if not self._is_kisna():
            self._unsupported()

        base = self._require_base(self._config.product_api_base, "product_api_base")
        url = f"{base}/search"
        params: dict[str, Any] = {"q": query, "limit": limit}
        if category is not None:
            params["category"] = category
        if price_min is not None:
            params["price_min"] = price_min
        if price_max is not None:
            params["price_max"] = price_max

        try:
            payload = await self._get_json(url, params=params)
            items = self._extract_list(payload)
            results = [self._normalize_product(item) for item in items if isinstance(item, dict)]
            logger.info(
                "Product search completed",
                extra={
                    "client_id": self.client_id,
                    "query": query,
                    "result_count": len(results),
                },
            )
            return results
        except Exception as e:
            logger.exception(
                "Product search failed",
                extra={
                    "client_id": self.client_id,
                    "query": query,
                    "error": str(e),
                },
            )
            raise

    async def get_product_details(self, product_id: str) -> dict:
        """
        Fetch full details for a single product.

        Args:
            product_id: Product identifier.

        Returns:
            Normalized product detail dict.

        Raises:
            NotImplementedError: If the client is not supported.
            ClientAPIError: If the HTTP request fails.
            ValueError: If product_api_base is not configured.
        """
        if not self._is_kisna():
            self._unsupported()

        base = self._require_base(self._config.product_api_base, "product_api_base")
        url = f"{base}/{product_id}"

        try:
            payload = await self._get_json(url)
            if isinstance(payload, dict) and "product" in payload:
                payload = payload["product"]
            if not isinstance(payload, dict):
                raise ClientAPIError(f"Unexpected product details response for {product_id}")
            result = self._normalize_product_detail(payload)
            logger.info(
                "Product details fetched",
                extra={
                    "client_id": self.client_id,
                    "product_id": product_id,
                },
            )
            return result
        except Exception as e:
            logger.exception(
                "Product details fetch failed",
                extra={
                    "client_id": self.client_id,
                    "product_id": product_id,
                    "error": str(e),
                },
            )
            raise

    async def get_product_variants(self, product_id: str) -> list[dict]:
        """
        Fetch variants for a product.

        Args:
            product_id: Product identifier.

        Returns:
            List of normalized variant dicts.

        Raises:
            NotImplementedError: If the client is not supported.
            ClientAPIError: If the HTTP request fails.
        """
        try:
            details = await self.get_product_details(product_id)
            raw_variants = details.get("variants") or []
            results = [
                self._normalize_variant(v)
                for v in raw_variants
                if isinstance(v, dict)
            ]
            logger.info(
                "Product variants fetched",
                extra={
                    "client_id": self.client_id,
                    "product_id": product_id,
                    "variant_count": len(results),
                },
            )
            return results
        except Exception as e:
            logger.exception(
                "Product variants fetch failed",
                extra={
                    "client_id": self.client_id,
                    "product_id": product_id,
                    "error": str(e),
                },
            )
            raise

    async def get_active_offers(self) -> list[dict]:
        """
        Fetch active offers and promotions.

        Returns:
            List of normalized offer dicts; empty list on error.
        """
        if not self._is_kisna():
            return []

        try:
            base = self._require_base(self._config.offers_api_base, "offers_api_base")
        except ValueError as e:
            logger.error(
                "Active offers fetch failed",
                extra={"client_id": self.client_id, "error": str(e)},
            )
            return []

        url = f"{base}/active"

        try:
            payload = await self._get_json(url)
            items = self._extract_list(payload, keys=("offers", "results", "data", "items"))
            results = [self._normalize_offer(item) for item in items if isinstance(item, dict)]
            logger.info(
                "Active offers fetched",
                extra={
                    "client_id": self.client_id,
                    "offer_count": len(results),
                },
            )
            return results
        except Exception as e:
            logger.error(
                "Active offers fetch failed",
                extra={
                    "client_id": self.client_id,
                    "error": str(e),
                },
            )
            return []

    async def get_nearby_stores(self, pincode: str) -> list[dict]:
        """
        Fetch stores near a pincode.

        Args:
            pincode: Postal pincode.

        Returns:
            List of normalized store dicts; empty list on error.
        """
        if not self._is_kisna():
            return []

        try:
            base = self._require_base(self._config.store_api_base, "store_api_base")
        except ValueError as e:
            logger.error(
                "Nearby stores fetch failed",
                extra={"client_id": self.client_id, "pincode": pincode, "error": str(e)},
            )
            return []

        url = f"{base}/nearby"

        try:
            payload = await self._get_json(url, params={"pincode": pincode})
            items = self._extract_list(payload, keys=("stores", "results", "data", "items"))
            results = [self._normalize_store(item) for item in items if isinstance(item, dict)]
            logger.info(
                "Nearby stores fetched",
                extra={
                    "client_id": self.client_id,
                    "pincode": pincode,
                    "store_count": len(results),
                },
            )
            return results
        except Exception as e:
            logger.error(
                "Nearby stores fetch failed",
                extra={
                    "client_id": self.client_id,
                    "pincode": pincode,
                    "error": str(e),
                },
            )
            return []

    async def create_pre_order(
        self,
        product_id: str,
        variant_id: str,
        phone_number: str,
        quantity: int = 1,
    ) -> dict:
        """
        Create a pre-order for a product variant.

        Args:
            product_id: Product identifier.
            variant_id: Variant identifier.
            phone_number: Customer phone number.
            quantity: Order quantity.

        Returns:
            Normalized pre-order dict with payment_url and confirmation_id.

        Raises:
            NotImplementedError: If the client is not supported.
            ClientAPIError: If the HTTP request fails.
            ValueError: If product_api_base is not configured.
        """
        if not self._is_kisna():
            self._unsupported()

        base = self._require_base(self._config.product_api_base, "product_api_base")
        url = f"{base}/pre-orders"
        body = {
            "product_id": product_id,
            "variant_id": variant_id,
            "phone": phone_number,
            "quantity": quantity,
        }

        try:
            payload = await self._post_json(url, body)
            if isinstance(payload, dict) and "pre_order" in payload:
                payload = payload["pre_order"]
            if not isinstance(payload, dict):
                raise ClientAPIError("Unexpected pre-order response")
            result = self._normalize_pre_order(payload)
            logger.info(
                "Pre-order created",
                extra={
                    "client_id": self.client_id,
                    "product_id": product_id,
                    "phone_number": phone_number,
                    "pre_order_id": result.get("id"),
                },
            )
            return result
        except Exception as e:
            logger.exception(
                "Pre-order creation failed",
                extra={
                    "client_id": self.client_id,
                    "product_id": product_id,
                    "phone_number": phone_number,
                    "error": str(e),
                },
            )
            raise

    def get_order_tracking_url(self, order_id: str) -> str:
        """
        Build the order tracking URL for the configured client.

        Uses KISNA_ORDER_TRACKING_URL or KISNA_TRACK_ORDER_URL when set;
        otherwise falls back to the Kisna website track-order page.
        """
        import os

        for key in ("KISNA_ORDER_TRACKING_URL", "KISNA_TRACK_ORDER_URL"):
            url = os.getenv(key, "").strip()
            if url:
                return append_kisna_utm(url)

        if self._config.client_id == "kisna":
            return append_kisna_utm("https://www.kisna.com/pages/track-order")

        base = self._require_base(self._config.product_api_base, "product_api_base")
        return f"{base}/track/{order_id}"
