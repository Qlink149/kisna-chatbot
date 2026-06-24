# KB grounding via prompt injection (KISNA_KNOWLEDGE_BASE).
# Switch to Chroma kb_search() when KB exceeds ~12k tokens.

import re

from kisna_chatbot.ai import run_general_agent
from kisna_chatbot.constants import KIA_HANDOFF_MESSAGE
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.format_chathistory import format_recent_history_str
from kisna_chatbot.utils.logger_config import logger

_HANDOFF_MESSAGE = KIA_HANDOFF_MESSAGE
_GENERIC_ERROR = (
    "Sorry, I couldn't process your question right now. Please try again in a moment."
)

_CATALOG_FOLLOWUP_RE = re.compile(
    r"\b("
    r"price|cost|kitna|rate|sasta|mehnga|cheap|expensive|cheapest|cheaper|better|compare|"
    r"difference|best|worst|affordable|"
    r"this|that one|yeh|woh|third|first|second"
    r")\b",
    re.I,
)

# FIX 6: Only reroute when query explicitly references a shown product.
# Without this, generic questions like "price of gold?" would get rerouted
# to product search whenever stale search history exists.
_PRODUCT_REFERENCE_RE = re.compile(
    r"\b(this|that|it\b|ye|yeh|woh|iska|iski|uska|the\s+one|which|"
    r"above|shown|earlier|last\s+one|pehle\s+wala)\b",
    re.I,
)


class GeneralAgent(Processor):
    """Handles brand questions, design advice, and policy/FAQ queries for Kisna."""

    def should_run(self, data: dict) -> bool:
        return "bot_response" not in data

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        user_profile = data["user_profile"]
        client_id = data.get("client_id", "kisna")
        username = user_profile.get("username") or user_profile.get(
            "whatsapp_username", "Customer"
        )

        if not self.should_run(data):
            logger.info(
                "Skipping processor",
                extra={
                    "processor": self.__class__.__name__,
                    "phone_number": phone_number,
                },
            )
            return data

        try:
            if "text" not in data.get("messages", {}):
                return data

            user_query = data["messages"]["text"]["body"]
            last_viewed = user_profile.get("last_viewed_product")
            last_search = user_profile.get("last_search_products") or []

            if (last_viewed or last_search) and _CATALOG_FOLLOWUP_RE.search(
                user_query or ""
            ):
                from kisna_chatbot.processors.classifier import _is_competitor_comparison
                # FIX 6: only reroute when the query explicitly refers to a specific
                # shown product (demonstrative pronoun). Generic questions like
                # "what is the price of gold?" should stay in GeneralAgent / KB.
                if _PRODUCT_REFERENCE_RE.search(user_query or ""):
                    if not _is_competitor_comparison(user_query):
                        logger.info(
                            "GeneralAgent rerouting catalog follow-up to product search",
                            extra={"phone_number": phone_number, "query": user_query},
                        )
                        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                        data["classified_category"] = "product_info"
                        return data

            chat_history_str = format_recent_history_str(user_profile, 8)

            result = await run_general_agent(
                phone_number=phone_number,
                client_id=client_id,
                username=username,
                user_query=user_query,
                chat_history_str=chat_history_str,
            )

            logger.info(
                "GeneralAgent completed",
                extra={
                    "phone_number": phone_number,
                    "provider": result.provider.value,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "fallback_used": getattr(result, "fallback_used", False),
                },
            )

            if result.live_agent_requested:
                text = result.message_text or _HANDOFF_MESSAGE
                data["bot_response"] = [{"type": "text", "text": text}]
            elif result.message_text:
                data["bot_response"] = [
                    {"type": "text", "text": result.message_text}
                ]
            else:
                data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]

            user_profile["service_selected"] = ""
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in GeneralAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
