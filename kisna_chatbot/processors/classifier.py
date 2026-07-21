import json
import re
import time
from typing import Any
from zoneinfo import ZoneInfo

from kisna_chatbot.ai import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.constants import ADMINS, KIA_HANDOFF_MESSAGE
from kisna_chatbot.models.service_list import ServiceList
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.ad_flow_agent import _PINCODE_ONLY_RE
from kisna_chatbot.processors.entity_extractor import (
    extract_structured_fields,
    is_unrecognizable_input,
)
from kisna_chatbot.processors.service_list import (
    build_acknowledgement_bot_response,
    build_clarification_bot_response,
    build_complaint_flow_bot_response,
    flow_switch_acknowledgement,
    build_greeting_welcome_bot_responses,
    build_main_menu_bot_response,
    is_new_session,
    is_menu_request,
    is_pure_greeting,
)
from kisna_chatbot.processors.gold_rate_handler import build_gold_rate_bot_response
from kisna_chatbot.processors.support_handler import build_expert_support_bot_response
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier
from kisna_chatbot.utils.format_chathistory import format_recent_history_str
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.reply_composer import sanitize_classifier_language
from kisna_chatbot.utils.session_state import (
    clear_transient_for_service_change,
    maybe_expire_session,
    reset_transient_state,
)
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
    r")(?:\s+(?:there|ji|dear|all|everyone|friend))?\s*[!?.]*\s*$",
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
    r"koi\s+offer|offer\s+hai|making\s+charge\s+off|"
    r"current\s+offers?|offers?\s+available|what\s+are.*offers?|show.*offers?"
    r")\b",
    re.I,
)

_FAQ_BRAND_RE = re.compile(
    r"\b("
    r"what is kisna|what are kisna|who is kisna|about kisna|kisna kya hai|"
    r"kisna ke baare|kisna kaun hai|tell me about kisna|what is kisna jewellery|"
    r"what are kisna jewellery|kisna jewellery kya hai"
    r")\b",
    re.I,
)

