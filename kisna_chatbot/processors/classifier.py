import json
import re
import time
from zoneinfo import ZoneInfo

from kisna_chatbot.ai import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.models.service_list import ServiceList
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.ad_flow_agent import _PINCODE_ONLY_RE
from kisna_chatbot.processors.entity_extractor import extract_entities
from kisna_chatbot.processors.service_list import (
    build_complaint_flow_bot_response,
    build_greeting_welcome_bot_responses,
    build_main_menu_bot_response,
    is_new_session,
    is_menu_request,
    is_pure_greeting,
)
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)

india_tz = ZoneInfo("Asia/Kolkata")

CONTEXT = kisna_classifier

_REROUTE_RE = re.compile(
    r"\b("
    r"menu|back|cancel|hi|hello|namaste|"
    r"view\s+offers|show\s+offers|any\s+offers|koi\s+offer|offers?\s*\?|"
    r"find\s+(a\s+)?store|store\s+locator|nearest\s+store|showroom|"
    r"track\s+(my\s+)?order|order\s+status|where\s+is\s+my\s+order|"
    r"complaint|file\s+complaint|"
    r"return\s+policy|refund\s+policy|"
    r"talk\s+to\s+(a\s+)?human|connect\s+me"
    r")\b",
    re.I,
)

_OFFERS_INTENT_RE = re.compile(
    r"\b("
    r"offers?|promo(?:tion)?s?|discounts?|deals?|sale|"
    r"koi\s+offer|offer\s+hai|making\s+charge\s+off"
    r")\b",
    re.I,
)

_ORDER_TRACKING_RE = re.compile(
    r"\b(track\s+(my\s+)?order|order\s+status|where\s+is\s+my\s+order|"
    r"delivery\s+status|shipment\s+status)\b",
    re.I,
)

_PRICE_PRODUCT_INFO_RE = re.compile(
    r"\b("
    r"price|cost|kitna|rate|mrp|how\s+much|"
    r"available|in\s+stock|stock"
    r")\b|"
    r"(isme|is\s+me|iska|is\s+ka)\s+(kitna|price|cost)",
    re.I,
)

_CATALOG_SEARCH_RE = re.compile(
    r"\b(ring|rings|necklace|earring|earrings|pendant|bracelet|bangle|"
    r"chain|mangalsutra|nose\s+pin|anklet|jewel|jewellery|jewelry|"
    r"gold|diamond|silver|platinum|under|below|budget)\b",
    re.I,
)

def _looks_like_product_search_query(text: str) -> bool:
    """True when free text looks like a catalog search, not a menu tap."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _CATALOG_SEARCH_RE.search(normalized):
        return True
    entities = extract_entities(normalized)
    return bool(
        entities.get("category")
        or entities.get("material_type")
        or entities.get("title")
        or entities.get("min_price")
        or entities.get("max_price")
    )


def _parse_classifier_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _programmatic_intent_override(user_query: str, user_profile: dict) -> str | None:
    """Route factual commerce queries without LLM when patterns are clear."""
    normalized = (user_query or "").strip()
    if not normalized:
        return None

    if _ORDER_TRACKING_RE.search(normalized):
        return "order_tracking"

    if _OFFERS_INTENT_RE.search(normalized) and not _CATALOG_SEARCH_RE.search(
        normalized
    ):
        return "offers"

    if _looks_like_store_query(normalized):
        return "store_info"

    last_viewed = user_profile.get("last_viewed_product")
    if last_viewed and _PRICE_PRODUCT_INFO_RE.search(normalized):
        return "product_info"

    if _PRICE_PRODUCT_INFO_RE.search(normalized) and _CATALOG_SEARCH_RE.search(
        normalized
    ):
        return "product_search"

    if _looks_like_product_search_query(normalized):
        return "product_search"

    return None


def _apply_intent_routing(data: dict, intent: str, user_profile: dict) -> bool:
    """Set service_selected from intent; return True if bot_response was set."""
    phone_number = data["phone_number"]
    chat_history = user_profile.get("chat_history", [])

    if intent == "greeting":
        user_profile["service_selected"] = ""
        data["classified_category"] = "greeting"
        data["bot_response"] = build_greeting_welcome_bot_responses(
            phone_number=phone_number,
            chat_history=chat_history,
        )
        return True

    if intent == "menu_help":
        data["bot_response"] = [build_main_menu_bot_response()]
        return True

    if intent == "complaint":
        user_profile["service_selected"] = ServiceList.COMPLAINT.value
        data["bot_response"] = [build_complaint_flow_bot_response()]
        return True

    service = _CATEGORY_TO_SERVICE.get(intent)
    if service:
        user_profile["service_selected"] = service.value
        return False

    logger.warning(
        "Unknown classifier intent",
        extra={"intent": intent, "phone_number": phone_number},
    )
    data["bot_response"] = [build_main_menu_bot_response()]
    return True


def _looks_like_store_query(text: str) -> bool:
    """True when message is a pincode-only or city-shaped store lookup."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _PINCODE_ONLY_RE.match(normalized):
        return True
    entities = extract_entities(normalized)
    return bool(entities.get("pincode") or entities.get("city"))


