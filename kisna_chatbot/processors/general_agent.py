# KB grounding via prompt injection (KISNA_KNOWLEDGE_BASE).

import re

from kisna_chatbot.ai import run_general_agent
from kisna_chatbot.constants import KIA_HANDOFF_MESSAGE
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.shopping_wizard import DIGITAL_GOLD_URL
from kisna_chatbot.utils.format_chathistory import format_recent_history_str
from kisna_chatbot.utils.logger_config import logger

_HANDOFF_MESSAGE = KIA_HANDOFF_MESSAGE
_GENERIC_ERROR = (
    "Sorry, I couldn't process your question right now. Please try again in a moment."
)

_DIGITAL_GOLD_RE = re.compile(
    r"\b("
    r"digital\s+gold|safegold|safe\s+gold|buy\s+gold\s+online|"
    r"gold\s+sip|digital\s+sona"
    r")\b",
    re.I,
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

_VARIANT_OR_BUDGET_RE = re.compile(
    r"("
    r"\d+\s*k|\d+\s*lakh|budget|under|above|gms?|gram|carat|\bct\b|"
    r"हज़ार|हजार|लाख|હજાર"
    r")",
    re.I,
)


def _match_shown_title(query: str, shown: list) -> bool:
    needle = (query or "").strip().strip("*").strip().casefold()
    if len(needle) < 4:
        return False
    for product in shown:
        title = (product.get("title") or product.get("name") or "").casefold()
        if title and (needle == title or needle in title or title in needle):
            return True
    return False


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

            async def _handoff_to_product_search(
                *, category: str = "product_search"
            ) -> dict:
                from kisna_chatbot.processors.product_search_agent_v3 import (
                    ProductSearchAgentV3,
                )

                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                data["classified_category"] = category
                return await ProductSearchAgentV3().process(data)

            # Never invent catalog while shopping — hand back to product search.
            if user_profile.get("shopping_wizard_active"):
                logger.info(
                    "GeneralAgent deferring to product search (wizard active)",
                    extra={"phone_number": phone_number, "query": user_query},
                )
                return await _handoff_to_product_search(category="product_search")

            if last_search and _match_shown_title(user_query, last_search):
                logger.info(
                    "GeneralAgent deferring typed product title to product search",
                    extra={"phone_number": phone_number, "query": user_query},
                )
                return await _handoff_to_product_search(category="product_info")

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
                        return await _handoff_to_product_search(category="product_info")

            # Budget / variant-sounding asks while results are on screen → product path.
            # A policy question that merely contains a number or "per gram"
            # ("making charges kitna per gram?", "EMI 10k per month?") belongs to
            # the knowledge base, not a fresh catalog search.
            from kisna_chatbot.processors.classifier import _POLICY_TOPIC_RE

            if (
                last_search
                and _VARIANT_OR_BUDGET_RE.search(user_query or "")
                and not _POLICY_TOPIC_RE.search(user_query or "")
            ):
                logger.info(
                    "GeneralAgent deferring budget/variant follow-up to product search",
                    extra={"phone_number": phone_number, "query": user_query},
                )
                return await _handoff_to_product_search(category="product_search")

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
                # Route through the shared support handler: it flags the profile,
                # pages the admins, and — outside support hours — offers a
                # callback slot instead. Sending the bare line here told the user
                # "I'll connect you" while notifying nobody.
                from kisna_chatbot.processors.support_handler import (
                    build_expert_support_bot_response,
                )

                logger.info(
                    "GeneralAgent live-agent handoff",
                    extra={"phone_number": phone_number},
                )
                data["_trace_outcome"] = "handoff"
                responses = build_expert_support_bot_response(
                    phone_number, user_profile
                )
                # Offline hours leave the callback flow selected; otherwise drop
                # back to no service, as every other GeneralAgent reply does.
                if user_profile.get("service_selected") != SL.CALLBACK.value:
                    user_profile["service_selected"] = ""
                data["bot_response"] = responses
                return data
            elif result.message_text:
                responses: list[dict] = [
                    {"type": "text", "text": result.message_text}
                ]
                if data.get("_digital_gold_cta") or _DIGITAL_GOLD_RE.search(
                    user_query or ""
                ):
                    responses.append(
                        {
                            "type": "cta_url",
                            "body": (
                                "Buy 24K Digital Gold securely on Kisna — "
                                "powered by SafeGold."
                            ),
                            "display_text": "Buy Digital Gold",
                            "url": DIGITAL_GOLD_URL,
                            "footer": "KISNA Diamond & Gold",
                        }
                    )
                data["bot_response"] = responses
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
