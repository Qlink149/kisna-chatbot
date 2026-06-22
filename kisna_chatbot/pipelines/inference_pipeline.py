from kisna_chatbot.pipelines.pipeline import Pipeline
from kisna_chatbot.processors.ad_flow_agent import AdFlowAgent
from kisna_chatbot.processors.classifier import Classifier
from kisna_chatbot.processors.complaint_agent import ComplaintAgent
from kisna_chatbot.processors.general_agent import GeneralAgent
from kisna_chatbot.processors.offers_agent import OffersAgent
from kisna_chatbot.processors.order_tracking_agent import OrderTrackingAgent
from kisna_chatbot.processors.pre_order_agent import PreOrderAgent
from kisna_chatbot.processors.product_checkout_agent import ProductCheckoutAgent
from kisna_chatbot.processors.product_details_agent import ProductDetailsAgent
from kisna_chatbot.processors.product_search_agent_v3 import ProductSearchAgentV3
from kisna_chatbot.processors.returns_refund_agent import ReturnsRefundAgent
from kisna_chatbot.processors.service_list import ServiceList
from kisna_chatbot.processors.user_registration import UserRegistration


class InitialPipeline(Pipeline):
    """Pipeline for user registration, intent classification, and main menu."""

    def __init__(self) -> None:
        processors = [UserRegistration(), Classifier(), ServiceList()]
        super().__init__(processors)


class GeneralPipeline(Pipeline):
    """Pipeline for general FAQ and conversational queries."""

    def __init__(self) -> None:
        processors = [GeneralAgent()]
        super().__init__(processors)


class ProductSearchPipeline(Pipeline):
    """Pipeline for product search and product detail views."""

    def __init__(self) -> None:
        processors = [ProductSearchAgentV3(), ProductDetailsAgent()]
        super().__init__(processors)


class OffersPipeline(Pipeline):
    """Pipeline for active offers and promotions."""

    def __init__(self) -> None:
        processors = [OffersAgent(), ProductSearchAgentV3()]
        super().__init__(processors)


class PreOrderPipeline(Pipeline):
    """Pipeline for pre-order and variant selection flows."""

    def __init__(self) -> None:
        processors = [ProductSearchAgentV3(), PreOrderAgent()]
        super().__init__(processors)


class ReturnsRefundPipeline(Pipeline):
    """Pipeline for return and refund requests — registers complaints."""

    def __init__(self) -> None:
        processors = [ReturnsRefundAgent()]
        super().__init__(processors)


class OrderTrackingPipeline(Pipeline):
    """Pipeline for order status and tracking links."""

    def __init__(self) -> None:
        processors = [OrderTrackingAgent()]
        super().__init__(processors)


class ComplaintPipeline(Pipeline):
    """Pipeline for customer complaints."""

    def __init__(self) -> None:
        processors = [ComplaintAgent()]
        super().__init__(processors)


class ProductCheckoutPipeline(Pipeline):
    """Pipeline for variant selection and cart checkout."""

    def __init__(self) -> None:
        processors = [ProductCheckoutAgent()]
        super().__init__(processors)


class AdFlowPipeline(Pipeline):
    """Pipeline for store locator and visit flows."""

    def __init__(self) -> None:
        processors = [AdFlowAgent()]
        super().__init__(processors)
