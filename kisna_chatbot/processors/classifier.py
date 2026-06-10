import json
import re
import time
from typing import Any
from zoneinfo import ZoneInfo

from kisna_chatbot.ai import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.models.service_list import ServiceList
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.ad_flow_agent import _PINCODE_ONLY_RE
from kisna_chatbot.processors.entity_extractor import (
    extract_entities,
    is_unrecognizable_input,
)
from kisna_chatbot.processors.service_list import (
    build_clarification_bot_response,
    build_complaint_flow_bot_response,
    build_flow_switch_bot_response,
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

CLARIFICATION_CONFIDENCE_THRESHOLD = 0.45
COMPLETELY_UNCLEAR_THRESHOLD = 0.3
PRODUCT_SEARCH_SESSION_EXPIRY_SECONDS = 2 * 60 * 60

_GREETING_RE = re.compile(
    r"^\s*("
    r"hi+|hey+|hello+|helo+|hii+|hiii+|heya|"
    r"yo+|sup|what'?s\s*up|wassup|howdy|"
    r"good\s*(morning|evening|afternoon|night|day)|"
    r"gm|gn|"
    r"namaste+|namaskar|pranam|"
    r"ram\s*ram|jai\s*(shree\s*)?krishna|jai\s*jinendra|"
    r"salam+|assalam|aadab|"
    r"kya\s*haal|kaise\s*(ho|hain)|kaisa\s*hai|"
    r"bhai+|yaar|dude"
    r")\s*[!?.]*\s*$",
    re.I,
)


def is_greeting_message(text: str) -> bool:
    """True for short standalone greetings (English, Hindi, Hinglish)."""
    return bool(_GREETING_RE.match((text or "").strip()))


_REROUTE_RE = re.compile(
    r"\b("
    r"menu|back|cancel|hi|hello|namaste|"
    r"view\s+offers|show\s+offers|any\s+offers|koi\s+offer|offers?\s*\?|"
    r"find\s+(a\s+)?store|store\s+locator|nearest\s+store|showroom|"
    r"track\s+(my\s+)?order|order\s+status|where\s+is\s+my\s+order|"
    r"complaint|file\s+complaint|"
    r"return\s+policy|refund\s+policy|"
    r"talk\s+to\s+(a\s+)?human|connect\s+me|"
    r"wapas|wapas\s+karna|refund\s+chahiye|"
    r"galat\s+item|kharab\s+nikla|kharab\s+product|"
    r"kisi\s+se\s+baat|agent\s+chahiye|support\s+chahiye|"
    r"agent\s+se\s+baat|human\s+chahiye"
    r")\b",
    re.I,
)

_OFFERS_INTENT_RE = re.compile(
    r"\b("
    r"offers?|promo(?:tion)?s?|discounts?|deals?|sale|cashback|"
    r"koi\s+offer|offer\s+hai|making\s+charge\s+off"
    r")\b",
    re.I,
)

_ORDER_TRACKING_RE = re.compile(
    r"\b(track\s+(my\s+)?order|order\s+status|where\s+is\s+my\s+order|"
    r"delivery\s+status|shipment\s+status|mera\s+order|order\s+track)\b",
    re.I,
)

_ORDER_DELIVERY_RE = re.compile(
    r"\b(mera\s+order|order.*delivery|delivery\s+kab|dispatch|shipment)\b",
    re.I,
)

_EXCHANGE_RE = re.compile(r"\b(exchange|badal|swap)\b", re.I)

_RETURNS_RE = re.compile(r"\b(return|refund|wapas)\b", re.I)

_POLICY_FAQ_RE = re.compile(
    r"\b(policy|hallmark|bis|certificate|guarantee|emi|installment|loan)\b",
    re.I,
)

_HUMAN_HANDOFF_RE = re.compile(
    r"\b(human|agent\s+se|customer\s+care|live\s+agent|support\s+chahiye|"
    r"baat\s+karni\s+hai|kisi\s+se\s+baat)\b",
    re.I,
)

_PRODUCT_REFERENCE_RE = re.compile(
    r"\b(this|that|yeh|woh|isme|is\s+me|iska|is\s+ka)\b",
    re.I,
)

_GIFT_BROWSE_RE = re.compile(
    r"\b(for my|for\s+a|gift|anniversary|wife|husband|fiancee|something for)\b",
    re.I,
)

_PRODUCT_EDD_RE = re.compile(
    r"\b(how many days|kitne din).*\bdelivery\b|\bdelivery.*\b(how many|kitne)\b",
    re.I,
)

_COMPLAINT_RE = re.compile(
    r"\b(complaint|damage|kharab|galat\s+item|wrong\s+item|defective)\b",
    re.I,
)

_STORE_LOOKUP_RE = re.compile(
    r"\b(nearest\s+store|showroom|store\s+near|kisna\s+showroom|outlet|"
    r"store\s+locator|find\s+store)\b",
    re.I,
)

_PRICE_PRODUCT_INFO_RE = re.compile(
    r"\b("
    r"price|cost|kitna|rate|mrp|how\s+much|weight|"
    r"available|in\s+stock|stock|delivery\s+days|edd|chain"
    r")\b|"
    r"(isme|is\s+me|iska|is\s+ka)\s+(kitna|price|cost)",
    re.I,
)

_PRODUCT_NAME_RE = re.compile(
    r"\b(elysia|maggio|rivaah|aadya|tanishta|evil\s+eye)\b",
    re.I,
)

_BROWSE_ACTION_RE = re.compile(
    r"\b(dikhao|dikha|chahiye|show|find|browse|search|dekh|looking\s+for)\b",
    re.I,
)

_CATEGORY_WORD_RE = re.compile(
    r"\b(ring|rings|necklace|earring|earrings|pendant|bracelet|bangle|"
    r"chain|mangalsutra|nose\s+pin|anklet|jewel|jewellery|jewelry|anguthi|bali|"
    r"jhumka|haar|mala|kada|kangan)\b",
    re.I,
)

_MATERIAL_WORD_RE = re.compile(
    r"\b(gold|diamond|silver|platinum|sona|heera)\b",
    re.I,
)

_BUDGET_BROWSE_RE = re.compile(
    r"\b(under|below|upto|up to|budget|within|tak|kam|k\b|lakh|lac)\b",
    re.I,
)

_COMPARATIVE_RE = re.compile(
    r"\b(cheapest|cheaper|better|best|worst|compare|comparison|sabse\s+sasta|"
    r"affordable|sasta|mehnga|expensive)\b",
    re.I,
)

_SIZE_QUERY_RE = re.compile(
    r"\b(size|sizes|variant|variants|karat|kt\b|18kt|14kt|22kt|chain)\b",
    re.I,
)


def _looks_like_product_search_query(text: str) -> bool:
    """True when free text looks like a catalog search, not a menu tap."""
    normalized = (text or "").strip()
    if not normalized:
        return False

    entities = extract_entities(normalized)

    if entities.get("category") or entities.get("title"):
        return True

    if entities.get("min_price") is not None or entities.get("max_price") is not None:
        return True

    if _CATEGORY_WORD_RE.search(normalized):
        return True

    if _BROWSE_ACTION_RE.search(normalized):
        if _MATERIAL_WORD_RE.search(normalized) or entities.get("material_type"):
            return True
        if _CATEGORY_WORD_RE.search(normalized) or entities.get("title"):
            return True
        if _BUDGET_BROWSE_RE.search(normalized):
            return True
        if re.search(r"\bkuch\b", normalized, re.I):
            return True

    if _GIFT_BROWSE_RE.search(normalized) and re.search(
        r"\b(something|gift|jewel|ring|present)\b", normalized, re.I
    ):
        return True

    if _BUDGET_BROWSE_RE.search(normalized) and (
        _MATERIAL_WORD_RE.search(normalized) or _CATEGORY_WORD_RE.search(normalized)
    ):
        return True

    return False


def _looks_like_product_info_query(text: str, user_profile: dict) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False

    if not _PRICE_PRODUCT_INFO_RE.search(normalized) and not _COMPARATIVE_RE.search(
        normalized
    ):
        return False

    entities = extract_entities(normalized)
    last_viewed = user_profile.get("last_viewed_product")

    if last_viewed:
        return True

    if _PRODUCT_REFERENCE_RE.search(normalized) and (
        _PRICE_PRODUCT_INFO_RE.search(normalized) or _SIZE_QUERY_RE.search(normalized)
    ):
        return True

    if _PRODUCT_NAME_RE.search(normalized) or entities.get("title"):
        return True

    if _CATEGORY_WORD_RE.search(normalized) and not _BUDGET_BROWSE_RE.search(
        normalized
    ):
        return True

    if _COMPARATIVE_RE.search(normalized) and user_profile.get("last_search_products"):
        return True

    return False


_LLM_ENTITY_CATEGORIES = frozenset(
    {
        "ring",
        "earring",
        "necklace",
        "pendant",
        "bracelet",
        "bangle",
        "mangalsutra",
        "anklet",
        "nose_ring",
        "nosewear",
        "maang_tikka",
        "chain",
    }
)
_LLM_ENTITY_MATERIALS = frozenset(
    {
        "gold",
        "diamond",
        "silver",
        "platinum",
        "white_gold",
        "rose_gold",
        "gemstone",
    }
)
_LLM_ENTITY_OCCASIONS = frozenset(
    {
        "wedding",
        "engagement",
        "anniversary",
        "birthday",
        "daily_wear",
        "gift",
    }
)
_LLM_ENTITY_STYLES = frozenset(
    {
        "traditional",
        "modern",
        "minimal",
        "heavy",
        "fashion",
        "cocktail",
        "couple_bands",
        "infinity",
        "hearts",
        "floral",
        "adjustable",
    }
)
_LLM_ENTITY_KARATS = frozenset({"9KT", "14KT", "18KT", "22KT", "24KT"})
_LLM_ENTITY_COLOURS = frozenset({"yellow", "white", "rose"})
_LLM_ENTITY_GENDERS = frozenset({"women", "men", "kids"})
_LLM_CATEGORY_ALIASES = {"nose_ring": "nosewear"}


def _coerce_null(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, str) and val.strip().lower() in ("", "null", "none"):
        return None
    return val


def _sanitize_llm_entities(entities: dict) -> dict:
    """Normalize LLM entity output to internal schema."""
    raw = entities or {}
    out: dict[str, Any] = {}

    category = _coerce_null(raw.get("category"))
    if isinstance(category, str):
        category = category.strip().lower()
        category = _LLM_CATEGORY_ALIASES.get(category, category)
        category = category if category in _LLM_ENTITY_CATEGORIES else None
    else:
        category = None
    out["category"] = category

    material = _coerce_null(raw.get("material_type"))
    metal_colour = _coerce_null(raw.get("metal_colour"))
    if isinstance(material, str):
        material = material.strip().lower()
        if material == "rose_gold":
            material = "gold"
            metal_colour = metal_colour or "rose"
        elif material == "white_gold":
            material = "gold"
            metal_colour = metal_colour or "white"
        material = material if material in _LLM_ENTITY_MATERIALS else None
    else:
        material = None
    out["material_type"] = material

    if isinstance(metal_colour, str):
        metal_colour = metal_colour.strip().lower()
        metal_colour = metal_colour if metal_colour in _LLM_ENTITY_COLOURS else None
    else:
        metal_colour = None
    out["metal_colour"] = metal_colour

    karat = _coerce_null(raw.get("karat"))
    if isinstance(karat, str):
        karat_norm = karat.strip().upper().replace(" ", "")
        if not karat_norm.endswith("KT"):
            karat_norm = f"{karat_norm}KT" if karat_norm.isdigit() else karat_norm
        karat = karat_norm if karat_norm in _LLM_ENTITY_KARATS else None
    else:
        karat = None
    out["karat"] = karat

    size_val = _coerce_null(raw.get("size"))
    if size_val is not None:
        try:
            size_int = int(float(size_val))
            size_val = size_int if 7 <= size_int <= 22 else None
        except (TypeError, ValueError):
            size_val = None
    else:
        size_val = None
    out["size"] = size_val

    collection = _coerce_null(raw.get("collection"))
    out["collection"] = (
        collection.strip() if isinstance(collection, str) and collection.strip() else None
    )

    gender = _coerce_null(raw.get("gender"))
    if isinstance(gender, str):
        gender = gender.strip().lower()
        gender = gender if gender in _LLM_ENTITY_GENDERS else None
    else:
        gender = None
    out["gender"] = gender

    for price_key in ("min_price", "max_price"):
        val = _coerce_null(raw.get(price_key))
        if val is not None:
            try:
                out[price_key] = int(float(val))
            except (TypeError, ValueError):
                out[price_key] = None
        else:
            out[price_key] = None

    title = _coerce_null(raw.get("title"))
    out["title"] = title.strip() if isinstance(title, str) and title.strip() else None

    occasion = _coerce_null(raw.get("occasion"))
    if isinstance(occasion, str):
        occasion = occasion.strip().lower()
        occasion = occasion if occasion in _LLM_ENTITY_OCCASIONS else None
    else:
        occasion = None
    out["occasion"] = occasion

    style = _coerce_null(raw.get("style"))
    if isinstance(style, str):
        style = style.strip().lower()
        style = style if style in _LLM_ENTITY_STYLES else None
    else:
        style = None
    out["style"] = style

    action = _coerce_null(raw.get("action"))
    if isinstance(action, str):
        action = action.strip().lower()
        action = action if action == "more" else None
    else:
        action = None
    out["action"] = action

    return out


def _store_llm_entities(data: dict, user_profile: dict, entities: dict) -> None:
    stored = dict(entities or {})
    user_profile["llm_extracted_entities"] = stored
    data["llm_extracted_entities"] = stored


def _parse_classifier_json(raw: str) -> dict:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    entities = parsed.get("entities") or {}
    intent = (
        parsed.get("intent") or parsed.get("category") or "general"
    ).strip().lower()
    return {
        "intent": intent,
        "confidence": float(parsed.get("confidence", 0.5)),
        "entities": entities,
    }


def _programmatic_intent_override(user_query: str, user_profile: dict) -> str | None:
    """Route factual commerce queries without LLM when patterns are clear."""
    normalized = (user_query or "").strip()
    if not normalized:
        return None

    if is_greeting_message(normalized):
        return "greeting"

    if is_unrecognizable_input(normalized):
        return "general"

    if _HUMAN_HANDOFF_RE.search(normalized):
        return "human_handoff"

    if re.search(r"\b(return\s+policy|refund\s+policy)\b", normalized, re.I):
        return "general"

    if _POLICY_FAQ_RE.search(normalized) and not _BROWSE_ACTION_RE.search(
        normalized
    ):
        if not _PRICE_PRODUCT_INFO_RE.search(normalized) or re.search(
            r"\b(policy|hallmark|bis|certificate|guarantee|emi)\b", normalized, re.I
        ):
            return "general"

    if _ORDER_TRACKING_RE.search(normalized) or _ORDER_DELIVERY_RE.search(normalized):
        return "order_tracking"

    if _EXCHANGE_RE.search(normalized):
        return "returns_refund"

    if _RETURNS_RE.search(normalized):
        return "returns_refund"

    if _COMPLAINT_RE.search(normalized):
        return "complaint"

    if _OFFERS_INTENT_RE.search(normalized) and not _CATEGORY_WORD_RE.search(
        normalized
    ) and not _MATERIAL_WORD_RE.search(normalized):
        return "offers"

    if _looks_like_store_query(normalized):
        return "store_info"

    if _PRODUCT_EDD_RE.search(normalized) and not _ORDER_DELIVERY_RE.search(
        normalized
    ):
        return "product_info"

    if _looks_like_product_info_query(normalized, user_profile):
        return "product_info"

    return None


def _is_obvious_reset(query: str) -> bool:
    return bool(
        re.search(r"^\s*(hi|hello|menu|back|cancel|namaste)\s*$", query, re.I)
    )


def _maybe_expire_product_search_session(user_profile: dict) -> None:
    if user_profile.get("service_selected") != ServiceList.PRODUCT_SEARCH.value:
        return
    last_at = user_profile.get("last_search_at")
    if last_at and time.time() - last_at > PRODUCT_SEARCH_SESSION_EXPIRY_SECONDS:
        user_profile["service_selected"] = ""


def _flow_escape_should_classify(user_query: str) -> bool:
    if _RETURNS_RE.search(user_query) or _EXCHANGE_RE.search(user_query):
        return True
    if _HUMAN_HANDOFF_RE.search(user_query):
        return True
    if _COMPLAINT_RE.search(user_query) and not _CATEGORY_WORD_RE.search(user_query):
        return True
    return False


def _maybe_prompt_flow_switch(
    data: dict,
    intent: str,
    user_profile: dict,
    user_query: str,
    confidence: float,
) -> bool:
    if intent in ("greeting", "menu_help", "human_handoff", "general"):
        return False
    current = user_profile.get("service_selected", "")
    new_service = _CATEGORY_TO_SERVICE.get(intent)
    if not (
        current
        and new_service
        and current != new_service.value
        and confidence >= 0.5
        and not _is_obvious_reset(user_query)
    ):
        return False
    data["bot_response"] = build_flow_switch_bot_response(current, intent)
    user_profile["pending_flow_switch"] = {
        "intent": intent,
        "service": new_service.value,
    }
    return True


def _handle_human_handoff(data: dict, user_profile: dict, phone_number: str) -> None:
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


def _apply_intent_routing(
    data: dict,
    intent: str,
    user_profile: dict,
    user_query: str = "",
    confidence: float = 1.0,
) -> bool:
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
        if _maybe_prompt_flow_switch(
            data, intent, user_profile, user_query, confidence
        ):
            return True
        user_profile["service_selected"] = ServiceList.COMPLAINT.value
        data["bot_response"] = [build_complaint_flow_bot_response()]
        return True

    service = _CATEGORY_TO_SERVICE.get(intent)
    if service:
        if _maybe_prompt_flow_switch(
            data, intent, user_profile, user_query, confidence
        ):
            return True
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
    if _STORE_LOOKUP_RE.search(normalized):
        return True
    entities = extract_entities(normalized)
    return bool(entities.get("pincode") or entities.get("city"))


def _should_offer_clarification(data: dict, user_query: str, user_profile: dict) -> bool:
    if user_profile.get("pending_clarification"):
        return False
    if is_pure_greeting(user_query) or is_greeting_message(user_query):
        return False
    service = user_profile.get("service_selected")
    if service == ServiceList.PRODUCT_SEARCH.value:
        chat_history = user_profile.get("chat_history", [])
        if chat_history and not _REROUTE_RE.search(user_query):
            entities = extract_entities(user_query)
            if (
                entities.get("category")
                or entities.get("material_type")
                or entities.get("title")
                or _BROWSE_ACTION_RE.search(user_query)
            ):
                return False
    return True


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


async def classify_query_for_audit(
    user_query: str,
    user_profile: dict | None = None,
    *,
    use_llm: bool = True,
) -> dict:
    """Classify a single query and return intent, confidence, and source."""
    profile = dict(user_profile or {})
    profile.setdefault("chat_history", [])
    profile.setdefault("service_selected", "")

    data = {
        "phone_number": "919999999999",
        "messages": {"text": {"body": user_query}},
        "user_profile": profile,
        "client_id": "kisna",
    }

    if is_greeting_message(user_query):
        return {"intent": "greeting", "confidence": 1.0, "entities": {}, "source": "shortcut"}

    if is_menu_request(user_query):
        return {"intent": "menu_help", "confidence": 1.0, "entities": {}, "source": "shortcut"}

    if profile.get("awaiting_store_pincode") or _looks_like_store_query(user_query):
        if user_query.strip().lower() not in ("cancel", "back"):
            return {
                "intent": "store_info",
                "confidence": 1.0,
                "entities": {},
                "source": "shortcut",
            }

    override = _programmatic_intent_override(user_query, profile)
    if override:
        return {
            "intent": override,
            "confidence": 1.0,
            "entities": {},
            "source": "programmatic",
        }

    if not use_llm:
        return {"intent": "unknown", "confidence": 0.0, "entities": {}, "source": "none"}

    chat_history = profile.get("chat_history", [])[-8:]
    chat_history_str = ""
    for chat in chat_history:
        role = chat.get("role", "")
        content = chat.get("content", "")
        chat_history_str += f"{role.capitalize()}: {content}\n"

    classifier_response = await complete_chat(
        agent=AgentName.CLASSIFIER,
        agent_display_name="Classifier Agent",
        instruction=CONTEXT,
        messages=[
            {"role": "system", "content": f"Chat history: {chat_history_str}"},
            {"role": "user", "content": f"User Query: {user_query}"},
        ],
        phone_number=data["phone_number"],
        client_id=data["client_id"],
    )
    parsed = _parse_classifier_json(classifier_response)
    return {
        "intent": parsed["intent"],
        "confidence": parsed["confidence"],
        "entities": _sanitize_llm_entities(parsed.get("entities") or {}),
        "source": "llm",
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

        _maybe_expire_product_search_session(user_profile)

        if is_greeting_message(user_query):
            return True

        if _REROUTE_RE.search(user_query):
            return True

        if user_profile.get("awaiting_store_pincode"):
            return False

        service = user_profile.get("service_selected")
        if service == ServiceList.AD_FLOW.value and _looks_like_store_query(user_query):
            return False

        if service == ServiceList.ORDER_TRACKING.value:
            if _REROUTE_RE.search(user_query) or _flow_escape_should_classify(user_query):
                return True
            return False

        if service == ServiceList.OFFERS.value:
            if _REROUTE_RE.search(user_query) or _flow_escape_should_classify(user_query):
                return True
            return False

        if service == ServiceList.PRODUCT_SEARCH.value:
            last_viewed = user_profile.get("last_viewed_product")
            if last_viewed and _PRICE_PRODUCT_INFO_RE.search(user_query):
                return False
            if _OFFERS_INTENT_RE.search(user_query) and not _CATEGORY_WORD_RE.search(
                user_query
            ):
                return True
            if _ORDER_TRACKING_RE.search(user_query) or _ORDER_DELIVERY_RE.search(
                user_query
            ):
                return True
            if _looks_like_store_query(user_query):
                return True
            if is_unrecognizable_input(user_query):
                return True
            if _flow_escape_should_classify(user_query):
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

                if user_profile.get("pending_clarification"):
                    user_profile["pending_clarification"] = False
                    user_profile["_skip_programmatic_once"] = True
                    clarified = user_query.strip()
                    user_query = (
                        "Context: user was asked to clarify their previous message. "
                        f"Their clarification: {clarified}"
                    )
                    data["messages"]["text"]["body"] = user_query

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
                if is_greeting_message(user_query):
                    user_profile["service_selected"] = ""
                    _store_llm_entities(data, user_profile, {})
                    data["classified_category"] = "greeting"
                    data["bot_response"] = build_greeting_welcome_bot_responses(
                        phone_number=phone_number,
                        chat_history=chat_history,
                    )
                    logger.info(
                        "Greeting shortcut — welcome and main menu",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if is_menu_request(user_query):
                    _store_llm_entities(data, user_profile, {})
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
                        _store_llm_entities(data, user_profile, {})
                        user_profile["service_selected"] = ServiceList.AD_FLOW.value
                        data["classified_category"] = "store_info"
                        logger.info(
                            "Store lookup shortcut — routing to ad_flow",
                            extra={"phone_number": phone_number},
                        )
                        return data

                skip_programmatic = user_profile.pop("_skip_programmatic_once", False)
                override_intent = None
                if not skip_programmatic:
                    override_intent = _programmatic_intent_override(
                        user_query,
                        user_profile,
                    )
                if override_intent:
                    _store_llm_entities(data, user_profile, {})
                    data["classified_category"] = override_intent
                    data["classifier_confidence"] = 1.0
                    logger.info(
                        "Programmatic classifier override",
                        extra={
                            "phone_number": phone_number,
                            "intent": override_intent,
                        },
                    )
                    if override_intent == "human_handoff":
                        _handle_human_handoff(data, user_profile, phone_number)
                        logger.info(
                            "Human handoff triggered",
                            extra={"phone_number": phone_number},
                        )
                        return data
                    if _apply_intent_routing(
                        data,
                        override_intent,
                        user_profile,
                        user_query=user_query,
                        confidence=1.0,
                    ):
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
                intent = parsed["intent"] or "menu_help"
                confidence = parsed["confidence"]
                _store_llm_entities(
                    data,
                    user_profile,
                    _sanitize_llm_entities(parsed.get("entities") or {}),
                )
                data["classified_category"] = intent
                data["classifier_confidence"] = confidence

                logger.info(
                    "Classifier intent",
                    extra={
                        "intent": intent,
                        "confidence": confidence,
                        "entities": data.get("llm_extracted_entities"),
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
                    or _COMPARATIVE_RE.search(user_query)
                ):
                    if user_profile.get("last_viewed_product") and (
                        intent == "product_info"
                        or _PRICE_PRODUCT_INFO_RE.search(user_query)
                        or _COMPARATIVE_RE.search(user_query)
                    ):
                        intent = "product_info"
                        data["classified_category"] = intent
                    elif _PRODUCT_NAME_RE.search(user_query) and _PRICE_PRODUCT_INFO_RE.search(
                        user_query
                    ):
                        intent = "product_info"
                        data["classified_category"] = intent

                if (
                    confidence < CLARIFICATION_CONFIDENCE_THRESHOLD
                    and _should_offer_clarification(data, user_query, user_profile)
                ):
                    user_profile["pending_clarification"] = True
                    data["bot_response"] = build_clarification_bot_response(
                        intent, confidence
                    )
                    logger.warning(
                        "Low-confidence classification — asking clarification",
                        extra={
                            "phone_number": phone_number,
                            "intent": intent,
                            "confidence": confidence,
                        },
                    )
                    return data

                if intent == "human_handoff":
                    _handle_human_handoff(data, user_profile, phone_number)
                    logger.info(
                        "Human handoff triggered",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if _apply_intent_routing(
                    data,
                    intent,
                    user_profile,
                    user_query=user_query,
                    confidence=confidence,
                ):
                    return data

            return data
        except json.JSONDecodeError as e:
            logger.exception(
                "Classifier returned invalid JSON",
                extra={"exception": e, "phone_number": phone_number},
            )
            _store_llm_entities(data, user_profile, {})
            user_profile["service_selected"] = ""
            data["bot_response"] = [build_main_menu_bot_response()]
            return data
        except Exception as e:
            logger.exception(
                "Exception occured while running classifier.",
                extra={"exception": e, "phone_number": phone_number},
            )
            _store_llm_entities(data, user_profile, {})
            user_profile["service_selected"] = ""
            data["bot_response"] = [build_main_menu_bot_response()]
            return data