_FAQ_WH_START_RE = re.compile(
    r"^\s*(what is|what are|who is|tell me about)\b",
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

_POLICY_TOPIC_RE = re.compile(
    r"\b(return|exchange|buyback|refund|wapas|warranty|"
    r"making\s+charges?|certificate|hallmark|emi|"
    r"digital\s+gold|safegold|delivery|shipping|"
    r"payment|cod|care|clean)\b",
    re.I,
)

_POLICY_INFO_SEEKING_RE = re.compile(
    r"\b(policy|kya hai|kaise|how (do|to|can)|"
    r"kitna|kitne|what is|batao|bataye|explain|"
    r"process|procedure|rules?|possible)\b",
    re.I,
)

_ACTION_INTENT_RE = re.compile(
    r"\b(karna hai|kar do|karwana hai|chahiye|initiate|"
    r"start (a )?return|process my|raise (a )?|file (a )?|"
    r"register (a )?|wapas karna|wapas chahiye|"
    r"refund chahiye|"
    r"i want to (return|exchange|refund)|"
    r"i need to (return|exchange))\b",
    re.I,
)

_CUSTOM_JEWELLERY_RE = re.compile(
    r"\b(custom(ize|ise|ized|ised)?|customis|made to order|"
    r"bespoke|personal\w*|engrav\w*|design my own|"
    r"apni design|custom design|naam likhwana|"
    r"initials|special order)\b",
    re.I,
)

_ACKNOWLEDGEMENT_RE = re.compile(
    r"^\s*(thank(s| you)?|thanx|ty|ok(ay)?|cool|nice|great|"
    r"good|perfect|awesome|dhanyavaad|shukriya|theek hai|"
    r"acha|accha|got it|sahi hai|👍|🙏)\s*[!.]*\s*$",
    re.I,
)

_CUSTOM_JEWELLERY_HANDOFF_MESSAGE = (
    "For custom and personalized jewellery, I'll connect you with "
    "a Kisna design expert who can help bring your vision to life. ✨"
)

_HUMAN_HANDOFF_RE = re.compile(
    r"\b("
    r"human|agent\s+se|customer\s+care|live\s+agent|support\s+chahiye|"
    r"baat\s+karni\s+hai|kisi\s+se\s+baat|call\s+me\s+back|connect\s+me|"
    r"need\s+urgent\s+support|talk\s+to\s+(?:an?\s+)?(?:agent|human|expert)|"
    r"baat\s+karao|call\s+karwao"
    r")\b",
    re.I,
)

_GOLD_RATE_RE = re.compile(
    r"\b("
    r"gold\s+rate|gold\s+price\s+today|today'?s?\s+rate|aaj\s+ka\s+rate|"
    r"sone\s+ka\s+bhav|sone\s+ka\s+rate|gold\s+price|"
    r"sona\s+kitne\s+ka|22\s*kt?\s+ka\s+(rate|bhav)|24\s*kt?\s+ka\s+(rate|bhav)"
    r")\b",
    re.I,
)

_VIDEO_CALL_RE = re.compile(
    r"\b("
    r"video\s*call|video\s*calling|video\s*consult\w*|video\s*shopping|"
    r"video\s*meeting|video\s*chat|"
    r"video\s*(par|pe)\s+(?:\w+\s+){0,3}(dikha|dekh|baat)\w*"
    r")\b",
    re.I,
)

# Any Indic script (Devanagari through Malayalam). The regex shortcut/gate layer
# is Latin-only, so these messages must ALWAYS reach the LLM classifier — otherwise
# a sticky session silently reuses stale filters (e.g. Gujarati "ring" continued a
# necklace search).
_INDIC_SCRIPT_RE = re.compile(r"[ऀ-ൿ]")

# Savings-plan / scheme queries (KMR = Kisna Meri Roshni) answered from the KB,
# never by the offers agent.
_SCHEME_RE = re.compile(
    r"\b("
    r"schemes?|kmr|meri\s+roshni|savings?\s+plan|gold\s+plan|"
    r"monthly\s+plan|installment\s+plan|kisht?\s+plan|10\s*\+\s*1"
    r")\b",
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
    r"in\s+stock|stock|delivery\s+days|edd|chain"
    r")\b|"
    r"(isme|is\s+me|iska|is\s+ka)\s+(kitna|price|cost|available)",
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

# Fuzzy pagination/continuation phrases — kept in sync with _SHOW_MORE_RE in
# product_search_agent_v3.py (duplicated locally to avoid a circular import).
_CONTINUATION_RE = re.compile(
    r"\b(show\s+more|more|next|aur\s+dikhao|next\s+3|kuch\s+aur|show\s+next|and\s+more|"
    r"any\s+other\s+options?|anything\s+else|something\s+else|other\s+options?|"
    r"alternate\s*s?|alternatives?|aur\s+kuch|koi\s+aur)\b",
    re.I,
)

# FIX 2: price signal regex for active-session clarification guard
_PRICE_SIGNAL_RE = re.compile(
    r"\b("
    r"under|below|above|over|upto|up\s+to|maximum|minimum|max|min|"
    r"tak|se\s+upar|se\s+zyada|se\s+kam|"
    r"\u20b9|k\b|lakh|lac|hazaar|thousand|"
    r"\d{3,}"
    r")\b",
    re.I,
)

_COMPARATIVE_RE = re.compile(
    r"\b(cheapest|cheaper|better|best|worst|compare|comparison|sabse\s+sasta|"
    r"affordable|sasta|which\s+is\s+cheaper|difference|best\s+one)\b",
    re.I,
)

_EXPENSIVE_SEARCH_RE = re.compile(
    r"\b(expensive|mehnga|costly|aur\s+mehnga|zyada\s+price|premium|aur\s+expensive)\b",
    re.I,
)

_SIZE_QUERY_RE = re.compile(
    r"\b(size|sizes|variant|variants|karat|kt\b|18kt|14kt|22kt|chain)\b",
    re.I,
)


_COMPETITOR_RE = re.compile(
    r"\b(tanishq|kalyan|malabar|caratlane|reliance\s+jewels|bluestone|"
    r"joyalukkas|pc\s+jeweller|pcj|bhima|grt|tbz|senco|png|"
    r"other\s+brands?|local\s+jeweler|local\s+jeweller|why\s+buy\s+from|"
    r"why\s+choose|better\s+than)\b",
    re.I,
)


def _is_competitor_comparison(text: str) -> bool:
    return bool(_COMPETITOR_RE.search((text or "").strip()))


def _is_custom_jewellery_query(text: str) -> bool:
    return bool(_CUSTOM_JEWELLERY_RE.search((text or "").strip()))


def _is_policy_action_query(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if not _POLICY_TOPIC_RE.search(normalized):
        return False
    return bool(_ACTION_INTENT_RE.search(normalized))


def _is_policy_information_query(text: str) -> bool:
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _is_policy_action_query(normalized):
        return False
    if _OFFERS_INTENT_RE.search(normalized):
        return False
    if not _POLICY_TOPIC_RE.search(normalized):
        return False
    return bool(_POLICY_INFO_SEEKING_RE.search(normalized))


def _programmatic_intent_override(text: str) -> tuple[str, float] | None:
    """Regex override for policy FAQ vs action, custom jewellery handoff."""
    normalized = (text or "").strip()
    if not normalized:
        return None
    if _is_competitor_comparison(normalized):
        return ("general", 0.95)
    if _is_custom_jewellery_query(normalized):
        return ("human_handoff", 0.95)
    if _GOLD_RATE_RE.search(normalized):
        return ("gold_rate", 0.95)
    if _VIDEO_CALL_RE.search(normalized):
        return ("video_call", 0.95)
    if _SCHEME_RE.search(normalized):
        return ("general", 0.9)
    # Policy action/info regexes are HINTS only (see _programmatic_intent_hint):
    # they misfire on phrases like "return gift ke liye kuch dikhao", so the
    # LLM keeps the final word.
    return None


def _programmatic_intent_hint(text: str) -> str | None:
    """Soft routing hint passed into the classifier prompt — never a verdict."""
    normalized = (text or "").strip()
    if not normalized:
        return None
    if _is_policy_action_query(normalized):
        return (
            "heuristic suggests a return/refund/exchange ACTION request "
            "(intent returns_refund) — but e.g. 'return gift' means a present, "
            "so trust the actual meaning"
        )
    if _is_policy_information_query(normalized):
        return (
            "heuristic suggests a policy/FAQ QUESTION (intent general) — "
            "trust the actual meaning if it differs"
        )
    return None


def _is_product_price_signal(user_query: str) -> bool:
    if not _PRICE_PRODUCT_INFO_RE.search(user_query or ""):
        return False
    if _POLICY_TOPIC_RE.search(user_query or ""):
        return False
    return True


def _in_active_input_flow(user_profile: dict) -> bool:
    if user_profile.get("awaiting_store_pincode"):
        return True
    if user_profile.get("pending_flow_switch"):
        return True
    if user_profile.get("pending_clarification"):
        return True
    if user_profile.get("service_selected") == ServiceList.COMPLAINT.value:
        return True
    if user_profile.get("callback_capture_step"):
        return True
    return False


def _is_acknowledgement_message(text: str, user_profile: dict) -> bool:
    if _in_active_input_flow(user_profile):
        return False
    return bool(_ACKNOWLEDGEMENT_RE.match((text or "").strip()))


def _looks_like_faq_query(text: str) -> bool:
    """Brand/FAQ questions that must reach the LLM classifier (not regex product search)."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _FAQ_BRAND_RE.search(normalized):
        return True
    if _is_policy_information_query(normalized):
        return True
    if _POLICY_TOPIC_RE.search(normalized):
        return True
    if not _FAQ_WH_START_RE.match(normalized):
        return False
    if _BROWSE_ACTION_RE.search(normalized):
        return False
    if _is_product_price_signal(normalized):
        return False
    if _PRODUCT_NAME_RE.search(normalized):
        return False
    if _OFFERS_INTENT_RE.search(normalized):
        return False
    return True


def _looks_like_browse_escape(text: str) -> bool:
    """True when user in store-pincode wait clearly wants a catalog search instead."""
    normalized = (text or "").strip()
    if not normalized or _looks_like_faq_query(normalized):
        return False
    if _BROWSE_ACTION_RE.search(normalized) and (
        _CATEGORY_WORD_RE.search(normalized) or _MATERIAL_WORD_RE.search(normalized)
    ):
        return True
    if _CATEGORY_WORD_RE.search(normalized) and _MATERIAL_WORD_RE.search(normalized):
        return True
    structured = extract_structured_fields(normalized)
    if (structured.get("min_price") or structured.get("max_price")) and (
        _CATEGORY_WORD_RE.search(normalized) or _MATERIAL_WORD_RE.search(normalized)
    ):
        return True
    return False


def _store_pincode_escape_intent(user_query: str) -> str | None:
    """Return intent when user should leave awaiting_store_pincode for another flow."""
    normalized = (user_query or "").strip()
    if not normalized:
        return None
    if _looks_like_browse_escape(normalized):
        return "product_search"
    if _OFFERS_INTENT_RE.search(normalized) and not _CATEGORY_WORD_RE.search(normalized):
        return "offers"
    if _ORDER_TRACKING_RE.search(normalized) or _ORDER_DELIVERY_RE.search(normalized):
        return "order_tracking"
    if _is_policy_action_query(normalized):
        return "returns_refund"
    if _COMPLAINT_RE.search(normalized) and not _CATEGORY_WORD_RE.search(normalized):
        return "complaint"
    return None


_LLM_ENTITY_CATEGORIES = frozenset(
    {
        "ring",
        "earring",
        "necklace",
        "pendant",
        "pendant_set",       # e.g. "pendant sets above 50k"
        "necklace_set",      # e.g. "necklace sets under 1 lakh"
        "bracelet",
        "bangle",
        "mangalsutra",
        "mangalsutra_bracelet",  # e.g. "mangalsutra bracelet"
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
_LLM_CATEGORY_ALIASES = {
    "nose_ring":         "nosewear",
    # Space-separated forms the LLM may produce for composite categories
    "pendant set":       "pendant_set",
    "pendant sets":      "pendant_set",
    "necklace set":      "necklace_set",
    "necklace sets":     "necklace_set",
    "mangalsutra bracelet": "mangalsutra_bracelet",
    "mangalsutra bracelets": "mangalsutra_bracelet",
}


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

    direction = _coerce_null(raw.get("price_direction"))
    if isinstance(direction, str):
        direction = direction.strip().lower()
        direction = direction if direction in ("lower", "higher") else None
    else:
        direction = None
    out["price_direction"] = direction

    # 1-based index of a shown product the user is referring to ("the 2nd one",
    # "the gold one", "बीच वाला"). Resolved by the LLM against the shown list;
    # validated to a small positive int here.
    ref = _coerce_null(raw.get("product_reference"))
    if ref is not None:
        try:
            ref_int = int(float(ref))
            ref = ref_int if 1 <= ref_int <= 10 else None
        except (TypeError, ValueError):
            ref = None
    out["product_reference"] = ref

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
    confidence = float(parsed.get("confidence", 0.5))

    # Fix inverted price ranges (e.g. "above 80k under 50k" mapped to min=80k, max=50k)
    try:
        min_p = entities.get("min_price")
        max_p = entities.get("max_price")
        if min_p is not None and max_p is not None:
            min_val = int(float(min_p))
            max_val = int(float(max_p))
            if min_val > max_val:
                entities["min_price"] = max_val
                entities["max_price"] = min_val
                if intent == "product_search" and confidence < 0.85:
                    confidence = 0.85
    except (TypeError, ValueError):
        pass

    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "language": sanitize_classifier_language(parsed.get("language")),
    }


def _is_obvious_reset(query: str) -> bool:
    return bool(
        re.search(r"^\s*(hi|hello|menu|back|cancel|namaste)\s*$", query, re.I)
    )


def _maybe_expire_product_search_session(user_profile: dict) -> None:
    maybe_expire_session(user_profile)


_RATING_WORD_MAP = {
    "1": 1,
    "one": 1,
    "ek": 1,
    "2": 2,
    "two": 2,
    "do": 2,
    "3": 3,
    "three": 3,
    "teen": 3,
    "4": 4,
    "four": 4,
    "char": 4,
    "5": 5,
    "five": 5,
    "paanch": 5,
    "panch": 5,
}


def _parse_rating_reply(text: str) -> int | None:
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return None
    if normalized.isdigit():
        val = int(normalized)
        return val if 1 <= val <= 5 else None
    return _RATING_WORD_MAP.get(normalized)


_INDIC_LANGS = frozenset(
    {"hi", "gu", "mr", "ta", "te", "bn", "kn", "ml", "pa", "or"}
)


def resolve_reply_language(language: str | None, user_text: str) -> str:
    """Language identity from the LLM; SCRIPT from the user's actual characters.

    The user's message proves which script they type — never trust the model's
    -Latn judgement. "Return krna hai" + "hi" → "hi-Latn"; "रिटर्न करना है" +
    "hi-Latn" → "hi". Reply always mirrors the script of the LAST message.
    """
    lang = sanitize_classifier_language(language)
    base = lang[:-5] if lang.endswith("-Latn") else lang
    has_indic_script = bool(_INDIC_SCRIPT_RE.search(user_text or ""))
    if has_indic_script:
        return base if base in _INDIC_LANGS else lang
    if base in _INDIC_LANGS:
        return f"{base}-Latn"
    return lang


def _store_language(
    user_profile: dict, language: str | None, user_text: str = ""
) -> None:
    """Per-message language state — the LAST message always wins.

    Without a fresh LLM label (shortcut paths), still correct the stored
    language's script to match the current message.
    """
    if language:
        user_profile["language"] = resolve_reply_language(language, user_text)
        return
    stored = user_profile.get("language")
    if stored and user_text:
        user_profile["language"] = resolve_reply_language(stored, user_text)


def _flow_escape_should_classify(user_query: str) -> bool:
    if _is_policy_action_query(user_query) or _is_policy_information_query(user_query):
        return True
    if _HUMAN_HANDOFF_RE.search(user_query):
        return True
    if _VIDEO_CALL_RE.search(user_query) or _SCHEME_RE.search(user_query):
        return True
    if _GOLD_RATE_RE.search(user_query):
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
    """Silent flow switch with a one-line acknowledgement (no confirmation buttons)."""
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

    clear_transient_for_service_change(
        user_profile,
        from_service=current,
        to_service=new_service.value,
    )
    if current == ServiceList.PRODUCT_SEARCH.value:
        user_profile["last_search_filters"] = {}
        user_profile["shown_product_ids"] = []
    user_profile.pop("pending_flow_switch", None)
    user_profile["service_selected"] = new_service.value
    data["classified_category"] = intent
    data["_flow_switch_ack"] = flow_switch_acknowledgement(current, intent)
    return False  # continue routing; ack prepended by callers if needed


def _prepend_flow_switch_ack(data: dict) -> None:
    """Prepend the silent-switch ack to an EXISTING bot_response.

    Never creates bot_response from the ack alone — downstream agents skip
    when bot_response is present, so an ack-only response would dead-end the
    turn ("Sure — I'll help with returns." and then nothing). When the service
    pipeline still has to run, the ack stays in data and main.py prepends it
    after the pipeline produced the real response.
    """
    responses = data.get("bot_response")
    if not isinstance(responses, list):
        return
    ack = data.pop("_flow_switch_ack", None)
    if not ack:
        return
    # Suppress the ack when the response already carries its own content. A
    # separate "Sure, let me help" line then just adds a redundant — and often
    # mixed-language — bubble in front (e.g. a Hinglish ack glued before an
    # English product intro or the pincode prompt). Cases:
    #  - products present (the varied intro already greets warmly)
    #  - the first item is a warm opener or a self-sufficient functional prompt
    #    (slot-fill, greeting, ack, pincode ask, budget/rating prompt)
    for item in responses:
        if isinstance(item, dict) and item.get("type") in (
            "media",
            "image_with_cta",
            "cta_url",
        ):
            return
    _SELF_SUFFICIENT = {
        "slot_fill",
        "vague_fallback",
        "greeting_new",
        "greeting_return",
        "acknowledgement",
        "store_pincode",
        "budget_prompt",
        "rating_prompt",
    }
    first = responses[0] if responses else {}
    if isinstance(first, dict) and first.get("_compose") in _SELF_SUFFICIENT:
        return
    ack_msg = {"type": "text", "text": ack, "_compose": "flow_switch_ack"}
    data["bot_response"] = [ack_msg, *responses]


def _handle_custom_jewellery_handoff(
    data: dict, user_profile: dict, phone_number: str
) -> None:
    user_profile["live_agent_requested_at"] = int(time.time())
    user_profile["live_agent_required"] = True
    for admin in ADMINS:
        send_customer_support_template(
            phone_number=admin,
            customer_name=user_profile.get("username", "Customer"),
            customer_phone=phone_number,
        )
    data["bot_response"] = [
        {"type": "text", "text": _CUSTOM_JEWELLERY_HANDOFF_MESSAGE}
    ]


def _handle_human_handoff(data: dict, user_profile: dict, phone_number: str) -> None:
    data["bot_response"] = build_expert_support_bot_response(
        phone_number, user_profile
    )


async def _finalize_classifier_response(data: dict) -> None:
    if data.get("_fetch_gold_rate"):
        from kisna_chatbot.utils.message_trace import try_trace

        try_trace(data, "Action", "Fetching live gold rates")
        data["bot_response"] = await build_gold_rate_bot_response(
            data.get("app_state")
        )
        data.pop("_fetch_gold_rate", None)
        text = ""
        if data.get("bot_response"):
            first = data["bot_response"][0] if data["bot_response"] else {}
            text = (first.get("text") or "") if isinstance(first, dict) else ""
        if "couldn't fetch" in text.lower():
            try_trace(
                data,
                "API call",
                "GET /api/v1/clara/rates → failed / empty",
                status="warn",
            )
        else:
            # Count karat lines like "• *24KT*"
            karat_lines = [
                ln
                for ln in text.splitlines()
                if ln.strip().startswith("•") and "KT" in ln.upper()
            ]
            try_trace(
                data,
                "API call",
                f"GET /api/v1/clara/rates → {len(karat_lines) or 'rates'} shown",
            )
            try_trace(data, "Result", "Sent gold rate message")


def _route_resolved_intent(
    data: dict,
    user_profile: dict,
    phone_number: str,
    user_query: str,
    chat_history: list,
    intent: str,
    confidence: float,
) -> bool:
    """Route a resolved intent; return True when processing should stop."""
    data["classified_category"] = intent
    data["classifier_confidence"] = confidence
    try:
        from kisna_chatbot.utils.message_trace import trace_step

        _INTENT_LABELS = {
            "product_search": "Product search",
            "store_info": "Store lookup",
            "offers": "Offers",
            "order_tracking": "Order tracking",
            "returns_refund": "Returns & refunds",
            "complaint": "Complaint",
            "greeting": "Greeting",
            "menu_help": "Main menu",
            "human_handoff": "Live agent handoff",
            "gold_rate": "Gold rate",
            "video_call": "Video call scheduling",
            "compare": "Compare products",
            "repair": "Clarify / repair",
            "general": "FAQ / general",
        }
        label = _INTENT_LABELS.get(intent, intent.replace("_", " ").title())
        status = "warn" if confidence < 0.45 else "ok"
        trace_step(
            data,
            "Understood as",
            f"{label} ({confidence:.0%} confidence)",
            status=status,
        )
        if intent == "human_handoff":
            data["_trace_outcome"] = "handoff"
    except Exception:
        pass

    if intent == "greeting":
        user_profile["service_selected"] = ""
        data["bot_response"] = build_greeting_welcome_bot_responses(
            phone_number=phone_number,
            chat_history=chat_history,
            user_profile=user_profile,
        )
        return True

    if intent == "human_handoff":
        if _is_custom_jewellery_query(user_query):
            _handle_custom_jewellery_handoff(data, user_profile, phone_number)
        else:
            _handle_human_handoff(data, user_profile, phone_number)
        return True

    if intent == "gold_rate":
        user_profile["service_selected"] = ""
        data["_fetch_gold_rate"] = True
        return True

    if intent == "repair":
        # User said the last reply was wrong / not what they meant, without a full
        # new request. Acknowledge warmly and ask what they actually want — never
        # silently re-search. Narrated into their language.
        #
        # CRITICAL: clear the product context. The wrong results the user just
        # rejected would otherwise stay in last_search_* / shown products and be
        # re-injected into the classifier context, anchoring the model to the
        # SAME wrong entities on the retry — an infinite "still showing rings"
        # loop. Repair means fresh start.
        for key in (
            "last_search_filters",
            "last_search_products",
            "last_search_buffer",
            "last_viewed_product",
            "shown_product_ids",
            "last_search_at",
            "llm_extracted_entities",
            "last_search_page",
            "last_search_total",
        ):
            user_profile.pop(key, None)
        user_profile["service_selected"] = ""
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    "Oops, my apologies! 🙏 Tell me a bit more about what you're "
                    "looking for and I'll get it right — a type of jewellery, a "
                    "budget, a style?"
                ),
                "_compose": "repair",
            }
        ]
        return True

    if intent == "video_call":
        from kisna_chatbot.config.gupshup import get_videocall_flow_id
        from kisna_chatbot.processors.service_list import (
            _start_callback_text_capture,
            build_video_call_flow_bot_response,
        )

        if get_videocall_flow_id():
            user_profile["service_selected"] = ServiceList.CALLBACK.value
            data["bot_response"] = [build_video_call_flow_bot_response()]
        else:
            data["bot_response"] = _start_callback_text_capture(
                user_profile, request_type="video_call"
            )
        return True

    if (
        confidence < CLARIFICATION_CONFIDENCE_THRESHOLD
        and _should_offer_clarification(data, user_query, user_profile)
    ):
        user_profile["pending_clarification"] = True
        data["bot_response"] = build_clarification_bot_response(intent, confidence)
        return True

    if _apply_intent_routing(
        data,
        intent,
        user_profile,
        user_query=user_query,
        confidence=confidence,
    ):
        _prepend_flow_switch_ack(data)
        return True

    _prepend_flow_switch_ack(data)
    return False


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
            user_profile=user_profile,
        )
        return True

    if intent == "menu_help":
        data["bot_response"] = [
            {
                "type": "text",
                "text": build_main_menu_bot_response()["text"],
                "_compose": "menu_help",
            }
        ]
        return True

    if intent == "complaint":
        _maybe_prompt_flow_switch(
            data, intent, user_profile, user_query, confidence
        )
        user_profile["service_selected"] = ServiceList.COMPLAINT.value
        data["bot_response"] = [build_complaint_flow_bot_response()]
        _prepend_flow_switch_ack(data)
        return True

    service = _CATEGORY_TO_SERVICE.get(intent)
    if service:
        _maybe_prompt_flow_switch(
            data, intent, user_profile, user_query, confidence
        )
        user_profile["service_selected"] = service.value
        return False

    logger.warning(
        "Unknown classifier intent",
        extra={"intent": intent, "phone_number": phone_number},
    )
    data["bot_response"] = [
        {
            "type": "text",
            "text": (
                "Sorry, I didn't catch that — could you say it another way? "
                "You can ask about jewellery, offers, a store, or your order."
            ),
            "_compose": "fallback_unclear",
        }
    ]
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
    structured = extract_structured_fields(normalized)
    return bool(structured.get("pincode") or structured.get("city"))


def _apply_store_pincode_shortcut(data: dict) -> bool:
    """Route bare pincode entry to store lookup while awaiting_store_pincode is set."""
    user_profile = data.get("user_profile", {})
    if not user_profile.get("awaiting_store_pincode"):
        return False
    messages = data.get("messages", {})
    if "text" not in messages:
        return False
    user_query = (messages.get("text", {}) or {}).get("body", "") or ""
    if _store_pincode_escape_intent(user_query):
        return False
    if user_query.strip().lower() in ("cancel", "back"):
        return False
    _store_llm_entities(data, user_profile, {})
    user_profile["service_selected"] = ServiceList.AD_FLOW.value
    data["classified_category"] = "store_info"
    return True


def _should_offer_clarification(data: dict, user_query: str, user_profile: dict) -> bool:
    if user_profile.get("pending_clarification"):
        return False
    if is_unrecognizable_input(user_query):
        return False
    if is_pure_greeting(user_query) or is_greeting_message(user_query):
        return False
    # The LLM extracted a concrete category/material/price → the query is a clear
    # product search, never clarify (esp. low-confidence native-script queries).
    entities = data.get("llm_extracted_entities") or {}
    if (
        entities.get("category")
        or entities.get("material_type")
        or entities.get("min_price") is not None
        or entities.get("max_price") is not None
    ):
        return False
    service = user_profile.get("service_selected")
    if service == ServiceList.PRODUCT_SEARCH.value:
        chat_history = user_profile.get("chat_history", [])
        if chat_history and not _REROUTE_RE.search(user_query):
            if (
                _BROWSE_ACTION_RE.search(user_query)
                or _CATEGORY_WORD_RE.search(user_query)
                or _CONTINUATION_RE.search(user_query)
            ):
                return False
            # FIX 2: price-only refinement in active session is unambiguous —
            # never fire clarification when there is prior category/material context
            if _PRICE_SIGNAL_RE.search(user_query):
                prior = user_profile.get("last_search_filters") or {}
                if prior.get("category") or prior.get("material_type"):
                    return False
    return True


_CATEGORY_TO_SERVICE = {
    "general": ServiceList.GENERAL,
    "greeting": ServiceList.GENERAL,
    "product_search": ServiceList.PRODUCT_SEARCH,
    "product_info": ServiceList.PRODUCT_SEARCH,
    "compare": ServiceList.PRODUCT_SEARCH,
    "offers": ServiceList.OFFERS,
    "pre_order": ServiceList.PRE_ORDER,
    "order_tracking": ServiceList.ORDER_TRACKING,
    "returns_refund": ServiceList.RETURNS_REFUND,
    "complaint": ServiceList.COMPLAINT,
    "store_info": ServiceList.AD_FLOW,
}

_FILTER_SUMMARY_KEYS = (
    "category",
    "material_type",
    "max_price",
    "min_price",
    "title",
)


def _format_shown_products(user_profile: dict) -> str:
    """Numbered list of products currently on the user's screen.

    Lets the LLM resolve references like "the second one", "the gold one",
    "बीच वाला" against what's actually shown — no regex, any language.
    """
    products = user_profile.get("last_search_products") or []
    if not products:
        return ""
    from kisna_chatbot.utils.product_formatter import get_product_display_price

    lines: list[str] = []
    for i, p in enumerate(products[:5], start=1):
        name = p.get("title") or p.get("name")
        if not name:
            continue
        price = get_product_display_price(p)
        price_txt = f" ₹{int(price):,}" if price and price > 0 else ""
        lines.append(f"{i}. {name}{price_txt}")
    if not lines:
        return ""
    return "Products currently shown to the user:\n" + "\n".join(lines)


def _format_active_product_context(user_profile: dict) -> str:
    """One-line product/search context for classifier when screen state matters."""
    last_viewed = user_profile.get("last_viewed_product")
    if last_viewed:
        title = last_viewed.get("title") or last_viewed.get("name") or "a product"
        return f"Active context: user recently viewed {title}."

    filters = user_profile.get("last_search_filters") or {}
    parts: list[str] = []
    for key in _FILTER_SUMMARY_KEYS:
        val = filters.get(key)
        if val is not None and val != "":
            label = key.replace("_", " ")
            parts.append(f"{label} {val}" if key in ("max_price", "min_price") else str(val))
    if parts:
        return f"Active context: user recently searched {', '.join(parts)}."
    return ""


def _build_classifier_system_content(
    user_profile: dict, chat_history_str: str, hint: str | None = None
) -> str:
    system_content = f"Chat history: {chat_history_str}"
    shown = _format_shown_products(user_profile)
    if shown:
        system_content = f"{shown}\n{system_content}"
    active_ctx = _format_active_product_context(user_profile)
    if active_ctx:
        system_content = f"{active_ctx}\n{system_content}"
    if hint:
        system_content = (
            f"{system_content}\nRouting hint (regex heuristic, can be wrong — "
            f"ignore if the message means otherwise): {hint}"
        )
    return system_content


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

    if _is_acknowledgement_message(user_query, profile):
        return {
            "intent": "acknowledgement",
            "confidence": 1.0,
            "entities": {},
            "source": "shortcut",
        }

    override = _programmatic_intent_override(user_query)
    if override:
        intent, confidence = override
        return {
            "intent": intent,
            "confidence": confidence,
            "entities": {},
            "source": "override",
        }

    if profile.get("awaiting_store_pincode") and _PINCODE_ONLY_RE.match(
        user_query.strip()
    ):
        if user_query.strip().lower() not in ("cancel", "back"):
            return {
                "intent": "store_info",
                "confidence": 1.0,
                "entities": {},
                "source": "shortcut",
            }

    if not use_llm:
        return {"intent": "unknown", "confidence": 0.0, "entities": {}, "source": "none"}

    chat_history_str = format_recent_history_str(profile, 8)
    system_content = _build_classifier_system_content(
        profile, chat_history_str, hint=_programmatic_intent_hint(user_query)
    )

    classifier_response = await complete_chat(
        agent=AgentName.CLASSIFIER,
        agent_display_name="Classifier Agent",
        instruction=CONTEXT,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"User Query: {user_query}"},
        ],
        phone_number=data["phone_number"],
        client_id=data["client_id"],
    )
    parsed = _parse_classifier_json(classifier_response)
    intent = parsed["intent"]
    confidence = parsed["confidence"]
    override = _programmatic_intent_override(user_query)
    if override:
        intent, confidence = override
        source = "override"
    else:
        source = "llm"
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": _sanitize_llm_entities(parsed.get("entities") or {}),
        "source": source,
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

        # Indic-script text bypasses every Latin-only regex gate below — the LLM
        # classifier is the only component that can understand it.
        if _INDIC_SCRIPT_RE.search(user_query):
            return True

        if is_greeting_message(user_query):
            return True

        if _REROUTE_RE.search(user_query):
            return True

        if user_profile.get("awaiting_store_pincode"):
            if _store_pincode_escape_intent(user_query):
                return True
            return False

        if user_profile.get("callback_capture_step"):
            if _flow_escape_should_classify(user_query):
                return True
            return False

        # LLM-default policy: the classifier sees every message. A regex may only
        # SKIP the LLM for provably unambiguous continuations — never because it
        # "looks like" an in-session refinement (Latin-only patterns cannot cover
        # multilingual / romanized phrasing and silently bulldoze stale context).
        service = user_profile.get("service_selected")
        if service == ServiceList.AD_FLOW.value and _PINCODE_ONLY_RE.match(
            user_query.strip()
        ):
            # Bare pincode during a store lookup — structured input, nothing to classify.
            return False

        if service == ServiceList.PRODUCT_SEARCH.value:
            stripped = user_query.strip()
            if (
                user_profile.get("chat_history")
                and len(stripped.split()) <= 4
                and _CONTINUATION_RE.search(stripped)
            ):
                # Pure "show more" continuation — the search agent pages the
                # active results; no meaning left for the LLM to extract.
                return False

        return True

    async def process(self, data: dict) -> dict:
        """Process the input data and return the processed data."""
        phone_number = data["phone_number"]
        user_profile = data["user_profile"]
        client_id = data.get("client_id", "kisna")

        if not self.should_run(data):
            if _apply_store_pincode_shortcut(data):
                logger.info(
                    "Store lookup shortcut — routing to ad_flow",
                    extra={"phone_number": phone_number},
                )
                return data
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

                # Script-mirror the stored language to THIS message even on
                # shortcut paths that skip the LLM (greeting, ack, overrides).
                _store_language(user_profile, None, user_query)

                if user_profile.get("pending_clarification"):
                    user_profile["pending_clarification"] = False
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
                        user_profile=user_profile,
                    )
                    logger.info(
                        "Greeting shortcut — welcome text only",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if user_profile.get("awaiting_rating"):
                    rating = _parse_rating_reply(user_query)
                    user_profile.pop("awaiting_rating", None)
                    if rating is not None:
                        logger.info(
                            "User submitted text rating",
                            extra={"phone_number": phone_number, "rating": rating},
                        )
                        data["bot_response"] = [
                            {
                                "type": "text",
                                "text": (
                                    "Thank you for your feedback! "
                                    "We're glad to have helped you."
                                ),
                                "_compose": "acknowledgement",
                            }
                        ]
                        return data
                    # Non-rating message — fall through and treat normally

                if is_menu_request(user_query):
                    _store_llm_entities(data, user_profile, {})
                    data["classified_category"] = "menu_help"
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": build_main_menu_bot_response()["text"],
                            "_compose": "menu_help",
                        }
                    ]
                    logger.info(
                        "Menu request shortcut — sending text help",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if user_profile.get("awaiting_store_pincode"):
                    escape_intent = _store_pincode_escape_intent(user_query)
                    if escape_intent:
                        user_profile["awaiting_store_pincode"] = False
                        extra_entities: dict[str, Any] = {}
                        if user_profile.pop("_price_direction_hint", None):
                            extra_entities["price_direction"] = "higher"
                        _store_llm_entities(data, user_profile, extra_entities)
                        data["classified_category"] = escape_intent
                        data["classifier_confidence"] = 1.0
                        _maybe_prompt_flow_switch(
                            data,
                            escape_intent,
                            user_profile,
                            user_query,
                            confidence=1.0,
                        )
                        if _apply_intent_routing(
                            data,
                            escape_intent,
                            user_profile,
                            user_query=user_query,
                            confidence=1.0,
                        ):
                            _prepend_flow_switch_ack(data)
                            return data
                        user_profile["service_selected"] = (
                            _CATEGORY_TO_SERVICE.get(escape_intent) or ServiceList.GENERAL
                        ).value
                        _prepend_flow_switch_ack(data)
                        return data
                    if user_query.strip().lower() not in ("cancel", "back"):
                        _store_llm_entities(data, user_profile, {})
                        user_profile["service_selected"] = ServiceList.AD_FLOW.value
                        data["classified_category"] = "store_info"
                        logger.info(
                            "Store lookup shortcut — routing to ad_flow",
                            extra={"phone_number": phone_number},
                        )
                        return data

                if _is_acknowledgement_message(user_query, user_profile):
                    _store_llm_entities(data, user_profile, {})
                    data["classified_category"] = "acknowledgement"
                    data["bot_response"] = build_acknowledgement_bot_response()
                    logger.info(
                        "Acknowledgement shortcut",
                        extra={"phone_number": phone_number},
                    )
                    return data

                override = _programmatic_intent_override(user_query)
                if override:
                    intent, confidence = override
                    _store_llm_entities(data, user_profile, {})
                    logger.info(
                        "Programmatic intent override",
                        extra={
                            "phone_number": phone_number,
                            "intent": intent,
                            "confidence": confidence,
                        },
                    )
                    if _route_resolved_intent(
                        data,
                        user_profile,
                        phone_number,
                        user_query,
                        chat_history,
                        intent,
                        confidence,
                    ):
                        await _finalize_classifier_response(data)
                        return data
                    return data

                logger.info(
                    "Request received to classify query",
                    extra={"phone_number": phone_number, "query": user_query},
                )

                chat_history_str = format_recent_history_str(user_profile, 8)
                system_content = _build_classifier_system_content(
                    user_profile,
                    chat_history_str,
                    hint=_programmatic_intent_hint(user_query),
                )

                classifier_response = await complete_chat(
                    agent=AgentName.CLASSIFIER,
                    agent_display_name="Classifier Agent",
                    instruction=CONTEXT,
                    messages=[
                        {
                            "role": "system",
                            "content": system_content,
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
                intent = parsed["intent"] or "general"
                confidence = parsed["confidence"]
                _store_language(user_profile, parsed.get("language"), user_query)
                override = _programmatic_intent_override(user_query)
                if override:
                    intent, confidence = override
                    logger.info(
                        "Post-LLM programmatic override",
                        extra={
                            "phone_number": phone_number,
                            "intent": intent,
                            "llm_intent": parsed["intent"],
                        },
                    )
                sanitized_entities = _sanitize_llm_entities(
                    parsed.get("entities") or {}
                )

                # Second-chance extraction: on native script the classifier's
                # combined task (intent + entities + language) often drops the
                # category/price even when it nails the intent. Two failure modes:
                #  - soft 'general'/'product_info' with no category -> handed to
                #    GeneralAgent, only acknowledged (never searched)
                #  - 'product_search' with NO category AND NO price -> the search
                #    agent asks for a budget the user ALREADY gave ("વીંટી ૧૦ લાખ").
                # The dedicated entity extractor (a focused prompt) is far more
                # reliable on Devanagari/Gujarati, so give it one focused pass.
                _missing_cat = not sanitized_entities.get("category")
                _missing_price = (
                    sanitized_entities.get("min_price") is None
                    and sanitized_entities.get("max_price") is None
                )
                _empty_product_search = (
                    intent == "product_search" and _missing_cat and _missing_price
                )
                if (
                    _missing_cat
                    and intent in ("general", "product_info", "menu_help")
                ) or _empty_product_search:
                    try:
                        from kisna_chatbot.processors.entity_extractor import (
                            extract_entities_with_llm,
                        )

                        second = await extract_entities_with_llm(
                            user_query=user_query,
                            client_id=client_id,
                            phone_number=phone_number,
                        )
                        if second and second.get("category"):
                            for key, val in second.items():
                                if val is not None and not sanitized_entities.get(key):
                                    sanitized_entities[key] = val
                            logger.info(
                                "Second-chance extraction rescued a product query",
                                extra={
                                    "phone_number": phone_number,
                                    "category": second.get("category"),
                                    "llm_intent": intent,
                                },
                            )
                    except Exception:
                        logger.warning(
                            "second-chance entity extraction failed",
                            exc_info=True,
                        )

                _store_llm_entities(data, user_profile, sanitized_entities)

                # Entity-driven product-search guard (language-agnostic): if a
                # jewellery category was extracted (by either pass), the user is
                # shopping — regardless of a low confidence score or a
                # general/product_info label. Trust the extraction and search.
                if sanitized_entities.get("category") and intent in (
                    "general",
                    "product_info",
                    "menu_help",
                    "greeting",
                ):
                    intent = "product_search"
                    confidence = max(confidence, 0.8)

                logger.info(
                    "Classifier intent",
                    extra={
                        "intent": intent,
                        "confidence": confidence,
                        "language": user_profile.get("language"),
                        "entities": data.get("llm_extracted_entities"),
                        "phone_number": phone_number,
                    },
                )

                if _route_resolved_intent(
                    data,
                    user_profile,
                    phone_number,
                    user_query,
                    chat_history,
                    intent,
                    confidence,
                ):
                    await _finalize_classifier_response(data)
                    return data

            return data
        except json.JSONDecodeError as e:
            logger.exception(
                "Classifier returned invalid JSON",
                extra={"exception": e, "phone_number": phone_number},
            )
            _store_llm_entities(data, user_profile, {})
            user_profile["service_selected"] = ""
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "Sorry, I didn't catch that — could you say it another way?"
                    ),
                    "_compose": "fallback_unclear",
                }
            ]
            return data
        except Exception as e:
            logger.exception(
                "Exception occured while running classifier.",
                extra={"exception": e, "phone_number": phone_number},
            )
            _store_llm_entities(data, user_profile, {})
            user_profile["service_selected"] = ""
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "Sorry, I didn't catch that — could you say it another way?"
                    ),
                    "_compose": "fallback_unclear",
                }
            ]
            return data
