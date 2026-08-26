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

_ORDER_STATUS_RE = re.compile(
    r"\b(order\s+status|order\s+confirm(?:ed)?|order\s+placed|"
    r"order\s+(?:ban(?:a)?|hua)\s*(?:ya\s*nahi)?|"
    r"shipment\s+status|dispatch(?:ed)?\s*(?:hua|ya\s+nahi)?|"
    r"ship(?:ped)?\s*(?:hua|ho\s+gaya)?\s*(?:ya\s+nahi)?)\b",
    re.I,
)

_ORDER_TRACK_RE = re.compile(
    r"\b(track\s+(my\s+)?order|order\s+track|where\s+is\s+my\s+order|"
    r"delivery\s+status|order\s+kaha|mera\s+order\s+kaha|"
    r"delivery\s+kab|kab\s+tak\s+(?:milega|pahuchega|aayega))\b",
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

# Asking FOR contact details is not asking to be put through. "What's the
# customer care number?" was being handed straight to a live agent: the user's
# actual question went unanswered and a human was paged who was never needed.
_SUPPORT_CONTACT_RE = re.compile(
    r"\b(?:"
    r"(?:customer\s*care|custumer\s*care|support|helpline|help\s*line|contact)"
    r"\s*(?:team\s*)?(?:ka|ke|ki)?\s*"
    r"(?:number|no\.?|num|phone|mobile|email|e-?mail|id|details|address|info)"
    r"|(?:number|phone|email|e-?mail|contact\s*details?)\s*(?:of|for|de[nd]o|do)\s*"
    r"(?:customer\s*care|support|helpline)"
    r"|helpline"
    r"|how\s+(?:do\s+i|can\s+i|to)\s+(?:contact|reach)\b"
    r"|kaise\s+contact\s+kar"
    r")\b",
    re.I,
)

# A message that also asks to be CONNECTED wants the agent, not the number.
_CONNECT_VERB_RE = re.compile(
    r"\b(connect|transfer|talk|speak|chat|baat\s*kar|call\s*me|"
    r"put\s+me\s+through)\b",
    re.I,
)


def _is_support_contact_request(text: str) -> bool:
    """True when the user wants the contact details, not a live transfer."""
    normalized = (text or "").strip()
    if not normalized:
        return False
    if _CONNECT_VERB_RE.search(normalized):
        return False
    return bool(_SUPPORT_CONTACT_RE.search(normalized))


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
from kisna_chatbot.utils.script_detect import (  # noqa: E402
    has_non_latin_letters,
)

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
    r"\b(tanishta|evil\s+eye)\b",
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
    if _ORDER_STATUS_RE.search(normalized):
        return "order_status"
    if _ORDER_TRACK_RE.search(normalized):
        return "track_order"
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
        # Kept even though Clara stocks none of these: dropping them here would
        # scrub the material to null and the funnel would then ask "gold,
        # diamond or gemstone?" as though the customer had never named silver.
        # _CLARA_UNSUPPORTED_MATERIALS is what turns them into an honest
        # "we don't carry that", and it can only fire on a value that survives.
        "pearl",
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
_LLM_ENTITY_KARATS = frozenset({"9KT", "14KT", "18KT", "24KT"})
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

    # The metal the customer RULED OUT. Before this field existed the model had
    # nowhere to record a refusal, so it fell back on the mapping table and
    # emitted the refused metal: "मुझे सोने की नहीं, अंगूठी दिखाओ" came back as
    # material_type="gold" in 6 of 6 Indic languages, while English was fine.
    # Same shape as budget="any" — an unrepresentable concept is one the model
    # cannot report, and no amount of "NEVER emit X" wording fixes that.
    excluded = _coerce_null(raw.get("excluded_material"))
    if isinstance(excluded, str):
        excluded = excluded.strip().lower()
        if excluded in ("rose_gold", "white_gold"):
            excluded = "gold"
        excluded = excluded if excluded in _LLM_ENTITY_MATERIALS else None
    else:
        excluded = None
    # A metal cannot be both wanted and refused. Trust the refusal: the failure
    # this field exists to fix is the model naming a refused metal as wanted.
    if excluded is not None and material == excluded:
        material = None
    out["material_type"] = material
    out["excluded_material"] = excluded

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

    # Store-lookup location, in English whatever script was typed. The store
    # locator used to read a 121-entry Latin city list and nothing else, so
    # "मुंबई में आपका स्टोर है क्या?" was answered with "share your pincode"
    # even though Kisna has four Mumbai branches. States had no support at all.
    for _place in ("city", "state"):
        _val = _coerce_null(raw.get(_place))
        out[_place] = (
            _val.strip()[:60]
            if isinstance(_val, str) and _val.strip()
            else None
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

    # A budget is a CEILING, and min == max returns only pieces priced to
    # the exact rupee -- in practice nothing. The model emits it for every
    # "my budget is X" phrasing in every language tested (5/5), and telling
    # it not to did not hold, so the shape is corrected here where it is
    # language-agnostic. Nobody shops for a piece costing exactly 250000.
    for price_key in ("min_price", "max_price"):
        val = _coerce_null(raw.get(price_key))
        if val is not None:
            try:
                out[price_key] = int(float(val))
            except (TypeError, ValueError):
                out[price_key] = None
        else:
            out[price_key] = None

    if (
        out.get("min_price") is not None
        and out["min_price"] == out.get("max_price")
    ):
        out["min_price"] = None

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
    if direction is not None:
        # A stated direction is a refinement of the search, not a request for
        # the next page of it. The model sometimes emits both; the pagination
        # gate reads action, so leaving them both set is a coin flip.
        out["action"] = None

    # "any" = the customer EXPLICITLY said price does not matter, which null
    # cannot express (null also means "never mentioned money"). Without this
    # the only way to notice a decline was to match phrases, which cannot
    # work across the nine languages this bot answers in.
    budget = _coerce_null(raw.get("budget"))
    if isinstance(budget, str):
        budget = budget.strip().lower()
        budget = budget if budget == "any" else None
    else:
        budget = None
    out["budget"] = budget

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

    # What they want to KNOW about that piece, as opposed to which piece they
    # mean. Without it, product_reference was the only signal and every
    # question about a shown product -- "iska price kya hai?" -- re-printed
    # the card the customer was already looking at. Tightening the
    # product_reference rule instead was tried and regressed Hindi into a
    # fresh search, so the two facts are reported separately now.
    # A flag, NOT the question text. Asking the model to echo the question
    # back was tried first and it mangled Gujarati -- "કેટલી કિંમત છે?" came
    # back as an unrelated sentence, and the answerer then answered that.
    # We already hold the customer's message verbatim, so the model only has
    # to judge whether it IS a question.
    question = _coerce_null(raw.get("product_question"))
    if isinstance(question, str):
        question = question.strip().lower() not in ("", "false", "null", "no", "0")
    out["product_question"] = bool(question)

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
# Everything else (store_info, order_status, track_order, returns_refund,
# complaint, callback, video_call, gold_rate, repair) needs none, and skipping the call
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


# Intents that can be answered or acknowledged as a SECOND request without
# starting a flow of their own. order_status, track_order, returns_refund and
# complaint are deliberately absent: each needs its own conversation.
_SECONDARY_INTENTS = frozenset(
    {"offers", "gold_rate", "store_info", "general"}
)


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

    # A SECOND thing asked in the same message. Restricted to intents that
    # can be answered or acknowledged without starting a flow -- anything
    # that needs an order id, a return reason or a complaint cannot be
    # bolted onto another turn, so it is not offered as a choice.
    secondary = parsed.get("secondary_intent")
    if isinstance(secondary, str):
        secondary = secondary.strip().lower()
        secondary = secondary if secondary in _SECONDARY_INTENTS else None
    else:
        secondary = None
    # Naming the same intent twice is not two requests.
    if secondary == intent:
        secondary = None

    return {
        "intent": intent,
        "confidence": confidence,
        "entities": entities,
        "secondary_intent": secondary,
        "language": sanitize_classifier_language(parsed.get("language")),
    }


# The telecom opt-out conventions. Kept as an exact-match fast path because
# honouring an opt-out must NEVER depend on a model call succeeding -- but it is
# only the fast path now: anything phrased differently, or in any other
# language, is read by the classifier as the `unsubscribe` intent.
#
# This was `== "stop"` alone, so "unsubscribe", "please remove my number",
# "stop sending me messages" and every non-English equivalent were ignored and
# answered with jewellery suggestions. That is a compliance problem, not a UX
# one.
_OPTOUT_KEYWORDS = frozenset(
    {"stop", "stop all", "unsubscribe", "opt out", "optout", "unsub"}
)


def _is_optout_keyword(query: str) -> bool:
    """Whole-message match only.

    Substring matching would unsubscribe someone who said "stop showing me the
    gold ones", which is far worse than missing a phrasing the LLM will catch.
    """
    normalized = re.sub(r"[^a-z ]+", "", (query or "").strip().lower()).strip()
    return normalized in _OPTOUT_KEYWORDS


def _unsubscribe(data: dict) -> dict:
    data["classified_category"] = "unsubscribe"
    data["bot_response"] = [
        {
            "type": "text",
            "text": "You've been successfully unsubscribed.",
            "_compose": "unsubscribe_ack",
        }
    ]
    return data


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


# Languages whose speakers commonly type in Latin script too, so a Latin
# message must not be answered in the native script. Urdu belongs here despite
# not being Indic: roman Urdu is as common as Hinglish and reads almost the
# same, and answering it in Nastaliq would be the same defect.
_INDIC_LANGS = frozenset(
    {"hi", "gu", "mr", "ta", "te", "bn", "kn", "ml", "pa", "or", "ur"}
)

# _INDIC_SCRIPT_RE (Devanagari-through-Malayalam, U+0900-U+0D7F) only answers
# "is this ANY Indic script" — it can't tell Gurmukhi from Gujarati from
# Devanagari, so a model that mislabels a Punjabi message as "gu" sails
# through unchallenged (has_indic_script=True, base "gu" is in _INDIC_LANGS,
# done). That is the actual mechanism behind observed Gurmukhi->Gujarati and
# Gujarati->Hindi reply-language thrashing: the script check only vetoes
# Indic-vs-Latin, never a wrong Indic language within the Indic family.
# Each of these blocks is script-exclusive (no codepoint overlap between
# them), so the block a message is actually written in can veto an
# incompatible label. Devanagari is shared by hi/mr (script alone can't
# split those two — that's a genuine identity call the LLM has to make), so
# it maps to both with "hi" as the safe default when the model's label is
# neither.
_BENGALI_BASES = frozenset({"bn", "as"})

# Assamese and Bengali share a block but not an alphabet: Assamese writes ৰ
# (U+09F0) and ৱ (U+09F1) where Bengali writes র and ব. Those two letters are
# not used in Bengali orthography at all, so their presence is evidence, not a
# guess -- measured over five real sentences each: 4/5 Assamese carry one,
# 0/5 Bengali do. Widening the frozenset alone was not enough (c219133): the
# block still fell back to "bn" whenever the model did not volunteer "as",
# which was every turn, so an Assamese customer was answered in Bengali 14/14.
# The short turn with no ৰ/ৱ ("হয়") is held by the bn/as sibling stickiness
# further down, the same way hi/mr is.
_ASSAMESE_ONLY_RE = re.compile(r"[\u09f0\u09f1]")


_SCRIPT_LANG_RANGES: tuple[tuple[re.Pattern, frozenset[str], str], ...] = (
    (re.compile(r"[ऀ-ॿ]"), frozenset({"hi", "mr"}), "hi"),  # Devanagari
    (re.compile(r"[઀-૿]"), frozenset({"gu"}), "gu"),  # Gujarati
    (re.compile(r"[਀-੿]"), frozenset({"pa"}), "pa"),  # Gurmukhi
    # Assamese uses the Bengali block. Listing only "bn" overrode a correct
    # "as" label on EVERY turn, so Assamese could never be answered in
    # Assamese — same shape as Devanagari's {"hi","mr"} below.
    (re.compile(r"[ঀ-৿]"), _BENGALI_BASES, "bn"),  # Bengali / Assamese
    (re.compile(r"[଀-୿]"), frozenset({"or"}), "or"),  # Odia
    (re.compile(r"[஀-௿]"), frozenset({"ta"}), "ta"),  # Tamil
    (re.compile(r"[ఀ-౿]"), frozenset({"te"}), "te"),  # Telugu
    (re.compile(r"[ಀ-೿]"), frozenset({"kn"}), "kn"),  # Kannada
    (re.compile(r"[ഀ-ൿ]"), frozenset({"ml"}), "ml"),  # Malayalam
    # Arabic script. Not Indic, but the same rule applies: the block a message
    # is written in vetoes an incompatible label, so Urdu typed in Nastaliq is
    # never answered in Hindi just because the model guessed "hi".
    (re.compile(r"[\u0600-\u06FF]"), frozenset({"ur"}), "ur"),
)


# Positive evidence that Latin-script text is actually romanized Indic.
# Deliberately excludes tokens that are also ordinary English words ("me",
# "main", "ho", "hi", "to", "so", "the") — a false positive here answers an
# English customer in Hinglish, which is the bug this exists to prevent.
_ROMANIZED_INDIC_RE = re.compile(
    r"\b("
    # Hindi / Hinglish
    r"mujhe|mereko|mera|meri|mere|kya|kyu|kyun|kaise|kaisa|kaisi|kitna|kitne|kitni|"
    r"chahiye|chaiye|chahiy|dikhao|dikhaiye|dikha|batao|bataye|bataiye|"
    r"karna|karni|krna|karo|kro|kar|nahi|nahin|nai|koi|kuch|thoda|zyada|jyada|"
    r"sasta|mehnga|bhai|yaar|aap|aapka|aapki|apka|apki|apke|hain|hoga|hogi|"
    r"raha|rahi|rahe|wala|wali|waale|sona|sone|soni|anguthi|angoothi|"
    r"achha|acha|accha|theek|thik|haan|kripya|dhoond|milega|milegi|"
    r"paas|pass|liye|walo|hazaar|hajar|lakh|paisa|paise|"
    # Gujarati romanized
    r"tamari|tamne|tame|joie|joiye|che|chhe|mane|maare|shu|"
    # Marathi romanized
    r"mala|havi|hava|ahe|aahe|dakhva|kuthe|"
    # Bengali romanized
    r"ami|amake|amar|dekhan|dekhao|chai|kothay|"
    # Punjabi romanized
    r"mainu|tuhada|tuhanu|chahida|dikhao|"
    # Tamil / Telugu romanized
    r"enakku|venum|kaattu|naaku|kavali|chupinchu"
    r")\b",
    re.I,
)


def resolve_reply_language(language: str | None, user_text: str) -> str:
    """Language identity from the LLM; SCRIPT from the user's actual characters.

    The user's message proves which script they type — never trust the model's
    -Latn judgement. "Return krna hai" + "hi" → "hi-Latn"; "रिटर्न करना है" +
    "hi-Latn" → "hi". Reply always mirrors the script of the LAST message.

    Within the Indic family, the specific script block also proves the
    specific language when that block is script-exclusive (Gujarati,
    Gurmukhi, Bengali, ...): a model label that doesn't match what the user
    actually typed is overridden, not trusted just because it's "some"
    Indic language.
    """
    lang = sanitize_classifier_language(language)
    base = lang[:-5] if lang.endswith("-Latn") else lang
    text = user_text or ""
    for script_re, valid_bases, default_base in _SCRIPT_LANG_RANGES:
        if script_re.search(text):
            # Letters Bengali does not have settle the pair outright — the
            # same authority the block itself carries, one level finer.
            if valid_bases is _BENGALI_BASES and _ASSAMESE_ONLY_RE.search(text):
                return "as"
            return base if base in valid_bases else default_base
    if base in _INDIC_LANGS:
        # Latin characters alone do not make a message romanized Indic. The
        # classifier labelled the plain English sentence "I need a ring" as
        # Hindi, and trusting that answered an all-English customer with
        # "Ye kis ke liye hai?" — and, because the label persists, every reply
        # after it too. Require actual romanized-Indic words before mirroring
        # into Hinglish; English is the safe default when they are absent.
        if _ROMANIZED_INDIC_RE.search(text):
            return f"{base}-Latn"
        return "en"
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
    "urdu": "ur",
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


# Filler and bare values that prove nothing about the customer's language.
# Anything containing Indic characters is excluded up front: that DOES prove a
# script, however short the message is.
_LOW_SIGNAL_ALWAYS_RE = re.compile(
    r"^[\W\d]*$"  # digits / punctuation / emoji only ("50000", "?", "😍")
    r"|^\s*(?:yes|no|ok|okay|yeah|yup|sure|hi|hii+|hey|hello|thanks|ty)\b",
    re.I,
)


def _is_low_language_signal(user_text: str) -> bool:
    """True when this message is too thin to justify changing reply language.

    The test is "is this an ANSWER rather than prose", not "is this short".
    Length alone is wrong: "Return krna hai" is three words and unmistakably
    romanized Hindi, while "Ready to ship" is three words of our own button
    label and says nothing about the speaker.
    """
    text = (user_text or "").strip()
    if not text:
        return True
    # Any non-Latin script, not just Indic — see utils/script_detect.
    if has_non_latin_letters(text):
        return False
    if _LOW_SIGNAL_ALWAYS_RE.search(text):
        return True

    from kisna_chatbot.processors.shopping_wizard import (
        _ANY_ANSWER_RE,
        _FULFILLMENT_TITLE_MAP,
        _GENDER_TITLE_MAP,
        _MATERIAL_TITLE_MAP,
    )

    normalized = " ".join(text.lower().split()).strip("*.!?, ")
    if (
        normalized in _GENDER_TITLE_MAP
        or normalized in _MATERIAL_TITLE_MAP
        or normalized in _FULFILLMENT_TITLE_MAP
    ):
        return True
    words = text.split()
    # "under 50k", "Under 10k ?", "15-35k" — a budget, not a language.
    if len(words) <= 3 and any(ch.isdigit() for ch in text):
        return True
    # "anyone", "koi bhi" — a decline, not a language.
    if len(words) <= 2 and _ANY_ANSWER_RE.search(text):
        return True
    return False


# Two languages sharing one script: no script check can separate them, so the
# per-turn LLM label alone decides, and a short refinement flips the whole
# conversation. Live: a Marathi search answered correctly, then "थोडं स्वस्त
# दाखवा" came back in Hindi and stayed there; and an Assamese customer was
# answered in Bengali. Every other language is protected by the script veto in
# _SCRIPT_LANG_RANGES — these two pairs are the only ones that cannot be.
_SAME_SCRIPT_SIBLINGS = {"hi": "mr", "mr": "hi", "bn": "as", "as": "bn"}

# A genuine language switch is a sentence; a slot answer or a refinement is a
# few words. Past this length we believe the label.
_SIBLING_STICKY_MAX_WORDS = 6


def _is_sibling_flip(stored: str | None, resolved: str, user_text: str) -> bool:
    """True when a SHORT message would flip between two same-script languages."""
    if not stored:
        return False
    stored_base = stored.split("-")[0]
    resolved_base = (resolved or "").split("-")[0]
    if _SAME_SCRIPT_SIBLINGS.get(stored_base) != resolved_base:
        return False
    return len((user_text or "").split()) <= _SIBLING_STICKY_MAX_WORDS


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
    stored = user_profile.get("language")
    if stored and _is_low_language_signal(user_text):
        # "under 50k", "Female", "Gold" carry almost no language evidence, but
        # the classifier still has to emit SOME label. Acting on it flipped
        # settled conversations: an all-English session answered "under 50k"
        # with "Aap aaj kya dhoond rahe hain?" and stayed Hinglish for the rest
        # of the chat (9/9 live), and a Gujarati-script customer who typed one
        # English word was demoted to romanized Gujarati. A slot answer is not
        # a language change; keep what the conversation already established.
        return
    if language:
        resolved = resolve_reply_language(language, user_text)
        if _is_sibling_flip(stored, resolved, user_text):
            # Keep what the conversation established, but still let the SCRIPT
            # follow the current message (native vs romanized).
            user_profile["language"] = resolve_reply_language(stored, user_text)
            return
        user_profile["language"] = resolved
        return
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
        "order_status",
        "track_order",
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
               material or category word, or an answer in any language/script).
               ALSO "answer" when it gives a budget, audience, metal or
               availability we have not asked for YET — the user is volunteering
               a detail about the SAME item, not starting over.
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
        # Snapshot before the wipe below. Whether this survives the turn is
        # decided later, once the actual intent is known -- see
        # _restore_wizard_after_safe_detour. At THIS point all we know is the
        # message doesn't answer the wizard's own question; it could still
        # turn out to be a self-contained detour (offers/gold_rate/store_info/
        # general) rather than a real abandonment.
        data["_wizard_detour_snapshot"] = {
            key: user_profile[key] for key in _WIZARD_STICKY_KEYS if key in user_profile
        }
        # The wizard belongs exclusively to product_search -- it is only ever
        # started there (shopping_wizard.py). The detour turn hands
        # service_selected to whichever pipeline answers it (ad_flow,
        # general, ...) and does not always hand it back, so pipeline
        # dispatch for the NEXT turn has nothing to route a button tap to
        # unless this comes back too.
        data["_wizard_detour_snapshot"]["service_selected"] = (
            ServiceList.PRODUCT_SEARCH.value
        )

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

    # 0. An explicit language-switch request is never the answer to a pending
    #    question, no matter how short. Without this, "In English" right
    #    after a wizard/store/callback prompt reads as answering it, and
    #    Classifier.process() returns before _store_language -- the only
    #    caller of detect_language_override -- ever runs, so an unambiguous
    #    request to switch language is silently ignored. Live: a returning
    #    tester's "In English" was swallowed twice running, right after the
    #    wizard's category prompt; only a longer, more distinctive phrasing
    #    on the third try escaped this gate and reached the classifier.
    if detect_language_override(normalized):
        _release_sticky_wait(data, user_profile, regex_hint or "unknown", normalized)
        return regex_hint or "unknown"

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


# The flows that ASK for an order number. While one of them owns the
# conversation, an order id is the answer to its question — not a request to
# track that order.
_ORDER_ID_OWNING_SERVICES = {
    ServiceList.RETURNS_REFUND.value,
    ServiceList.COMPLAINT.value,
}


def _keep_order_id_with_its_flow(
    user_profile: dict, user_query: str, intent: str
) -> str:
    """Do not let order tracking steal the answer to a returns/complaint prompt.

    Live: "I want to return my order" -> the returns prompt; "KIS12345" ->
    "Order KIS12345 - click below to track your order"; and the returns prompt
    then restarted from scratch. The customer could not complete a return by
    text at all, in English or Hindi.

    Deliberately narrow: only when one of those flows is already active, only
    when the intent resolved to order_status or track_order, and only when the
    message is essentially JUST an id. "where is my order" mid-return is still
    a real escape and still routes to tracking.
    """
    if intent not in ("order_status", "track_order"):
        return intent
    if user_profile.get("service_selected") not in _ORDER_ID_OWNING_SERVICES:
        return intent
    from kisna_chatbot.processors.order_tracking_agent import (
        _extract_order_id_from_text,
    )

    text = (user_query or "").strip()
    if not _extract_order_id_from_text(text):
        return intent
    # A bare id, or an id with a couple of words around it — not a sentence.
    if len(text.split()) > 4:
        return intent
    return user_profile["service_selected"]


# Keys _release_sticky_wait snapshots and _restore_wizard_after_safe_detour
# puts back — the same four clear_wizard_state (shopping_wizard.py) drops.
_WIZARD_STICKY_KEYS = (
    "shopping_wizard_active",
    "shopping_wizard_step",
    "shopping_wizard_data",
    "shopping_wizard_explicit",
)


def _restore_wizard_after_safe_detour(data: dict) -> None:
    """Give the wizard its progress back after answering a self-contained detour.

    Live: "show me gold rings" -> [Female] tap deferred -> a standalone
    "what's today's gold rate?" (or a store/offers/FAQ question, asked with no
    priming at all) answered correctly, but silently wiped shopping_wizard_data
    -- category=ring, material_type=gold, gone. The next [Female] tap then
    either restarted the wizard from empty, or once, with no active flow left
    to interpret it against, got routed to human_handoff outright.

    _release_sticky_wait has to tear the wizard down the moment a message
    doesn't answer the wizard's OWN pending question -- at that point nothing
    has classified the message yet, so it cannot know if this is a real
    abandonment or an answerable detour. offers/gold_rate/store_info/general
    are exactly the intents _SECONDARY_INTENTS already names as answerable
    without starting a new flow (see secondary_intent.py for the same-message
    case) -- so once the real intent is known, restore what was snapshotted.

    Called from main.py AFTER this turn's reply already exists, deliberately:
    restoring the flag any earlier would run into GeneralAgent's own "wizard
    active -> hand back to product search" guard and swallow the very FAQ
    answer the customer just asked for. This turn's agent runs exactly as it
    does today; only the NEXT turn sees the wizard is still there.
    """
    snapshot = data.pop("_wizard_detour_snapshot", None)
    if not snapshot:
        return
    if data.get("classified_category") not in _SECONDARY_INTENTS:
        return
    user_profile = data.get("user_profile")
    if not isinstance(user_profile, dict):
        return
    # service_selected rides along too -- pipeline dispatch for the NEXT turn
    # needs it back at "product_search" or a button tap has nowhere to go.
    for key, value in snapshot.items():
        user_profile[key] = value


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
    intent = _keep_order_id_with_its_flow(user_profile, user_query, intent)
    data["classified_category"] = intent
    data["classifier_confidence"] = confidence
    try:
        from kisna_chatbot.utils.message_trace import trace_step

        _INTENT_LABELS = {
            "product_search": "Product search",
            "store_info": "Store lookup",
            "offers": "Offers",
            "order_status": "Order status",
            "track_order": "Track my order",
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
        if _is_support_contact_request(user_query):
            # Answer the question that was actually asked, then offer the
            # transfer as a choice rather than making it for them.
            from kisna_chatbot.processors.support_handler import (
                build_support_contact_response,
            )

            data["classified_category"] = "support_contact"
            data["bot_response"] = build_support_contact_response(user_profile)
            return True
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

    if confidence < CLARIFICATION_CONFIDENCE_THRESHOLD and _is_misspelled_store_lookup(
        user_query
    ):
        intent = "store_info"
        data["classified_category"] = intent
        confidence = 0.9

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


def _apply_product_url_shortcut(data: dict, raw_query: str) -> bool:
    """Route one or more pasted Kisna product URLs straight to product search.

    A raw product URL is an unambiguous, high-confidence signal that doesn't
    need LLM classification -- resolved the same way plain-text title search
    already works (see kisna_product_url.py for why: Clara has no lookup-by-
    id/slug/variant endpoint, only `title` substring search).
    """
    from kisna_chatbot.processors.product_search_agent_v3 import _empty_entities
    from kisna_chatbot.utils.kisna_product_url import (
        extract_kisna_product_urls,
        product_url_to_title_query,
    )

    urls = extract_kisna_product_urls(raw_query, limit=3)
    if not urls:
        return False
    phrases: list[str] = []
    seen_phrases: set[str] = set()
    for u in urls:
        phrase = product_url_to_title_query(u)
        if not phrase or phrase.lower() in seen_phrases:
            # Different variant= ids of the SAME product slug resolve to the
            # identical title phrase -- without this, the same product would
            # be searched and shown twice.
            continue
        seen_phrases.add(phrase.lower())
        phrases.append(phrase)
    if not phrases:
        return False

    user_profile = data["user_profile"]
    entities = {**_empty_entities(), "title": phrases[0]}
    _store_llm_entities(data, user_profile, entities)
    user_profile["service_selected"] = ServiceList.PRODUCT_SEARCH.value
    data["classified_category"] = "product_search"
    # Turn-scoped only -- not persisted to user_profile. Consumed and popped
    # by ProductSearchAgentV3._handle_url_multi_search, for ONE url too: a
    # pasted product link is an unambiguous, explicit signal, so it always
    # searches directly rather than routing through the normal per-turn flow
    # (which can independently infer a category from slug words like
    # "pendant" and trigger an avoidable confirmation prompt).
    data["_url_search_titles"] = phrases
    return True


_STORE_WORDS = ("store", "shop", "showroom", "outlet")
_STORE_TYPO_TOKEN_RE = re.compile(r"[A-Za-z]{4,}")


def _within_one_edit(word: str, target: str) -> bool:
    """True when ONE typing slip turns word into target.

    Insertion, deletion, substitution -- and transposition, which plain
    Levenshtein scores as two edits but which is the single most common thing
    fingers actually do: "stroe" for "store".
    """
    if abs(len(word) - len(target)) > 1:
        return False
    if word == target:
        return True
    if len(word) == len(target):
        differing = [i for i, (a, b) in enumerate(zip(word, target)) if a != b]
        if len(differing) == 1:
            return True
        if len(differing) == 2:
            i, j = differing
            return (
                j == i + 1
                and word[i] == target[j]
                and word[j] == target[i]
            )
        return False
    shorter, longer = (word, target) if len(word) < len(target) else (target, word)
    i = j = 0
    skipped = False
    while i < len(shorter) and j < len(longer):
        if shorter[i] == longer[j]:
            i += 1
            j += 1
            continue
        if skipped:
            return False
        skipped = True
        j += 1
    return True


def _is_misspelled_store_lookup(user_query: str) -> bool:
    """A store question we failed to recognise because "store" was mistyped.

    Live: "story udaipur" came back intent=general at 0.3-0.4 confidence and
    the customer got the generic "what are you looking for?" card -- with a
    real KISNA branch in Udaipur. Every correctly-spelled variant scores
    0.92-0.93, and "story mumbai" happens to score 0.92 too, so this is the
    model being unsure about one particular string rather than a rule anyone
    can write.

    Two conditions, and BOTH are required. A near-miss of a store word alone
    would fire on "tell me a story"; a city name alone would hijack a bare
    "Udaipur" answered at some other step. Together they are specific enough
    to be safe, and this only ever runs on the low-confidence clarification
    path -- the one where we were about to admit we did not understand -- so
    it cannot change any routing that already works.
    """
    text = (user_query or "").strip()
    if not text or len(text.split()) > 6:
        return False
    lowered = text.lower()
    # "stone" is one edit from "store", so "stone ring udaipur" would otherwise
    # be sent to the locator instead of the catalogue. A jewellery word means
    # they are shopping -- the same guard the deterministic store override
    # above already applies for the same reason.
    if _CATEGORY_WORD_RE.search(lowered):
        return False
    if not any(
        _within_one_edit(token, word)
        for token in _STORE_TYPO_TOKEN_RE.findall(lowered)
        for word in _STORE_WORDS
    ):
        return False
    from kisna_chatbot.processors.entity_extractor import _extract_city

    # The deterministic resolver, deliberately: the LLM returned city=None on
    # 2 of 3 runs for this exact input, while the city list resolves it every
    # time.
    return bool(_extract_city(text))


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
    "order_status": ServiceList.ORDER_TRACKING,
    "track_order": ServiceList.ORDER_TRACKING,
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
        # Named has_indic historically; the question is really whether the
        # Latin-only escape regexes below could have read this at all, so
        # it covers Arabic/Urdu too. Urdu escapes were looping the funnel.
        has_indic = has_non_latin_letters(user_query)

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
            # NOTE: a pasted product URL landing here (a sticky wait owns the
            # turn) is not detected -- _apply_product_url_shortcut only runs
            # further down, on the ordinary per-turn path. Same pre-existing
            # gap every shortcut below already has; not new breakage.
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

                if _apply_product_url_shortcut(data, raw_query):
                    logger.info(
                        "Product URL shortcut — routing to product search",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if _is_optout_keyword(raw_query):
                    return _unsubscribe(data)

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

                if user_profile.get("awaiting_support_connect"):
                    # They were shown the customer-care details and asked
                    # whether to connect. Handle a TYPED yes/no here; a tapped
                    # quick reply is handled in service_list.
                    from kisna_chatbot.processors.service_list import (
                        _handle_support_connect_reply,
                    )

                    _store_llm_entities(data, user_profile, {})
                    _handle_support_connect_reply(
                        raw_query, data, user_profile, phone_number
                    )
                    await _finalize_classifier_response(data)
                    return data

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
                    elif has_non_latin_letters(raw_query):
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
                # Set unconditionally, including to None: a stale secondary
                # from an earlier turn would append an answer nobody asked
                # for on this one.
                data["secondary_intent"] = parsed.get("secondary_intent")
                _store_language(user_profile, parsed.get("language"), raw_query)
                # Any language, any phrasing — the keyword fast path above only
                # covers the telecom conventions. Checked AFTER the language is
                # stored: the ack is composed from user_profile["language"], so
                # returning before that told a Hindi customer "You've been
                # successfully unsubscribed" in English.
                if intent == "unsubscribe":
                    return _unsubscribe(data)
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
                # jewellery category was extracted and the classifier's own
                # label was general/menu_help/greeting, the user is shopping and
                # the classifier missed it entirely — trust the extraction.
                #
                # product_info is handled separately below: unlike the other
                # three, a product_info label is not automatically a miss. Any
                # "price of a NAMED product" query ("Maggio ring ki price kya
                # hai?") legitimately contains a category word — the product's
                # own name — so the extractor finds "ring" even when
                # product_info was exactly right. Overriding those sent every
                # specific-product price question to a browse search instead of
                # answering the question asked. Only override when the
                # classifier itself was unsure (below its own clarification
                # threshold), which is the genuine "browse query mislabelled at
                # low confidence" case this guard exists for.
                if sanitized_entities.get("category") and intent in (
                    "general",
                    "menu_help",
                    "greeting",
                ):
                    intent = "product_search"
                    confidence = max(confidence, 0.8)
                elif (
                    sanitized_entities.get("category")
                    and intent == "product_info"
                    and confidence < CLARIFICATION_CONFIDENCE_THRESHOLD
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
