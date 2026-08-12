import hashlib
import json
import re
from typing import Any
from zoneinfo import ZoneInfo

from kisna_chatbot.ai import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.models.service_list import ServiceList
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.ad_flow_agent import _PINCODE_ONLY_RE
from kisna_chatbot.processors.entity_extractor import (
    extract_entities,
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
from kisna_chatbot.processors.shopping_wizard import (
    ANY_SLOT,
    WIZARD_CARRYOVER_KEYS as _WIZARD_CARRYOVER_KEYS,
    is_fulfillment_slot_answer,
)
from kisna_chatbot.processors.support_handler import build_expert_support_bot_response
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier_intent
from kisna_chatbot.utils.format_chathistory import format_recent_history_str
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.reply_composer import sanitize_classifier_language
from kisna_chatbot.utils.session_state import (
    clear_all_sticky_states,
    clear_transient_for_service_change,
    maybe_expire_session,
    reset_session_on_fresh_start,
    reset_transient_state,
)

india_tz = ZoneInfo("Asia/Kolkata")

CONTEXT = kisna_classifier_intent

CLARIFICATION_CONFIDENCE_THRESHOLD = 0.45
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


def _reset_session_on_fresh_start(user_profile: dict) -> None:
    """Greeting / menu starts a fresh turn — wipe sticky waits and search context."""
    reset_session_on_fresh_start(user_profile)


# Back-compat alias used by older call sites / tests.
_clear_state_on_greeting = _reset_session_on_fresh_start


_REROUTE_RE = re.compile(
    r"\b("
    r"menu|back|cancel|hi|hello|namaste|"
    r"view\s+offers|show\s+offers|any\s+offers|koi\s+offer|offers?\s*\?|"
    r"find\s+(a\s+)?store|store\s+locator|nearest\s+store|nearest\s+shop|showroom|"
    r"store\s+in|have\s+(a\s+)?store|stores?\s+in|outlet|"
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

# BESPOKE WORK ONLY — a piece Kisna cannot serve from the catalogue: made to
# the user's own design, or personalised (engraving / initials / a name).
#
# MADE-TO-ORDER IS NOT BESPOKE. MTO is a first-class catalogue filter sent to
# the Clara search API: the shopping wizard offers "Made to order" as a button,
# _FULFILLMENT_TITLE_MAP maps the phrase to "mto", and the entity extractor
# does the same. This regex used to contain "made to order" AND a bare
# "custom|customize|customise" — the exact strings the wizard accepts as an
# availability answer. Because it feeds _programmatic_intent_override (a hard
# 0.95 verdict that beats the LLM), typing the wizard's own button label handed
# the user to a design expert instead of filtering the catalogue.
#
# So: bare "custom" is not enough. A bespoke verdict needs the word attached to
# a jewellery noun or a design/personalisation request.
_CUSTOM_JEWELLERY_RE = re.compile(
    r"\b(bespoke|personalis\w*|personaliz\w*|engrav\w*|"
    r"design my own|apni design|custom design|"
    r"naam likhwana|initials|special order|"
    r"custom(?:i[sz]ed?)?\s+"
    r"(?:ring|jewell?ery|jewelry|necklace|earring\w*|bracelet|bangle|"
    r"pendant|chain|mangalsutra|piece|design|order)"
    r")\b",
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
    r"baat\s+karni\s+hai|kisi\s+se\s+baat|connect\s+me|"
    r"need\s+urgent\s+support|"
    r"(?:talk|speak|connect)\s+to\s+(?:an?\s+)?(?:agent|human|expert|support)|"
    r"baat\s+karao|agent\s+chahiye|human\s+chahiye"
    r")\b",
    re.I,
)

_CALLBACK_RE = re.compile(
    r"\b("
    r"call\s*me\s*back|call\s*back|callback|request\s+(?:a\s+)?callback|"
    r"please\s+call\s+me|phone\s+karo|mujhe\s+call|call\s+karwao|call\s+karo|"
    r"callback\s+form|schedule\s+(?:a\s+)?callback"
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

_DIGITAL_GOLD_RE = re.compile(
    r"\b("
    r"digital\s+gold|safegold|safe\s+gold|buy\s+gold\s+online|"
    r"gold\s+sip|digital\s+sona"
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

# Physical retail location — NOT product catalog / "do you have this ring".
# Keep distinct from product availability ("available in store", "in-store pickup").
_STORE_LOOKUP_RE = re.compile(
    r"\b("
    r"nearest\s+(?:store|shop|showroom|outlet)|"
    r"(?:store|shop|showroom|outlet)\s+(?:near|locator)|"
    r"store\s+locator|"
    r"find\s+(?:a\s+)?(?:store|shop|showroom|outlet)|"
    r"kisna\s+(?:store|showroom|outlet|shop)|"
    r"showroom|outlet|"
    # "store/shop/showroom in|at Mumbai", "stores in Delhi"
    r"(?:stores?|shops?|showrooms?|outlets?)\s+(?:in|at|near)\b|"
    # "have a store", "any Kisna store", "do you have a store"
    r"(?:have|has|got|any)\s+(?:a\s+|an\s+|any\s+)?(?:kisna\s+)?"
    r"(?:store|shop|showroom|outlet)s?\b|"
    r"(?:store|shop|showroom)\s+(?:location|address|directions?)\b|"
    r"(?:location|address|directions?)\s+(?:of\s+)?(?:the\s+|your\s+|kisna\s+)?"
    r"(?:store|shop|showroom|outlet)s?\b|"
    r"where\s+(?:is|are)\s+(?:your\s+|the\s+|a\s+|kisna\s+)?"
    r"(?:store|shop|showroom|outlet)s?\b|"
    # Hinglish / Hindi-Latin
    r"(?:store|showroom|outlet|shop)\s+(?:kahan|kahaan|hai|batao|bataye)\b|"
    r"(?:mein|me)\s+(?:store|showroom|outlet|shop)\b|"
    r"(?:store|showroom|outlet|shop)\s+(?:mein|me)\b"
    r")",
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

# Unambiguous "page the same results" only — topic-change phrases must hit the LLM.
_PAGINATION_ONLY_RE = re.compile(
    r"^\s*("
    r"show\s+more|more|next|aur\s+dikhao|next\s+3|show\s+next|and\s+more|"
    r"aur\s+options?"
    r")\s*[!.]*\s*$",
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


# A NAMED rival (or an explicit "other brands" phrasing) is unambiguous — safe
# to decide without the LLM.
_COMPETITOR_BRAND_RE = re.compile(
    r"\b(tanishq|kalyan|malabar|caratlane|reliance\s+jewels|bluestone|"
    r"joyalukkas|pc\s+jeweller|pcj|bhima|grt|tbz|senco|png|"
    r"other\s+brands?|local\s+jeweler|local\s+jeweller|why\s+buy\s+from)\b",
    re.I,
)

# "better than" / "why choose" alone are NOT competitor signals — they are how
# people compare the products we just showed them ("is this better than the
# second one?"). Kept only as a soft hint so the LLM can pick compare instead.
_COMPETITOR_WEAK_RE = re.compile(
    r"\b(why\s+choose|better\s+than)\b",
    re.I,
)

_COMPETITOR_RE = re.compile(
    f"{_COMPETITOR_BRAND_RE.pattern}|{_COMPETITOR_WEAK_RE.pattern}",
    re.I,
)


def _is_competitor_comparison(text: str) -> bool:
    """Named-rival comparison only — see _COMPETITOR_WEAK_RE for why."""
    return bool(_COMPETITOR_BRAND_RE.search((text or "").strip()))


def _is_custom_jewellery_query(text: str) -> bool:
    """True only for bespoke work — never for an availability answer.

    Second layer of the same rule as _CUSTOM_JEWELLERY_RE: a message that IS
    one of the wizard's availability button labels ("made to order", "custom")
    is a catalogue filter, whatever else the regex might read into it.
    """
    normalized = (text or "").strip()
    if not normalized:
        return False
    if is_fulfillment_slot_answer(normalized):
        return False
    return bool(_CUSTOM_JEWELLERY_RE.search(normalized))


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
    """Hard override only for cases the LLM must not decide alone.

    Live-agent / callback / video / gold-rate are LLM-primary (prompt + soft
    hints). Sticky waits may use regex only to *leave* the wait, then the LLM
    classifies.
    """
    normalized = (text or "").strip()
    if not normalized:
        return None
    if _is_competitor_comparison(normalized):
        return ("general", 0.95)
    if _is_custom_jewellery_query(normalized):
        return ("human_handoff", 0.95)
    if _DIGITAL_GOLD_RE.search(normalized) or _SCHEME_RE.search(normalized):
        return ("general", 0.9)
    # Policy action/info regexes are HINTS only (see _programmatic_intent_hint).
    return None


def _programmatic_intent_fallback(text: str) -> tuple[str, float] | None:
    """Unambiguous support intents when the LLM is down (rate-limit / outage).

    Normal path stays LLM-primary. This only runs after a classifier failure so
    "Callback" / "call me back" do not trap the user in "didn't catch that".
    """
    normalized = (text or "").strip()
    if not normalized:
        return None
    if _HUMAN_HANDOFF_RE.search(normalized):
        return ("human_handoff", 0.9)
    if _CALLBACK_RE.search(normalized):
        return ("callback", 0.9)
    if _VIDEO_CALL_RE.search(normalized):
        return ("video_call", 0.9)
    if _GOLD_RATE_RE.search(normalized):
        return ("gold_rate", 0.9)
    if _STORE_LOOKUP_RE.search(normalized) and not (
        _CATEGORY_WORD_RE.search(normalized) and _BROWSE_ACTION_RE.search(normalized)
    ):
        return ("store_info", 0.9)
    return None


def _programmatic_intent_hint(text: str) -> str | None:
    """Soft routing hint passed into the classifier prompt — never a verdict."""
    normalized = (text or "").strip()
    if not normalized:
        return None
    if _COMPETITOR_WEAK_RE.search(normalized) and not _COMPETITOR_BRAND_RE.search(
        normalized
    ):
        return (
            "message contains 'better than' / 'why choose' with NO rival brand "
            "named — if products are shown this is almost certainly a comparison "
            "of THOSE items (intent compare), not a competitor question"
        )
    if _HUMAN_HANDOFF_RE.search(normalized):
        return (
            "heuristic suggests an explicit live-agent / human request "
            "(intent human_handoff, confidence ≥0.9) — never general or unclear"
        )
    if _CALLBACK_RE.search(normalized):
        return (
            "heuristic suggests a phone callback request (intent callback) — "
            "NOT live chat handoff, NOT video"
        )
    if _VIDEO_CALL_RE.search(normalized):
        return (
            "heuristic suggests video call / video consultation "
            "(intent video_call)"
        )
    if _GOLD_RATE_RE.search(normalized):
        return (
            "heuristic suggests today's gold metal rate (intent gold_rate) — "
            "NOT a jewellery product price"
        )
    if _STORE_LOOKUP_RE.search(normalized) and not (
        _CATEGORY_WORD_RE.search(normalized) and _BROWSE_ACTION_RE.search(normalized)
    ):
        return (
            "heuristic suggests a PHYSICAL store/showroom/outlet location lookup "
            "(intent store_info, confidence ≥0.9) — NOT product_search. "
            "'do you have a store in <city>' is about a PLACE, not jewellery inventory"
        )
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
    if user_profile.get("shopping_wizard_active"):
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
    # Bare jewellery type ("Ring", "earrings") — never a pincode/city.
    if _CATEGORY_WORD_RE.search(normalized) and not _PINCODE_ONLY_RE.match(normalized):
        return True
    structured = extract_structured_fields(normalized)
    if (structured.get("min_price") or structured.get("max_price")) and (
        _CATEGORY_WORD_RE.search(normalized) or _MATERIAL_WORD_RE.search(normalized)
    ):
        return True
    return False


def _sticky_wait_escape_intent(user_query: str) -> str | None:
    """Intent when user should leave store/wizard/callback wait for another flow."""
    normalized = (user_query or "").strip()
    if not normalized:
        return None
    # Bespoke asks are a handoff, never a catalog filter — check before the
    # browse escape so "custom ring banwana hai" is not read as a ring search,
    # and before everything else so "custom design chahiye" (no category word)
    # is not swallowed by the wizard as a fulfillment answer.
    if _is_custom_jewellery_query(normalized):
        return "human_handoff"
    if _looks_like_browse_escape(normalized):
        return "product_search"
    if _OFFERS_INTENT_RE.search(normalized) and not _CATEGORY_WORD_RE.search(normalized):
        return "offers"
    if _STORE_LOOKUP_RE.search(normalized):
        return "store_info"
    if _ORDER_TRACKING_RE.search(normalized) or _ORDER_DELIVERY_RE.search(normalized):
        return "order_tracking"
    if _is_policy_action_query(normalized):
        return "returns_refund"
    if _COMPLAINT_RE.search(normalized) and not _CATEGORY_WORD_RE.search(normalized):
        return "complaint"
    if _HUMAN_HANDOFF_RE.search(normalized):
        return "human_handoff"
    if _CALLBACK_RE.search(normalized):
        return "callback"
    if _VIDEO_CALL_RE.search(normalized):
        return "video_call"
    if _GOLD_RATE_RE.search(normalized):
        return "gold_rate"
    if _DIGITAL_GOLD_RE.search(normalized) or _SCHEME_RE.search(normalized):
        return "general"
    if _looks_like_faq_query(normalized):
        return "general"
    return None


def _store_pincode_escape_intent(user_query: str) -> str | None:
    """Back-compat alias — store wait uses the shared sticky-wait escape."""
    return _sticky_wait_escape_intent(user_query)


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
# "any" is the user REFUSING an availability ("ready to ship nahi chahiye") or
# stating no preference. It must survive sanitization: both prompts are told to
# emit it and both consumers test for it (the search path converts it to None
# before querying Clara, the recap-correction path reads it as a real change).
# Dropping it here silently turned every refusal into "no signal", which left
# the correction handler with only the Latin-only regex.
_LLM_ENTITY_FULFILLMENTS = frozenset({"ready", "mto", "any"})
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
        _GENDER_ALIASES = {
            "female": "women",
            "woman": "women",
            "ladies": "women",
            "lady": "women",
            "male": "men",
            "man": "men",
            "gents": "men",
            "gent": "men",
            "kid": "kids",
            "child": "kids",
            "children": "kids",
            "baby": "kids",
        }
        gender = _GENDER_ALIASES.get(gender, gender)
        gender = gender if gender in _LLM_ENTITY_GENDERS else None
    else:
        gender = None
    out["gender"] = gender

    fulfillment = _coerce_null(raw.get("fulfillment"))
    if isinstance(fulfillment, str):
        fulfillment = fulfillment.strip().lower()
        # Accept common aliases the model may emit.
        if fulfillment in ("ready_to_ship", "ready-to-ship", "rts"):
            fulfillment = "ready"
        elif fulfillment in (
            "made_to_order",
            "made-to-order",
            "make_to_order",
            "custom",
        ):
            fulfillment = "mto"
        fulfillment = (
            fulfillment if fulfillment in _LLM_ENTITY_FULFILLMENTS else None
        )
    else:
        fulfillment = None
    out["fulfillment"] = fulfillment

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


# ── Context-free extraction stash ──────────────────────────────────────────
#
# The classifier runs one context-free entity extraction per turn (see the
# canonical extraction in process()). The search agent needs exactly the same
# thing, so it reads this instead of extracting a second time — otherwise a
# search turn costs three LLM calls: classifier + extractor + extractor.
#
# Keyed to the CURRENT message. A stash whose key does not match the message
# being searched is IGNORED, not used: a miss costs one extra call, whereas a
# stale hit would be a context-bleed bug of exactly the kind this whole
# refactor removes. Fails open in every failure mode.
_ENTITY_STASH_KEY = "_context_free_entities"

# Intents whose turn can end in a catalogue search, and therefore need entities.
# Everything else (store_info, order_tracking, returns_refund, complaint,
# callback, video_call, gold_rate, repair) needs none, and skipping the call
# there is where the saving comes from.
_ENTITY_EXTRACTION_INTENTS = frozenset(
    {
        "product_search",
        "product_info",
        "compare",
        "general",
        "menu_help",
        "greeting",
    }
)

# Fields that make an extraction pass unnecessary — a search filter is already
# present for this message.
_SEARCH_ENTITY_FIELDS = (
    "category",
    "material_type",
    "min_price",
    "max_price",
    "collection",
    "title",
)


def _has_search_entities(entities: dict | None) -> bool:
    return any((entities or {}).get(field) is not None for field in _SEARCH_ENTITY_FIELDS)


def _message_key(message: str | None) -> str:
    return hashlib.sha256((message or "").strip().encode("utf-8")).hexdigest()


def stash_context_free_entities(
    data: dict, message: str | None, entities: dict | None
) -> None:
    data[_ENTITY_STASH_KEY] = {
        "message_key": _message_key(message),
        "entities": dict(entities or {}),
    }


def read_context_free_entities(data: dict, message: str | None) -> dict | None:
    """The extraction for THIS message, or None to extract normally."""
    stash = data.get(_ENTITY_STASH_KEY)
    if not isinstance(stash, dict):
        return None
    if stash.get("message_key") != _message_key(message):
        return None
    entities = stash.get("entities")
    return dict(entities) if isinstance(entities, dict) else None


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


_LANGUAGE_NAME_TO_CODE = {
    "english": "en",
    "angrezi": "en",
    "hindi": "hi",
    "gujarati": "gu",
    "gujrati": "gu",
    "marathi": "mr",
    "tamil": "ta",
    "telugu": "te",
    "bengali": "bn",
    "kannada": "kn",
    "malayalam": "ml",
    "punjabi": "pa",
}

# "talk to me in English only please", "sirf English mein baat karo",
# "please reply in Hindi", "English me hi baat karo".
_LANG_NAMES = (
    r"english|angrezi|hindi|gujarati|gujrati|marathi|tamil|telugu"
    r"|bengali|kannada|malayalam|punjabi"
)
_LANGUAGE_OVERRIDE_RE = re.compile(
    # "…in English please", "reply in Hindi"
    rf"\b(?:in|mein|me|ma)\s+({_LANG_NAMES})\b"
    # "sirf English…", "only Hindi…"
    rf"|\b(?:only|sirf|just)\b[^.!?]{{0,20}}?\b({_LANG_NAMES})\b"
    # "English me hi baat karo", "Hindi only"
    rf"|\b({_LANG_NAMES})\b\s*(?:mein|me|men|ma)?\s*\b(?:hi|only)\b"
    # "reply/talk/speak in English", "English mein baat karo"
    rf"|\b(?:reply|talk|speak|baat|bol|likh|write)\b[^.!?]{{0,30}}?"
    rf"\b({_LANG_NAMES})\b",
    re.I,
)


def detect_language_override(text: str) -> str | None:
    """Language code when the user explicitly asks to be replied to in one."""
    normalized = (text or "").strip()
    if not normalized:
        return None
    match = _LANGUAGE_OVERRIDE_RE.search(normalized)
    if not match:
        return None
    for group in match.groups():
        if group and group.lower() in _LANGUAGE_NAME_TO_CODE:
            return _LANGUAGE_NAME_TO_CODE[group.lower()]
    return None


def _store_language(
    user_profile: dict, language: str | None, user_text: str = ""
) -> None:
    """Per-message language state — the LAST message always wins.

    Without a fresh LLM label (shortcut paths), still correct the stored
    language's script to match the current message.

    An explicit request ("talk to me in English only please") outranks both:
    the user told us what they want and detection must stop second-guessing
    them. Cleared on greeting / session expiry with the other transient state.
    """
    requested = detect_language_override(user_text)
    if requested:
        user_profile["language_override"] = requested
    override = user_profile.get("language_override")
    if override:
        user_profile["language"] = override
        return
    if language:
        user_profile["language"] = resolve_reply_language(language, user_text)
        return
    stored = user_profile.get("language")
    if stored and user_text:
        user_profile["language"] = resolve_reply_language(stored, user_text)


def _flow_escape_should_classify(user_query: str) -> bool:
    return _sticky_wait_escape_intent(user_query) is not None


# Intents that always mean "the user left the sticky flow". Anything else
# (product_search/product_info/general) is treated as an answer to the flow's
# own question when a wizard is collecting slots.
_STICKY_ESCAPE_INTENTS = frozenset(
    {
        "human_handoff",
        "callback",
        "video_call",
        "gold_rate",
        "complaint",
        "order_tracking",
        "returns_refund",
        "offers",
        "store_info",
        "menu_help",
        "greeting",
        "repair",
    }
)


def _llm_intent_escapes_sticky(user_profile: dict, intent: str) -> bool:
    """Decide from the LLM verdict whether a sticky wait should be dropped.

    Used for native-script messages, where the Latin escape regexes see nothing
    and would otherwise trap the user in the wizard / pincode / callback wait.
    Each wait keeps the answers it is actually waiting for and lets the rest go.
    """
    if user_profile.get("shopping_wizard_active"):
        # The wizard is collecting slots — a shopping reply is its answer.
        return intent in _STICKY_ESCAPE_INTENTS

    if user_profile.get("awaiting_store_pincode"):
        # Waiting on a pincode / city; anything else is a new intent.
        return intent != "store_info"

    if user_profile.get("callback_capture_step"):
        # Waiting on a name / mobile — free text (names classify as "general"
        # with low confidence) must stay in the capture. Only an explicit jump
        # to another flow escapes; callback/video_call mean "already here".
        return intent in (_STICKY_ESCAPE_INTENTS - {"callback", "video_call"})

    return True


def _stash_wizard_carryover(data: dict, user_profile: dict) -> None:
    """Hand button-tapped wizard slots to the re-seeded funnel for THIS turn.

    After tapping Female + Gold, typing "rings under 30k" cleared the wizard and
    re-asked both questions: the message names a category, so
    ``merge_search_entities`` treats it as a fresh search and inherits nothing.
    Stashing on ``data`` (per-turn, never persisted) keeps the answers without
    creating another sticky flag to garbage-collect.
    """
    collected = user_profile.get("shopping_wizard_data")
    if not isinstance(collected, dict):
        return
    carryover = {
        key: collected[key]
        for key in _WIZARD_CARRYOVER_KEYS
        if collected.get(key) is not None and collected[key] != ANY_SLOT
    }
    if carryover:
        data["_wizard_carryover"] = carryover


def _wizard_parses_offline(user_profile: dict, text: str) -> bool:
    """True when the wizard can read this answer without an LLM call.

    Keeps native-script slot answers ("डाइमंड", "સોનું") off the LLM path: they
    are handled by the wizard's own Indic title maps, and routing them through
    the classifier would make them fail closed on any LLM outage.
    """
    from kisna_chatbot.processors.shopping_wizard import (
        _parse_text_for_step,
        get_next_step,
    )

    step = user_profile.get("shopping_wizard_step") or get_next_step(
        user_profile.get("shopping_wizard_data") or {}
    )
    if not step or step == "complete":
        return False
    try:
        return _parse_text_for_step(step, text) is not None
    except Exception:  # never let a parser slip block the escape path
        return False


def _has_sticky_wait(user_profile: dict) -> bool:
    return bool(
        user_profile.get("awaiting_store_pincode")
        or user_profile.get("shopping_wizard_active")
        or user_profile.get("callback_capture_step")
    )


def _clear_sticky_waits(user_profile: dict) -> None:
    """Drop store / wizard / callback input waits without wiping search filters."""
    clear_all_sticky_states(user_profile)
    for key in ("callback_capture_step", "callback_draft"):
        user_profile.pop(key, None)


# Intents that always mean the user left the flow, whatever question was
# pending. Used by the regex fast path; the gate below covers everything else.
_UNIVERSAL_ESCAPE_INTENTS = frozenset(
    {
        "human_handoff",
        "callback",
        "video_call",
        "complaint",
        "greeting",
        "menu_help",
    }
)

# The question each sticky wait is holding the turn for. Given to the gate so
# it judges "does this answer THAT?" rather than guessing an intent.
_PENDING_QUESTION_BY_STEP = {
    "category": "What type of jewellery are you looking for? (rings, earrings, …)",
    "gender": "Who is it for? (women, men, kids)",
    "material": "What material? (gold, diamond, gemstone)",
    "budget": "What is your budget, in rupees?",
    "fulfillment": "Ready to ship, or made to order?",
}
_STORE_PINCODE_QUESTION = "What is your 6-digit pincode, to find the nearest store?"
_CALLBACK_QUESTION = "Your name and phone number, for the callback."


def _answers_store_pincode_question(text: str) -> bool:
    """A store wait accepts a pincode or a city — nothing else.

    Decided in code, not by an LLM: the answer format is machine-checkable and
    language-independent (digits are digits), so asking a model whether "Ring"
    is a pincode is both slower and less reliable. It said "yes".
    """
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _PINCODE_ONLY_RE.match(normalized):
        return True
    structured = extract_structured_fields(normalized)
    return bool(structured.get("pincode") or structured.get("city"))


def _pending_question(user_profile: dict) -> str | None:
    """The question the active sticky wait is holding the turn for."""
    if user_profile.get("shopping_wizard_active"):
        step = user_profile.get("shopping_wizard_step")
        if not step or step == "complete":
            from kisna_chatbot.processors.shopping_wizard import get_next_step

            step = get_next_step(user_profile.get("shopping_wizard_data") or {})
        return _PENDING_QUESTION_BY_STEP.get(step or "")
    if user_profile.get("awaiting_store_pincode"):
        return _STORE_PINCODE_QUESTION
    if user_profile.get("callback_capture_step"):
        return _CALLBACK_QUESTION
    return None


# Deliberately tiny and separate from the main classifier prompt: this is a
# gate, not a classification. It answers ONE question — did the user answer us,
# or start something else — so it covers every intent, not a fixed list. An
# intent list is what made the regex fragile: anything unlisted got swallowed.
_QUICK_ESCAPE_PROMPT = """A jewellery shop's WhatsApp bot asked the user a question and is
waiting for the answer.

THE PENDING QUESTION:
{question}

Decide what the user's next message is doing. Reply with exactly one word:

answer       - it responds to the pending question (including "any", "you
               decide", "doesn't matter", "skip", a bare number, a bare
               material or category word, or an answer in any language/script)
new_request  - it is about something else: a shop/store location, an order,
               a return or refund, a complaint, an offer or discount, the gold
               rate, a policy or brand question, asking for a person, a
               callback or a video call, a greeting, the menu, or a different
               product to the one being narrowed down

If it could be either, prefer "answer" — the user is mid-conversation.
Reply with the single word only. No punctuation, no explanation."""


async def _quick_escape_classify(
    user_message: str,
    pending_question: str,
    *,
    client_id: str = "kisna",
    phone_number: str | None = None,
) -> bool | None:
    """Did the user answer our question, or start something else?

    True  — a new request (leave the flow)
    False — an answer (flow keeps the turn)
    None  — could not decide; the caller falls back to the regex verdict, i.e.
            exactly the behaviour that shipped before this gate existed. The
            gate must never make an outage WORSE than no gate at all.
    """
    try:
        raw = await complete_chat(
            agent=AgentName.CLASSIFIER,
            agent_display_name="Escape Gate",
            instruction=_QUICK_ESCAPE_PROMPT.format(question=pending_question),
            messages=[{"role": "user", "content": user_message}],
            max_output_tokens=8,
            phone_number=phone_number,
            client_id=client_id,
        )
    except Exception:
        logger.warning(
            "Escape gate unavailable — falling back to regex escape",
            extra={"phone_number": phone_number},
            exc_info=True,
        )
        return None
    verdict = (raw or "").strip().strip(".\"'").lower()
    if verdict.startswith("new_request"):
        return True
    if verdict.startswith("answer"):
        return False
    logger.warning(
        "Escape gate returned an unusable verdict — falling back to regex",
        extra={"phone_number": phone_number, "verdict": verdict[:40]},
    )
    return None


def _release_sticky_wait(
    data: dict, user_profile: dict, escape_intent: str, user_message: str
) -> None:
    """Leave the flow, preserving everything the turn still needs.

    Mirrors the long-standing regex escape path: button-tapped wizard slots are
    stashed before the funnel is torn down (otherwise the re-seeded search
    re-asks questions the user already answered), and a product-search escape
    keeps the regex entities so the search has something to run with even if
    the classifier LLM then fails.
    """
    if user_profile.get("shopping_wizard_active"):
        _stash_wizard_carryover(data, user_profile)

    extra_entities: dict[str, Any] = {}
    if user_profile.pop("_price_direction_hint", None):
        extra_entities["price_direction"] = "higher"

    _clear_sticky_waits(user_profile)

    if escape_intent == "product_search":
        extracted = extract_entities(user_message)
        for key in (
            "category",
            "material_type",
            "min_price",
            "max_price",
            "metal_colour",
        ):
            if extracted.get(key) is not None:
                extra_entities[key] = extracted[key]
    if extra_entities:
        _store_llm_entities(data, user_profile, extra_entities)


async def _check_universal_escape(
    data: dict,
    user_profile: dict,
    user_message: str,
    *,
    client_id: str = "kisna",
    phone_number: str | None = None,
) -> str | None:
    """Release a sticky wait when the message is not an answer to it.

    Runs BEFORE any wizard / store-wait check. Its ONLY job is to release the
    wait so the message reaches the classifier — it never decides the intent.
    Intent stays LLM-primary: routing a regex verdict directly is what used to
    send callback / handoff turns through _apply_intent_routing into
    "samajh nahi aaya".

    Returns a provisional intent (for logging and the LLM-failure fallback),
    or None when the flow keeps the turn.
    """
    normalized = (user_message or "").strip()
    if not normalized or not _has_sticky_wait(user_profile):
        return None

    override = _programmatic_intent_override(normalized)
    regex_hint = override[0] if override else _sticky_wait_escape_intent(normalized)

    # 1. Free path, and ONLY for intents that can never be a slot answer.
    #    "connect me to an agent" is never the answer to "what's your budget?",
    #    so a regex hit is safe to act on without a call.
    if regex_hint in _UNIVERSAL_ESCAPE_INTENTS:
        _release_sticky_wait(data, user_profile, regex_hint, normalized)
        return regex_hint

    # 2. A store wait has a machine-checkable answer (pincode or city), so it
    #    is decided in code — no LLM, no language dependence, no ambiguity.
    if user_profile.get("awaiting_store_pincode") and not user_profile.get(
        "shopping_wizard_active"
    ):
        if _answers_store_pincode_question(normalized):
            return None
        _release_sticky_wait(
            data, user_profile, regex_hint or "unknown", normalized
        )
        return regex_hint or "unknown"

    # 3. Free-text flows go to the gate — including messages the regex DID
    #    match. The regex cannot be trusted to tell an escape from an answer:
    #    at the category step "ring" is the answer, yet _looks_like_browse_escape
    #    reads it as a new product search and tears the funnel down. And it is
    #    Latin-only, so it is silent for every native-script and romanized
    #    regional message — the languages this bot exists to serve. The gate is
    #    script-agnostic and judges against the question we actually asked.
    question = _pending_question(user_profile)
    if not question:
        # No question to judge against (e.g. wizard already complete) — fall
        # back to the regex verdict rather than guessing.
        if regex_hint:
            _release_sticky_wait(data, user_profile, regex_hint, normalized)
        return regex_hint

    decision = await _quick_escape_classify(
        normalized,
        question,
        client_id=client_id,
        phone_number=phone_number,
    )
    if decision is None:
        # Gate unavailable — behave exactly as we did before it existed.
        if regex_hint:
            _release_sticky_wait(data, user_profile, regex_hint, normalized)
        return regex_hint
    if decision:
        _release_sticky_wait(
            data, user_profile, regex_hint or "unknown", normalized
        )
        logger.info(
            "Escape gate — message is a new request, sticky waits cleared",
            extra={
                "phone_number": phone_number,
                "pending_question": question,
                "regex_hint": regex_hint,
            },
        )
        # The full classifier decides where the user actually went;
        # _maybe_prompt_flow_switch adds the one-line switch acknowledgement.
        # regex_hint (if any) is only a fallback for an LLM outage.
        return regex_hint or "unknown"
    return None


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
    """Design-expert handoff, respecting support hours.

    Delegates to the shared support handler so an out-of-hours request gets a
    callback slot instead of a promise nobody is awake to keep. The bespoke
    opener is prepended and tagged so it reaches the user in their language.
    """
    responses = build_expert_support_bot_response(phone_number, user_profile)
    data["bot_response"] = [
        {
            "type": "text",
            "text": _CUSTOM_JEWELLERY_HANDOFF_MESSAGE,
            "_compose": "custom_jewellery_handoff",
        },
        *responses,
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
            "callback": "Callback request form",
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
        _clear_state_on_greeting(user_profile)
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

    if intent == "callback":
        from kisna_chatbot.config.gupshup import get_callback_flow_id
        from kisna_chatbot.processors.service_list import (
            _start_callback_text_capture,
            build_callback_flow_bot_response,
        )

        user_profile["service_selected"] = ServiceList.CALLBACK.value
        preamble = {
            "type": "text",
            "text": (
                "Sure! Please fill in your details below and we'll call you back."
            ),
            "_compose": "callback_preamble",
        }
        if get_callback_flow_id():
            data["bot_response"] = [preamble, build_callback_flow_bot_response()]
        else:
            data["bot_response"] = [preamble] + _start_callback_text_capture(
                user_profile, request_type="callback"
            )
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
        and intent
        not in (
            "human_handoff",
            "callback",
            "video_call",
            "gold_rate",
            "repair",
        )
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
        _clear_state_on_greeting(user_profile)
        data["classified_category"] = "greeting"
        data["bot_response"] = build_greeting_welcome_bot_responses(
            phone_number=phone_number,
            chat_history=chat_history,
            user_profile=user_profile,
        )
        return True

    if intent == "menu_help":
        _reset_session_on_fresh_start(user_profile)
        data["bot_response"] = [
            {
                "type": "text",
                "text": build_main_menu_bot_response()["text"],
                "_compose": "menu_help",
            }
        ]
        return True

    if intent == "general" and (
        _DIGITAL_GOLD_RE.search(user_query or "") or data.get("_digital_gold_cta")
    ):
        data["_digital_gold_cta"] = True

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
    # Active shopping wizard owns the turn (budget / fulfillment answers).
    if user_profile.get("shopping_wizard_active"):
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
    """One-line search-state signal for the classifier.

    NEVER echoes the active filter VALUES (category/material/price). That
    echo was answer-shaped — after one wrong search, "user recently searched
    ring, diamond, max price 10000" sat as the first context line and the
    model copied it into every subsequent extraction, locking the wrong
    filters in forever. The classifier only needs to know a search/product
    context EXISTS (for intent on short follow-ups); the actual carry-over
    of filters is done deterministically by the merge code.
    """
    last_viewed = user_profile.get("last_viewed_product")
    if last_viewed:
        title = last_viewed.get("title") or last_viewed.get("name") or "a product"
        return f"Active context: user recently viewed {title}."

    if user_profile.get("last_search_filters"):
        return (
            "Active context: the user has an active jewellery search — short "
            "refinements (a bare budget, 'under 20k', 'gold mein', 'show more') "
            "continue it."
        )
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
    entities = _sanitize_llm_entities(parsed.get("entities") or {})
    if (
        source == "llm"
        and _STORE_LOOKUP_RE.search(user_query)
        and not entities.get("category")
        and not (
            _CATEGORY_WORD_RE.search(user_query)
            and _BROWSE_ACTION_RE.search(user_query)
        )
        and intent
        in (
            "product_search",
            "product_info",
            "general",
            "menu_help",
            "greeting",
        )
    ):
        intent = "store_info"
        confidence = max(confidence, 0.9)
        source = "store_guard"
    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
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

        if is_greeting_message(user_query):
            return True

        if _REROUTE_RE.search(user_query):
            return True

        # Sticky waits own the turn (including Indic slot answers like "डाइमंड")
        # unless the user is clearly escaping to another flow.
        #
        # Native script must reach the LLM: every escape regex below is
        # Latin-only, so "मुझे एजेंट से बात करनी है" mid-wizard matched nothing
        # and the funnel re-asked the same question forever. The LLM decides
        # escape-vs-slot-answer in process() (_llm_intent_escapes_sticky).
        has_indic = bool(_INDIC_SCRIPT_RE.search(user_query))

        if user_profile.get("shopping_wizard_active"):
            if _sticky_wait_escape_intent(user_query):
                return True
            if is_greeting_message(user_query) or is_menu_request(user_query):
                return True
            if has_indic and not _wizard_parses_offline(user_profile, user_query):
                # Native script the wizard cannot read — only the LLM can tell a
                # slot answer from "मुझे एजेंट से बात करनी है".
                return True
            # Let product search advance the wizard without re-classifying
            return False

        if user_profile.get("awaiting_store_pincode"):
            if _sticky_wait_escape_intent(user_query):
                return True
            return bool(has_indic)

        if user_profile.get("callback_capture_step"):
            if _sticky_wait_escape_intent(user_query):
                return True
            return bool(has_indic)

        # Indic-script text bypasses Latin-only regex gates below — the LLM
        # classifier is the only component that can understand free-form Indic.
        if has_indic:
            return True

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
                and _PAGINATION_ONLY_RE.match(stripped)
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

        # ── Universal escape ────────────────────────────────────────────────
        # Runs before should_run() and before every sticky-wait check, because
        # should_run() is exactly what skipped the classifier while the wizard
        # was active. A user asking for a human, a callback, a video call or
        # reporting damage is never answering "what's your budget?".
        #
        # This only RELEASES the wait. The intent is still decided by the full
        # classifier below, so a regex or gate misfire cannot route the turn.
        escape_text = ""
        if "text" in data.get("messages", {}):
            escape_text = (data["messages"]["text"].get("body") or "").strip()
        flow_keeps_turn = False
        if escape_text and _has_sticky_wait(user_profile):
            escape_intent = await _check_universal_escape(
                data,
                user_profile,
                escape_text,
                client_id=client_id,
                phone_number=phone_number,
            )
            if escape_intent and escape_intent != "unknown":
                # Only used if the classifier LLM then fails — never routed
                # directly while the LLM is healthy. "unknown" means the gate
                # only knows the user left the flow, not where they went, so
                # there is nothing to fall back to.
                data["_escape_verdict"] = escape_intent
            elif escape_intent is None and not (
                is_greeting_message(escape_text) or is_menu_request(escape_text)
            ):
                # The message ANSWERS the pending question. The flow owns the
                # turn — and this verdict must outrank the Latin escape regex
                # further down, which would otherwise tear the funnel apart for
                # a legitimate answer ("ring" at the category step).
                flow_keeps_turn = True

        if flow_keeps_turn or not self.should_run(data):
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
            raw_query = ""
            chat_history: list = user_profile.get("chat_history") or []
            if "text" in data["messages"]:
                user_query = data["messages"]["text"]["body"]

                # Script-mirror the stored language to THIS message even on
                # shortcut paths that skip the LLM (greeting, ack, overrides).
                _store_language(user_profile, None, user_query)

                # Keep the raw user text for shortcuts / overrides / sticky escape.
                # Context-prefixed rewrite is LLM-only (pending clarification).
                raw_query = user_query
                llm_user_query = user_query
                if user_profile.get("pending_clarification"):
                    user_profile["pending_clarification"] = False
                    clarified = raw_query.strip()
                    llm_user_query = (
                        "Context: user was asked to clarify their previous message. "
                        f"Their clarification: {clarified}"
                    )

                if raw_query.strip().lower() == "stop":
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": "You've been successfully unsubscribed.",
                        }
                    ]
                    return data

                if raw_query.lower() == "hi from ads":
                    user_profile["service_selected"] = ServiceList.AD_FLOW.value
                    return data

                chat_history = data["user_profile"].get("chat_history", [])
                if is_greeting_message(raw_query):
                    _reset_session_on_fresh_start(user_profile)
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
                    rating = _parse_rating_reply(raw_query)
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

                if is_menu_request(raw_query):
                    _reset_session_on_fresh_start(user_profile)
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

                # Set when the Latin escape regexes saw nothing but the message
                # is native script — the LLM verdict below decides whether the
                # sticky wait is dropped or keeps the turn.
                sticky_escape_deferred = False

                if _has_sticky_wait(user_profile):
                    escape_intent = _sticky_wait_escape_intent(raw_query)
                    if escape_intent:
                        if escape_intent == "product_search":
                            # Still shopping: carry the button-tapped slots so
                            # the funnel does not re-ask them. (Not for handoff /
                            # order escapes — they are done browsing.)
                            _stash_wizard_carryover(data, user_profile)
                        # Regex only clears the sticky wait so the funnel does not
                        # swallow the message. Intent is LLM-primary below —
                        # never treat escape_intent as a hard verdict (that used
                        # to route callback/handoff through _apply_intent_routing
                        # → fallback_unclear / "samajh nahi aaya").
                        _clear_sticky_waits(user_profile)
                        extra_entities: dict[str, Any] = {}
                        if user_profile.pop("_price_direction_hint", None):
                            extra_entities["price_direction"] = "higher"
                        if escape_intent == "product_search":
                            extracted = extract_entities(raw_query)
                            for key in (
                                "category",
                                "material_type",
                                "min_price",
                                "max_price",
                                "metal_colour",
                            ):
                                if extracted.get(key) is not None:
                                    extra_entities[key] = extracted[key]
                        if extra_entities:
                            _store_llm_entities(data, user_profile, extra_entities)
                        # Provisional routing verdict. The LLM below is still
                        # primary and overwrites this via _route_resolved_intent
                        # — but if the LLM call fails, the escape must not lose
                        # the turn: without this, an exception left
                        # classified_category unset and the user got
                        # "Sorry, I didn't catch that" after a clear "Ring".
                        data["classified_category"] = escape_intent
                        data["classifier_confidence"] = 0.9
                        data["_escape_verdict"] = escape_intent
                        logger.info(
                            "Sticky wait cleared — LLM will classify escape",
                            extra={
                                "phone_number": phone_number,
                                "escape_hint": escape_intent,
                            },
                        )
                        # Fall through to ack / override / LLM
                    elif _INDIC_SCRIPT_RE.search(raw_query):
                        # Native script — every escape regex above is Latin-only,
                        # so "silence" here is not evidence the user stayed in
                        # the flow. Let the LLM classify, then decide (below).
                        sticky_escape_deferred = True
                        logger.info(
                            "Native-script message in sticky wait — deferring "
                            "escape decision to the LLM",
                            extra={"phone_number": phone_number},
                        )
                    elif user_profile.get("awaiting_store_pincode"):
                        if raw_query.strip().lower() not in ("cancel", "back"):
                            _store_llm_entities(data, user_profile, {})
                            user_profile["service_selected"] = ServiceList.AD_FLOW.value
                            data["classified_category"] = "store_info"
                            logger.info(
                                "Store lookup shortcut — routing to ad_flow",
                                extra={"phone_number": phone_number},
                            )
                            return data

                if _is_acknowledgement_message(raw_query, user_profile):
                    _store_llm_entities(data, user_profile, {})
                    data["classified_category"] = "acknowledgement"
                    data["bot_response"] = build_acknowledgement_bot_response()
                    logger.info(
                        "Acknowledgement shortcut",
                        extra={"phone_number": phone_number},
                    )
                    return data

                override = _programmatic_intent_override(raw_query)
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
                        raw_query,
                        chat_history,
                        intent,
                        confidence,
                    ):
                        await _finalize_classifier_response(data)
                        return data
                    return data

                logger.info(
                    "Request received to classify query",
                    extra={"phone_number": phone_number, "query": raw_query},
                )

                chat_history_str = format_recent_history_str(user_profile, 8)
                system_content = _build_classifier_system_content(
                    user_profile,
                    chat_history_str,
                    hint=_programmatic_intent_hint(raw_query),
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
                            "content": f"User Query: {llm_user_query}",
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
                _store_language(user_profile, parsed.get("language"), raw_query)
                override = _programmatic_intent_override(raw_query)
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

                # CANONICAL ENTITY EXTRACTION for this turn.
                #
                # The classifier prompt no longer extracts search filters — it
                # returns intent, confidence, language and the two routing
                # fields only. This focused, context-free pass is therefore the
                # single place search filters come from, and its result is
                # stashed for the search agent to reuse, so a search turn stays
                # at two LLM calls (classifier + extractor) rather than three.
                #
                # It runs only for intents that can lead to a catalogue search.
                # The "already has entities" guard is NOT vestigial: it skips
                # the call when the response already carried filters — the regex
                # entities a sticky escape stores, and mocked/legacy classifier
                # responses — which is also what stops a price-only refinement
                # being disturbed by a re-read.
                if intent in _ENTITY_EXTRACTION_INTENTS and not _has_search_entities(
                    sanitized_entities
                ):
                    try:
                        from kisna_chatbot.processors.entity_extractor import (
                            extract_entities_with_llm,
                        )

                        extracted = await extract_entities_with_llm(
                            user_query=raw_query,
                            client_id=client_id,
                            phone_number=phone_number,
                        )
                        if extracted:
                            for key, val in extracted.items():
                                if val is not None and not sanitized_entities.get(key):
                                    sanitized_entities[key] = val
                            stash_context_free_entities(data, raw_query, extracted)
                            logger.info(
                                "Canonical entity extraction complete",
                                extra={
                                    "phone_number": phone_number,
                                    "category": extracted.get("category"),
                                    "llm_intent": intent,
                                },
                            )
                    except Exception:
                        logger.warning(
                            "canonical entity extraction failed — regex fallback",
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

                # Store-location guard: "do you have a store in Mumbai" is often
                # hallucinated as product_search because "do you have X" looks like
                # inventory. Clear physical-store phrasing (no jewellery category)
                # always wins → store_info.
                if (
                    _STORE_LOOKUP_RE.search(raw_query)
                    and not sanitized_entities.get("category")
                    and not (
                        _CATEGORY_WORD_RE.search(raw_query)
                        and _BROWSE_ACTION_RE.search(raw_query)
                    )
                    and intent
                    in (
                        "product_search",
                        "product_info",
                        "general",
                        "menu_help",
                        "greeting",
                    )
                ):
                    logger.info(
                        "Store-location guard corrected intent",
                        extra={
                            "phone_number": phone_number,
                            "llm_intent": intent,
                            "query": raw_query,
                        },
                    )
                    intent = "store_info"
                    confidence = max(confidence, 0.9)

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

                if sticky_escape_deferred:
                    # Native-script message inside a sticky wait — the LLM has
                    # now read it, so the escape decision is finally informed.
                    if _llm_intent_escapes_sticky(user_profile, intent):
                        _clear_sticky_waits(user_profile)
                        logger.info(
                            "Sticky wait cleared by LLM verdict",
                            extra={"phone_number": phone_number, "intent": intent},
                        )
                    else:
                        # It answered the flow's own question — hand the turn
                        # back with the LLM entities the flow could not parse.
                        logger.info(
                            "Native-script message kept by sticky flow",
                            extra={"phone_number": phone_number, "intent": intent},
                        )
                        return data

                if _route_resolved_intent(
                    data,
                    user_profile,
                    phone_number,
                    raw_query,
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
            if await _route_on_llm_failure(
                data, user_profile, phone_number, raw_query, chat_history
            ):
                return data
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
            if await _route_on_llm_failure(
                data, user_profile, phone_number, raw_query, chat_history
            ):
                return data
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


async def _route_on_llm_failure(
    data: dict,
    user_profile: dict,
    phone_number: str,
    raw_query: str,
    chat_history: list,
) -> bool:
    """Honour crystal-clear support asks when the classifier LLM is down."""
    # A sticky-wait escape already resolved this turn by regex before the LLM
    # was called. Losing that verdict to an LLM outage is how a clear "Ring"
    # during a store wait ended up as "Sorry, I didn't catch that".
    escape_verdict = data.pop("_escape_verdict", None)
    fallback = _programmatic_intent_fallback(raw_query)
    if escape_verdict and not fallback:
        fallback = (escape_verdict, 0.9)
    if not fallback:
        return False
    intent, confidence = fallback
    # Keep anything the escape path already extracted (regex category/price for
    # a product_search escape); only guarantee the key exists.
    _store_llm_entities(data, user_profile, data.get("llm_extracted_entities") or {})
    logger.warning(
        "Classifier LLM failed — applying unambiguous intent fallback",
        extra={
            "phone_number": phone_number,
            "intent": intent,
            "confidence": confidence,
            "query": raw_query,
        },
    )
    if _route_resolved_intent(
        data,
        user_profile,
        phone_number,
        raw_query,
        chat_history,
        intent,
        confidence,
    ):
        await _finalize_classifier_response(data)
        return True
    # No bot_response was produced, but the intent WAS routed (service_selected
    # is set and the service pipeline owns the turn from here). For an escape
    # verdict that is a complete outcome — falling through to the generic
    # "didn't catch that" would throw away a verdict we are confident in.
    if escape_verdict:
        return True
    return False
