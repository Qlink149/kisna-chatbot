"""
Multi-client configuration registry for the WhatsApp chatbot platform.

Loads per-client settings from environment variables at resolve time so
load_dotenv() in env_load runs before API bases are read.
"""

import os
from functools import lru_cache

from kisna_chatbot.config.base import ClientConfig

# Ensure .env is loaded before any ClientConfig is built.
from kisna_chatbot.utils import env_load as _env_load  # noqa: F401

NKL_SHOPIFY_MCP_URL = "https://nilkamal-sleep.myshopify.com/api/mcp"

KISNA_INTENT_CATEGORIES = [
    "general",
    "product",
    "main_menu",
    "store_locator",
    "offers",
    "pre_order",
    "order_tracking",
    "human_handoff",
]

NKL_INTENT_CATEGORIES = [
    "general",
    "product",
    "main_menu",
    "store_locator",
    "damage_complaint",
    "human_handoff",
]


def _env(key: str) -> str:
    """Read an environment variable, defaulting to empty string if unset."""
    return os.getenv(key, "")


def _kisna_config() -> ClientConfig:
    return ClientConfig(
        client_id="kisna",
        brand_name="Kisna Jewellery",
        brand_voice="trendy, energetic, design expert, warm",
        product_api_base=_env("KISNA_PRODUCT_API"),
        offers_api_base=_env("KISNA_OFFERS_API"),
        store_api_base=_env("KISNA_STORE_API"),
        vtiger_base=_env("KISNA_VTIGER_BASE"),
        vtiger_token=_env("KISNA_VTIGER_TOKEN"),
        intent_categories=KISNA_INTENT_CATEGORIES,
    )


def _nkl_config() -> ClientConfig:
    return ClientConfig(
        client_id="nkl",
        brand_name="Nilkamal Sleep",
        brand_voice="warm, consultative, sleep expert",
        product_api_base=NKL_SHOPIFY_MCP_URL,
        offers_api_base="",
        store_api_base="",
        vtiger_base=_env("NKL_VTIGER_BASE"),
        vtiger_token=_env("NKL_VTIGER_TOKEN"),
        has_pre_order=False,
        has_offers=False,
        has_store_locator=True,
        has_order_tracking=False,
        intent_categories=NKL_INTENT_CATEGORIES,
    )


@lru_cache(maxsize=1)
def _registry() -> dict[str, ClientConfig]:
    return {
        "kisna": _kisna_config(),
        "nkl": _nkl_config(),
    }


def get_client_config(client_id: str) -> ClientConfig:
    """
    Return configuration for a client_id slug (case-insensitive).

    Args:
        client_id: Client slug such as "kisna" or "nkl".

    Returns:
        ClientConfig for the requested client.

    Raises:
        ValueError: If client_id does not match any registered client.
    """
    normalized = client_id.strip().lower()
    configs = _registry()
    if normalized in configs:
        return configs[normalized]
    valid_ids = list(configs.keys())
    raise ValueError(
        f"Unknown client_id: {client_id!r}. Valid ids: {valid_ids}"
    )


def refresh_client_registry() -> None:
    """Clear cached configs (e.g. after env changes in tests)."""
    _registry.cache_clear()