_CATEGORY_TO_SERVICE = {
    "general": ServiceList.GENERAL,
    "greeting": ServiceList.GENERAL,
    "product_search": ServiceList.PRODUCT_SEARCH,
    "product_info": ServiceList.PRODUCT_SEARCH,
    "offers": ServiceList.OFFERS,
    "pre_order": ServiceList.PRE_ORDER,
    "order_tracking": ServiceList.ORDER_TRACKING,
    "returns_refund": ServiceList.RETURNS_REFUND,
    "complaint": ServiceList.COMPLAINT,
    "store_info": ServiceList.AD_FLOW,
}


class Classifier(Processor):
    """Classifies a query based on user intent."""

    def should_run(self, data: dict) -> bool:
        """Determine whether the processor should run based on the input data."""
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        if "text" not in messages:
            return True

        user_profile = data.get("user_profile", {})
        user_query = messages["text"].get("body", "") or ""

        if _REROUTE_RE.search(user_query):
            return True

        if user_profile.get("awaiting_store_pincode"):
            return False

        service = user_profile.get("service_selected")
        if service == ServiceList.AD_FLOW.value and _looks_like_store_query(user_query):
            return False

        if service == ServiceList.ORDER_TRACKING.value:
            return _looks_like_product_search_query(user_query)

        if service == ServiceList.OFFERS.value:
            return _looks_like_product_search_query(user_query)

        if service == ServiceList.PRODUCT_SEARCH.value:
            last_viewed = user_profile.get("last_viewed_product")
            if last_viewed and _PRICE_PRODUCT_INFO_RE.search(user_query):
                return False
            if _OFFERS_INTENT_RE.search(user_query) and not _CATALOG_SEARCH_RE.search(
                user_query
            ):
                return True
            if _ORDER_TRACKING_RE.search(user_query):
                return True
            if _looks_like_store_query(user_query):
                return True

        if service != ServiceList.PRODUCT_SEARCH.value:
            return True

        chat_history = user_profile.get("chat_history", [])
        if not chat_history:
            return True

        return False

    async def process(self, data: dict) -> dict:
        """Process the input data and return the processed data."""
        phone_number = data["phone_number"]
        user_profile = data["user_profile"]
        client_id = data.get("client_id", "kisna")

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
            if "text" in data["messages"]:
                user_query = data["messages"]["text"]["body"]

                if user_query.strip().lower() == "stop":
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": "You've been successfully unsubscribed.",
                        }
                    ]
                    return data

                if user_query.lower() == "hi from ads":
                    user_profile["service_selected"] = ServiceList.AD_FLOW.value
                    return data

                chat_history = data["user_profile"].get("chat_history", [])
                if is_pure_greeting(user_query) and is_new_session(chat_history):
                    user_profile["service_selected"] = ""
                    data["classified_category"] = "greeting"
                    data["bot_response"] = build_greeting_welcome_bot_responses(
                        phone_number=phone_number,
                        chat_history=chat_history,
                    )
                    logger.info(
                        "Greeting on new session — welcome and main menu",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if is_menu_request(user_query):
                    data["classified_category"] = "menu_help"
                    data["bot_response"] = [build_main_menu_bot_response()]
                    logger.info(
                        "Menu request shortcut — sending main menu",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if user_profile.get("awaiting_store_pincode") or _looks_like_store_query(
                    user_query
                ):
                    if user_query.strip().lower() not in ("cancel", "back"):
                        user_profile["service_selected"] = ServiceList.AD_FLOW.value
                        data["classified_category"] = "store_info"
                        logger.info(
                            "Store lookup shortcut — routing to ad_flow",
                            extra={"phone_number": phone_number},
                        )
                        return data

                override_intent = _programmatic_intent_override(
                    user_query,
                    user_profile,
                )
                if override_intent:
                    data["classified_category"] = override_intent
                    logger.info(
                        "Programmatic classifier override",
                        extra={
                            "phone_number": phone_number,
                            "intent": override_intent,
                        },
                    )
                    if _apply_intent_routing(data, override_intent, user_profile):
                        return data
                    return data

                logger.info(
                    "Request received to classify query",
                    extra={"phone_number": phone_number, "query": user_query},
                )

                recent_chats = chat_history[-8:]

                chat_history_str = ""
                for chat in recent_chats:
                    role = chat.get("role", "")
                    content = chat.get("content", "")
                    chat_history_str += f"{role.capitalize()}: {content}\n"

                classifier_response = await complete_chat(
                    agent=AgentName.CLASSIFIER,
                    agent_display_name="Classifier Agent",
                    instruction=CONTEXT,
                    messages=[
                        {
                            "role": "system",
                            "content": f"Chat history: {chat_history_str}",
                        },
                        {
                            "role": "user",
                            "content": f"User Query: {user_query}",
                        },
                    ],
                    phone_number=phone_number,
                    client_id=client_id,
                )

                logger.info(
                    "Classifier agent response",
                    extra={
                        "response": classifier_response,
                        "phone_number": phone_number,
                    },
                )

                parsed = _parse_classifier_json(classifier_response)
                intent = (
                    parsed.get("intent") or parsed.get("category", "menu_help")
                ).strip().lower()
                data["classified_category"] = intent

                logger.info(
                    "Classifier intent",
                    extra={
                        "intent": intent,
                        "confidence": parsed.get("confidence"),
                        "phone_number": phone_number,
                    },
                )

                if intent == "greeting":
                    user_profile["service_selected"] = ""
                    data["classified_category"] = "greeting"
                    data["bot_response"] = build_greeting_welcome_bot_responses(
                        phone_number=phone_number,
                        chat_history=chat_history,
                    )
                    logger.info(
                        "Classifier greeting intent — welcome and main menu",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if intent in ("product_info", "product_search") and (
                    _PRICE_PRODUCT_INFO_RE.search(user_query)
                    or user_profile.get("last_viewed_product")
                ):
                    if user_profile.get("last_viewed_product") and (
                        intent == "product_info"
                        or _PRICE_PRODUCT_INFO_RE.search(user_query)
                    ):
                        intent = "product_info"
                        data["classified_category"] = intent

                if intent == "human_handoff":
                    user_profile["live_agent_requested_at"] = int(time.time())
                    user_profile["live_agent_required"] = True
                    for admin in ADMINS:
                        send_customer_support_template(
                            phone_number=admin,
                            customer_name=user_profile.get("username", "Customer"),
                            customer_phone=phone_number,
                        )
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": (
                                "Sure! I'm connecting you to a live designer right now. "
                                "Someone from our team will be with you shortly."
                            ),
                        }
                    ]
                    logger.info(
                        "Human handoff triggered",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if intent == "complaint":
                    user_profile["service_selected"] = ServiceList.COMPLAINT.value
                    data["bot_response"] = [build_complaint_flow_bot_response()]
                    logger.info(
                        "Complaint intent — launching complaint flow",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if _apply_intent_routing(data, intent, user_profile):
                    return data

            return data
        except json.JSONDecodeError as e:
            logger.exception(
                "Classifier returned invalid JSON",
                extra={"exception": e, "phone_number": phone_number},
            )
            user_profile["service_selected"] = ""
            data["bot_response"] = [build_main_menu_bot_response()]
            return data
        except Exception as e:
            logger.exception(
                "Exception occured while running classifier.",
                extra={"exception": e, "phone_number": phone_number},
            )
            user_profile["service_selected"] = ""
            data["bot_response"] = [build_main_menu_bot_response()]
            return data
