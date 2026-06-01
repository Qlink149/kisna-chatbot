from pydantic import BaseModel, Field


class ClientConfig(BaseModel):
    """Per-client settings for the multi-brand WhatsApp chatbot."""

    client_id: str = Field(
        ...,
        description=(
            "Stable slug used in webhooks and routing (e.g. kisna, nkl). "
            "Passed to get_client_config() and pipeline selection."
        ),
    )
    brand_name: str = Field(
        ...,
        description=(
            "Display name shown in prompts, menus, and user-facing copy. "
            "Used by general and product agents when referring to the brand."
        ),
    )
    brand_voice: str = Field(
        ...,
        description=(
            "Tone descriptor injected into agent system prompts "
            "(e.g. warm, consultative, sleep expert)."
        ),
    )
    product_api_base: str = Field(
        ...,
        description=(
            "Base URL for the product catalog API. "
            "Product search and checkout processors call endpoints under this URL."
        ),
    )
    offers_api_base: str = Field(
        ...,
        description=(
            "Base URL for offers and promotions API. "
            "Used when has_offers is True to fetch active deals."
        ),
    )
    store_api_base: str = Field(
        ...,
        description=(
            "Base URL for store locator API. "
            "Used when has_store_locator is True for pincode and showroom lookup."
        ),
    )
    vtiger_base: str = Field(
        ...,
        description=(
            "VTiger CRM webhook base URL. "
            "Damage complaints, store visits, and lead flows post cases here."
        ),
    )
    vtiger_token: str = Field(
        ...,
        description=(
            "Authentication token for VTiger API requests. "
            "Loaded from environment; never hardcode in source."
        ),
    )
    has_pre_order: bool = Field(
        default=True,
        description=(
            "Whether pre-order flows are enabled for this client. "
            "When False, pre_order intent is not routed."
        ),
    )
    has_offers: bool = Field(
        default=True,
        description=(
            "Whether offers and promotions flows are enabled. "
            "When False, offers intent and offers_api_base are unused."
        ),
    )
    has_store_locator: bool = Field(
        default=True,
        description=(
            "Whether store locator and visit booking flows are enabled. "
            "When False, store_locator intent maps to general or menu fallback."
        ),
    )
    has_order_tracking: bool = Field(
        default=True,
        description=(
            "Whether order tracking flows are enabled. "
            "When False, order_tracking intent is not offered."
        ),
    )
    intent_categories: list[str] = Field(
        ...,
        description=(
            "Intent labels used by the classifier and service routing. "
            "Must align with classifier prompt categories for this client."
        ),
    )
