from enum import Enum


class ServiceList(Enum):
    """Enum class for service list options."""

    GENERAL = "general"
    PRODUCT_SEARCH = "product_search"
    OFFERS = "offers"
    PRE_ORDER = "pre_order"
    ORDER_TRACKING = "order_tracking"
    RETURNS_REFUND = "returns_refund"
    COMPLAINT = "complaint"
    PRODUCT_CHECKOUT = "product_checkout"
    AD_FLOW = "ad_flow"
