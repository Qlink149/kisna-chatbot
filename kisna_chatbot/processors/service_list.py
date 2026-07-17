import json
import time

from kisna_chatbot.config.gupshup import get_callback_flow_id, get_videocall_flow_id
from kisna_chatbot.models.enums import ListIds, QuickReplyId
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.order_tracking_agent import build_track_order_bot_response
from kisna_chatbot.processors.support_handler import (
    HELP_CALLBACK_POSTBACK,
    HELP_CALLBACK_QR_MSGID,
    build_expert_support_bot_response,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.support_hours import format_support_hours_text

_FLOW_SWITCH_PENDING_TTL = 300  # 5 minutes — FIX 13b

_GENERIC_ERROR = "Apologies — something went wrong on my end. Could you please try again?"

_TEXT_HELP_PROMPT = (
    "Just tell me what you need — browse products, check offers, find a store, "
    "track an order, or get help. I'm here to assist."
)

_EXPLORE_CAT_LIST_MSGID = "search$cat$list"
_HELP_CENTER_MSGID = "help$center$list"

_FIND_STORE_TEXT = (
    "Share your pincode or city and I'll help you find the nearest Kisna store."
)

_CAPABILITY_HINT = (
    "Just tell me what you're looking for — rings, necklaces, offers, "
    "a store near you, or your order status."
)

_SLOT_FILL_QUESTION = (
    "Lovely! Are you thinking rings, earrings, necklaces…? "
    "And any budget in mind? e.g. under 25k, 15–35k, around 1 lakh"
)

_BUDGET_TEXT_PROMPT = (
    "What budget do you have in mind? e.g. under 25k, 15–35k, around 1 lakh"
)

_ACK_TEXT = (
    "Happy to help! Ask me anything else — jewellery, offers, your order… 😊"
)

_RATING_TEXT_PROMPT = "How was your experience? Reply with a rating from 1 to 5."

_PRODUCT_DETAIL_HINT = (
    "You can ask me for *similar designs*, a *store near you*, or keep browsing 💎"
)

_GREETING_TOKENS = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hii",
        "hola",
        "namaste",
        "good morning",
        "good afternoon",
        "good evening",
        "whats up",
        "what's up",
        "sup",
    }
)

_FAQ_TEXT = (
    "*About KISNA Diamond & Gold* ✨\n"
    "KISNA is India's trusted certified jewellery brand.\n"
    "All gold is BIS hallmarked. All diamonds come with\n"
    "authenticity certificates.\n\n"
    "*Common Questions*\n"
    "• Returns — 7-day returns\n"
    "• Exchange — 95% diamond / 100% gold (lifetime, 7+ days after purchase)\n"
    "• Buyback — 90% diamond / 97% gold\n"
    "• Certification — BIS + IGI/GIA certified\n"
    "• Delivery — Free shipping, ~6 working day dispatch\n"
    "• Payment — No COD; EMI available on checkout\n"
    "• Support — +91 80651 55600, "
    f"{format_support_hours_text().replace(' IST', '')}\n\n"
    "What would you like to know more about?"
)


def _parse_button_msgid(raw_id: str) -> str:
    """Extract msgid from a Gupshup button id (plain or JSON-encoded)."""
    btn_msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            btn_msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    return btn_msgid if isinstance(btn_msgid, str) else raw_id


def is_pure_greeting(text: str) -> bool:
    """True for short greetings without a separate intent (hi, hello, hey, etc.)."""
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return False
    if normalized in _GREETING_TOKENS:
        return True
    for prefix in ("hi ", "hello ", "hey "):
        if normalized.startswith(prefix) and len(normalized.split()) <= 4:
            return True
    return False


def is_menu_request(text: str) -> bool:
    """True when the user explicitly asks to open/show the menu/options."""
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return False

    if normalized in ("menu", "options", "help"):
        return True

    if normalized in ("?", "??", "???"):
        return True

    # Strict: must explicitly mention "menu" plus an action verb.
    if "menu" in normalized and any(v in normalized for v in ("open", "show", "send")):
        return True

    return False


def is_new_session(chat_history: list) -> bool:
    """True when the user has no prior turns stored (first interaction)."""
    return len(chat_history or []) == 0


def _is_valid_display_name(name: str | None) -> bool:
    """Reject garbage WhatsApp names for greeting personalization."""
    if not name or not isinstance(name, str):
        return False
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 30:
        return False
    if "@" in cleaned:
        return False
    if cleaned.replace(" ", "").isdigit():
        return False
    lowered = cleaned.lower()
    if lowered in ("none", "null", "customer", "user"):
        return False
    return True


def _display_name_from_profile(user_profile: dict | None) -> str | None:
    profile = user_profile or {}
    for key in ("username", "whatsapp_username"):
        candidate = profile.get(key)
        if _is_valid_display_name(candidate):
            return str(candidate).strip()
    return None


def _format_recent_search_hint(user_profile: dict | None) -> str | None:
    """Optional continue-search line when last_search_filters is fresh (<2h)."""
    profile = user_profile or {}
    last_at = profile.get("last_search_at")
    if not last_at or time.time() - last_at > 2 * 60 * 60:
        return None
    filters = profile.get("last_search_filters") or {}
    parts: list[str] = []
    category = filters.get("category")
    if category:
        parts.append(str(category).replace("_", " "))
    material = filters.get("material_type")
    if material:
        parts.append(str(material))
    max_p = filters.get("max_price")
    min_p = filters.get("min_price")
    if max_p and min_p and max_p != min_p:
        parts.append(f"₹{min_p:,}–₹{max_p:,}")
    elif max_p:
        parts.append(f"under ₹{max_p:,}")
    elif min_p:
        parts.append(f"above ₹{min_p:,}")
    if not parts:
        return None
    return f"Want to keep looking at {' '.join(parts)}?"


def build_greeting_text(
    *,
    chat_history: list | None = None,
    user_profile: dict | None = None,
) -> str:
    """English greeting copy — localized by callers via reply_composer."""
    history = chat_history if chat_history is not None else []
    name = _display_name_from_profile(user_profile)
    if is_new_session(history):
        if name:
            return (
                f"Hi {name}! 👋 Welcome to Kisna — I'm KIA, your jewellery assistant.\n"
                f"{_CAPABILITY_HINT}"
            )
        return (
            "Hi! 👋 Welcome to Kisna — I'm KIA, your jewellery assistant.\n"
            f"{_CAPABILITY_HINT}"
        )

    continue_hint = _format_recent_search_hint(user_profile)
    if name:
        text = f"Welcome back, {name}! 👋"
    else:
        text = "Welcome back! 👋"
    if continue_hint:
        text = f"{text}\n{continue_hint}"
    else:
        text = f"{text} {_CAPABILITY_HINT}"
    return text


def build_greeting_welcome_bot_responses(
    phone_number: str | None = None,
    chat_history: list | None = None,
    user_profile: dict | None = None,
) -> list[dict]:
    """Welcome for new or returning users — text only, localized before send."""
    history = chat_history if chat_history is not None else []
    profile = user_profile or {}
    template_key = "greeting_new" if is_new_session(history) else "greeting_return"
    text = build_greeting_text(chat_history=history, user_profile=profile)
    return [{"type": "text", "text": text, "_compose": template_key}]


def build_vague_slot_fill_response() -> dict:
    """One combined clarifying question for vague jewellery browse."""
    return {"type": "text", "text": _SLOT_FILL_QUESTION, "_compose": "slot_fill"}


def build_budget_text_prompt() -> dict:
    """Ask for budget in plain text (replaces budget list / flow wizard)."""
    return {"type": "text", "text": _BUDGET_TEXT_PROMPT, "_compose": "budget_prompt"}


def build_product_detail_hint_response() -> dict:
    return {
        "type": "text",
        "text": _PRODUCT_DETAIL_HINT,
        "_compose": "product_detail_hint",
    }


def build_rating_prompt_response() -> dict:
    return {"type": "text", "text": _RATING_TEXT_PROMPT, "_compose": "rating_prompt"}


def handle_non_text_quick_reply(
    btn_msgid: str, user_profile: dict, data: dict
) -> bool:
    """Route non-text quick-reply taps; return True if handled."""
    if btn_msgid != QuickReplyId.NON_TEXT_BROWSE.value:
        return False

    title = (data.get("_non_text_button_title") or "").strip().lower()

    if title in ("view offers",):
        user_profile["service_selected"] = SL.OFFERS.value
        data["classified_category"] = "offers"
        return True

    if title in ("open menu",):
        data["bot_response"] = [build_main_menu_bot_response()]
        return True

    user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
    data["classified_category"] = "product_search"
    data["bot_response"] = [build_vague_slot_fill_response()]
    return True


def build_main_menu_bot_response() -> dict:
    """Text-only help prompt used wherever the main menu list was sent."""
    return {"type": "text", "text": _TEXT_HELP_PROMPT}


def build_acknowledgement_bot_response() -> list[dict]:
    """Lightweight thank-you / acknowledgement — text only."""
    return [{"type": "text", "text": _ACK_TEXT, "_compose": "acknowledgement"}]


def build_complaint_flow_bot_response() -> dict:
    """WhatsApp Flow payload for damage / quality complaints."""
    return {
        "type": "flow",
        "flow": "damage_complaint",
        "text": "Please provide your order details and describe the issue.",
    }


def build_callback_flow_bot_response() -> dict:
    """WhatsApp Flow payload for callback requests."""
    return {
        "type": "flow",
        "flow": "callback_request",
        "text": "Please share your details for a callback.",
    }


def build_video_call_flow_bot_response() -> dict:
    """WhatsApp Flow payload for video call scheduling."""
    return {
        "type": "flow",
        "flow": "video_call_request",
        "text": "Please share your details to schedule a video call.",
    }


def _start_callback_text_capture(
    user_profile: dict, request_type: str = "callback"
) -> list[dict]:
    user_profile["service_selected"] = SL.CALLBACK.value
    user_profile["callback_capture_step"] = 1
    user_profile["callback_draft"] = {"request_type": request_type}
    from kisna_chatbot.processors.callback_agent import (
        build_callback_text_prompt,
        build_video_call_text_prompt,
    )

    if request_type == "video_call":
        return [{"type": "text", "text": build_video_call_text_prompt(1)}]
    return [{"type": "text", "text": build_callback_text_prompt(1)}]


def _handle_help_center_selection(
    postback: str, user_profile: dict, data: dict, phone_number: str
) -> None:
    key = (postback or "").strip().lower()

    if key == "help$expert":
        user_profile["service_selected"] = ""
        data["bot_response"] = build_expert_support_bot_response(
            phone_number, user_profile
        )
        return

    if key == "help$complaint":
        user_profile["service_selected"] = SL.COMPLAINT.value
        data["bot_response"] = [build_complaint_flow_bot_response()]
        return

    if key == "help$callback":
        if get_callback_flow_id():
            user_profile["service_selected"] = SL.CALLBACK.value
            data["bot_response"] = [build_callback_flow_bot_response()]
        else:
            data["bot_response"] = _start_callback_text_capture(
                user_profile, request_type="callback"
            )
        return

    if key == "help$videocall":
        if get_videocall_flow_id():
            user_profile["service_selected"] = SL.CALLBACK.value
            data["bot_response"] = [build_video_call_flow_bot_response()]
        else:
            data["bot_response"] = _start_callback_text_capture(
                user_profile, request_type="video_call"
            )
        return

    logger.warning("Unknown help center selection", extra={"postback": postback})
    data["bot_response"] = [build_main_menu_bot_response()]


def build_complaint_entry_cta_bot_response() -> dict:
    """Legacy alias — complaint intent sends the form directly."""
    return build_complaint_flow_bot_response()


def _parse_list_reply(messages: dict) -> tuple[str, str, str] | None:
    """Parse list_reply into (msgid, title, postbackText)."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return None

    list_reply = interactive.get("list_reply", {})
    title = list_reply.get("title", "")
    raw_id = list_reply.get("id", "")
    list_msgid = raw_id
    postback = ""

    try:
        payload = json.loads(raw_id)
        if isinstance(payload, dict):
            list_msgid = payload.get("msgid", raw_id)
            postback = str(payload.get("postbackText", "") or "")
    except (json.JSONDecodeError, TypeError):
        pass

    if not isinstance(list_msgid, str):
        return None
    return list_msgid, title, postback


def _normalize_menu_key(title: str, postback: str) -> str:
    """Map list title or postbackText to a stable menu action key."""
    postback = (postback or "").strip().lower()
    if postback:
        legacy_postbacks = {
            "locate_store": "find_store",
        }
        return legacy_postbacks.get(postback, postback)

    title_key = " ".join((title or "").strip().lower().split())
    aliases = {
        "raise complaint": "raise_complaint",
        "raise a complaint": "raise_complaint",
        "help / complaint": "help_center",
        "help center": "help_center",
        "locate store": "find_store",
        "locate_store": "find_store",
        "find store near me": "find_store",
        "explore products": "explore_products",
        "view offers": "view_offers",
        "track my order": "track_order",
        "faqs & help": "faqs_help",
        "faqs / about kisna": "faqs_help",
    }
    return aliases.get(title_key, title_key)


def _clear_explore_browse_session(user_profile: dict) -> None:
    """Reset search session when user explicitly taps Explore Products."""
    user_profile["last_search_filters"] = {}
    user_profile["last_search_products"] = []
    user_profile["last_search_page"] = 0
    user_profile["last_search_buffer"] = []
    user_profile["shown_product_ids"] = []
    user_profile["pref_material"] = None
    user_profile["pref_type"] = None
    user_profile.pop("pref_category", None)
    user_profile.pop("pref_title", None)
    user_profile.pop("preference_step", None)
    user_profile.pop("awaiting_custom_budget", None)
    user_profile.pop("custom_budget_attempts", None)
    user_profile.pop("pending_explore_search", None)
    # FIX 12: reset Show-More exhaustion counters so stale values don't
    # cause incorrect exhaustion on the very first Show More after a fresh browse.
    user_profile["last_search_filter_ratio"] = 1.0
    user_profile["last_search_api_total"] = 0


def build_custom_budget_prompt() -> dict:
    """Prompt user to type a custom budget."""
    return build_budget_text_prompt()


def flow_switch_acknowledgement(current_service: str, new_intent: str) -> str:
    """One-line natural acknowledgement when switching flows silently."""
    acks = {
        (SL.PRODUCT_SEARCH.value, "offers"): "Sure — let me show you today's offers.",
        (SL.PRODUCT_SEARCH.value, "order_tracking"): "Sure — let's look at your order.",
        (SL.PRODUCT_SEARCH.value, "returns_refund"): "Sure — I'll help with returns.",
        (SL.PRODUCT_SEARCH.value, "complaint"): "Sure — let's get your issue logged.",
        (SL.PRODUCT_SEARCH.value, "store_info"): "Sure — let's find a store near you.",
        (SL.OFFERS.value, "product_search"): "Sure — let's browse some jewellery.",
        (SL.AD_FLOW.value, "product_search"): "Sure — let's look at jewellery.",
        (SL.AD_FLOW.value, "offers"): "Sure — let me show you offers.",
        (SL.AD_FLOW.value, "order_tracking"): "Sure — let's check your order.",
    }
    return acks.get(
        (current_service, (new_intent or "").strip().lower()),
        "Sure — let me help with that.",
    )


def build_flow_switch_bot_response(current_service: str, new_intent: str) -> list[dict]:
    """Legacy alias — silent flow switch uses text ack only."""
    return [
        {
            "type": "text",
            "text": flow_switch_acknowledgement(current_service, new_intent),
        }
    ]


def build_explore_products_list() -> dict:
    """Legacy alias — vague browse now uses a text slot-fill question."""
    return build_vague_slot_fill_response()


def build_explore_products_list_with_prompt() -> dict:
    """Legacy alias — vague browse now uses a text slot-fill question."""
    return build_vague_slot_fill_response()


def handle_flow_switch_quick_reply(
    btn_msgid: str, user_profile: dict, data: dict
) -> bool:
    """Route flow-switch quick-reply taps; return True if handled."""
    if btn_msgid != QuickReplyId.FLOW_SWITCH_CONFIRM.value:
        return False

    # FIX 13b: discard stale pending_flow_switch (older than 5 minutes)
    raw_pending = user_profile.get("pending_flow_switch") or {}
    created_at = raw_pending.get("created_at", 0)
    if created_at and (time.time() - created_at) > _FLOW_SWITCH_PENDING_TTL:
        user_profile.pop("pending_flow_switch", None)
        logger.info("pending_flow_switch expired — discarding")
        return False  # treat as unhandled; let normal routing proceed

    title = (data.get("_flow_switch_button_title") or "").strip().lower()
    pending = user_profile.pop("pending_flow_switch", None) or {}

    if "yes" in title:
        new_service = pending.get("service", "")
        new_intent = pending.get("intent", "")
        if new_service:
            if user_profile.get("service_selected") == SL.PRODUCT_SEARCH.value:
                user_profile["last_search_filters"] = {}
                user_profile["shown_product_ids"] = []
            user_profile["service_selected"] = new_service
            if new_intent:
                data["classified_category"] = new_intent
        return True

    data["bot_response"] = [
        {
            "type": "text",
            "text": "No problem, let's continue! What else would you like to see?",
        }
    ]
    if user_profile.get("service_selected") == SL.PRODUCT_SEARCH.value:
        data["bot_response"].append(build_vague_slot_fill_response())
    return True


def build_clarification_bot_response(intent: str, confidence: float) -> list[dict]:
    """Return one plain-text clarifying question for low-confidence classification."""
    intent = (intent or "").strip().lower()
    conf = float(confidence or 0)

    if conf < 0.3:
        text = (
            "I want to make sure I help you right — are you looking to browse jewellery, "
            "check offers, track an order, or find a store?"
        )
    elif intent in ("store_info",):
        text = "Are you looking for a KISNA store near you? Share your PIN code or city."
    elif intent in ("order_tracking", "complaint", "returns_refund"):
        text = (
            "Is this about tracking an existing order, or reporting an issue with one?"
        )
    elif intent in ("offers",) or (intent == "product_search" and conf < 0.42):
        text = "Are you looking for jewellery to browse, or current offers and deals?"
    else:
        text = (
            "Are you looking for a specific jewellery piece, or a question about KISNA?"
        )

    return [{"type": "text", "text": text}]


def handle_clarification_quick_reply(
    btn_msgid: str, user_profile: dict, data: dict
) -> bool:
    """Route clarification quick-reply taps; return True if handled."""
    user_profile["pending_clarification"] = False
    title = (data.get("_clarify_button_title") or "").strip().lower()

    if btn_msgid == QuickReplyId.CLARIFY_BROWSE.value:
        if title in ("ask a question",):
            user_profile["service_selected"] = SL.GENERAL.value
            data["classified_category"] = "general"
            return True
        if title in ("view offers",):
            user_profile["service_selected"] = SL.OFFERS.value
            data["classified_category"] = "offers"
            return True
        if title in ("track order",):
            user_profile["service_selected"] = SL.ORDER_TRACKING.value
            data["classified_category"] = "order_tracking"
            data["bot_response"] = build_track_order_bot_response()
            return True
        if title in ("find store",):
            user_profile["service_selected"] = SL.AD_FLOW.value
            user_profile["awaiting_store_pincode"] = True
            data["classified_category"] = "store_info"
            data["bot_response"] = [{"type": "text", "text": _FIND_STORE_TEXT}]
            return True
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        data["classified_category"] = "product_search"
        data["bot_response"] = [build_vague_slot_fill_response()]
        return True

    if btn_msgid == QuickReplyId.CLARIFY_ASK.value:
        user_profile["service_selected"] = SL.GENERAL.value
        data["classified_category"] = "general"
        return True

    if btn_msgid == QuickReplyId.CLARIFY_STORE_YES.value:
        if "no" in title:
            data["bot_response"] = [build_main_menu_bot_response()]
            return True
        user_profile["service_selected"] = SL.AD_FLOW.value
        user_profile["awaiting_store_pincode"] = True
        data["classified_category"] = "store_info"
        data["bot_response"] = [{"type": "text", "text": _FIND_STORE_TEXT}]
        return True

    if btn_msgid == QuickReplyId.CLARIFY_STORE_NO.value:
        data["bot_response"] = [build_main_menu_bot_response()]
        return True

    if btn_msgid == QuickReplyId.CLARIFY_TRACK.value:
        if "report" in title or "problem" in title:
            user_profile["service_selected"] = SL.COMPLAINT.value
            data["classified_category"] = "complaint"
            data["bot_response"] = [build_complaint_flow_bot_response()]
            return True
        user_profile["service_selected"] = SL.ORDER_TRACKING.value
        data["classified_category"] = "order_tracking"
        data["bot_response"] = build_track_order_bot_response()
        return True

    if btn_msgid == QuickReplyId.CLARIFY_COMPLAINT.value:
        user_profile["service_selected"] = SL.COMPLAINT.value
        data["classified_category"] = "complaint"
        data["bot_response"] = [build_complaint_flow_bot_response()]
        return True

    if btn_msgid == QuickReplyId.CLARIFY_OFFERS.value:
        if "offer" in title:
            user_profile["service_selected"] = SL.OFFERS.value
            data["classified_category"] = "offers"
            return True
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        data["classified_category"] = "product_search"
        data["bot_response"] = [build_vague_slot_fill_response()]
        return True

    if btn_msgid == QuickReplyId.CLARIFY_VIEW_OFFERS.value:
        user_profile["service_selected"] = SL.OFFERS.value
        data["classified_category"] = "offers"
        return True

    if btn_msgid == QuickReplyId.CLARIFY_FIND_STORE.value:
        user_profile["service_selected"] = SL.AD_FLOW.value
        user_profile["awaiting_store_pincode"] = True
        data["classified_category"] = "store_info"
        data["bot_response"] = [{"type": "text", "text": _FIND_STORE_TEXT}]
        return True

    if btn_msgid == QuickReplyId.CLARIFY_ASK_QUESTION.value:
        user_profile["service_selected"] = SL.GENERAL.value
        data["classified_category"] = "general"
        return True

    return False


_CLARIFY_MSGIDS = frozenset(
    {
        QuickReplyId.CLARIFY_BROWSE.value,
        QuickReplyId.CLARIFY_ASK.value,
        QuickReplyId.CLARIFY_STORE_YES.value,
        QuickReplyId.CLARIFY_STORE_NO.value,
        QuickReplyId.CLARIFY_TRACK.value,
        QuickReplyId.CLARIFY_COMPLAINT.value,
        QuickReplyId.CLARIFY_OFFERS.value,
        QuickReplyId.CLARIFY_VIEW_OFFERS.value,
        QuickReplyId.CLARIFY_FIND_STORE.value,
        QuickReplyId.CLARIFY_ASK_QUESTION.value,
        QuickReplyId.NON_TEXT_BROWSE.value,
    }
)


def _build_rating_quickreply() -> dict:
    """Legacy alias — rating is now a plain-text prompt."""
    return build_rating_prompt_response()


def _is_product_search_postback(postback: str) -> bool:
    """True if list postback should be handled by ProductSearchAgentV3."""
    postback = (postback or "").strip()
    return postback.startswith("search$") or postback.startswith("pref$")


def _handle_menu_selection(
    title: str, user_profile: dict, data: dict, postback: str = "", phone_number: str = ""
) -> None:
    """Route Kisna main menu selection (legacy postbacks mapped via aliases)."""
    from kisna_chatbot.utils.message_trace import try_trace

    if _is_product_search_postback(postback):
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        try_trace(data, "Understood as", "Product search (menu)")
        return

    key = _normalize_menu_key(title, postback)

    if key in ("explore_products",):
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        _clear_explore_browse_session(user_profile)
        data["bot_response"] = [build_vague_slot_fill_response()]
        try_trace(data, "Understood as", "Explore products (text slot-fill)")
        try_trace(data, "Action", "Asked category + budget in text")
        return

    if key in ("view_offers",):
        user_profile["service_selected"] = SL.OFFERS.value
        data["classified_category"] = "offers"
        try_trace(data, "Understood as", "Offers (menu selection)")
        return

    if key in ("find_store", "store_info"):
        user_profile["service_selected"] = SL.AD_FLOW.value
        user_profile["awaiting_store_pincode"] = True
        data["bot_response"] = [{"type": "text", "text": _FIND_STORE_TEXT}]
        try_trace(data, "Understood as", "Store locator (menu)")
        try_trace(data, "Action", "Asked for pincode / city")
        return

    if key in ("track_order",):
        user_profile["service_selected"] = SL.ORDER_TRACKING.value
        data["bot_response"] = build_track_order_bot_response()
        try_trace(data, "Understood as", "Order tracking (menu)")
        try_trace(data, "Action", "Sent order tracking link / prompt")
        return

    if key in ("help_center",):
        user_profile["service_selected"] = ""
        data["bot_response"] = [build_main_menu_bot_response()]
        try_trace(data, "Understood as", "Help Center (text)")
        try_trace(data, "Action", "Sent capability summary")
        return

    if key in ("raise_complaint", "damage_complaint", "complaint"):
        user_profile["service_selected"] = SL.COMPLAINT.value
        data["bot_response"] = [build_complaint_flow_bot_response()]
        try_trace(data, "Understood as", "Complaint (menu legacy)")
        try_trace(data, "Action", "Sent complaint form")
        return

    if key.startswith("help$"):
        try_trace(data, "Understood as", f"Help Center option ({key})")
        _handle_help_center_selection(
            key, user_profile, data, phone_number or data.get("phone_number", "")
        )
        return

    if key in ("faqs_help",):
        user_profile["service_selected"] = SL.GENERAL.value
        data["bot_response"] = [{"type": "text", "text": _FAQ_TEXT}]
        try_trace(data, "Understood as", "FAQs (menu)")
        return

    logger.warning(
        "Unknown service list selection",
        extra={"title": title, "postback": postback, "key": key},
    )
    try_trace(
        data,
        "Understood as",
        f"Unknown menu option ({title or postback})",
        status="warn",
    )
    data["bot_response"] = [
        {
            "type": "text",
            "text": (
                "Sorry, I didn't recognize that option. "
                "Just tell me what you need — products, offers, a store, "
                "order tracking, or help."
            ),
        }
    ]


def _handle_rating_button(button_reply: dict, data: dict, phone_number: str) -> None:
    label = button_reply.get("title", "")
    logger.info(
        "User submitted rating",
        extra={"phone_number": phone_number, "rating": label},
    )
    data["bot_response"] = [
        {
            "type": "text",
            "text": "Thank you for your feedback! We're glad to have helped you.",
        }
    ]


def _is_delegated_button(msgid: str) -> bool:
    """True if another processor should handle this button."""
    prefixes = ("buy$", "preorder$", "track$", "details$", "product$")
    return any(msgid.startswith(p) for p in prefixes)


class ServiceList(Processor):
    """Processor for sending and routing the main service menu."""

    def should_run(self, data: dict) -> bool:
        """Run when no bot_response has been set yet."""
        return "bot_response" not in data

    async def process(self, data: dict) -> dict:
        """Handle menu display, list selections, and menu-related buttons."""
        user_profile = data["user_profile"]
        messages = data.get("messages", {})
        phone_number = data["phone_number"]

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
            logger.info(
                "Service list request",
                extra={"phone_number": phone_number},
            )

            interactive = messages.get("interactive", {})

            if interactive.get("type") == "button_reply":
                button_reply = interactive.get("button_reply", {})
                raw_id = button_reply.get("id", "")
                btn_msgid = _parse_button_msgid(raw_id)

                if btn_msgid == QuickReplyId.FLOW_SWITCH_CONFIRM.value:
                    data["_flow_switch_button_title"] = button_reply.get("title", "")
                    if handle_flow_switch_quick_reply(btn_msgid, user_profile, data):
                        return data

                if btn_msgid in _CLARIFY_MSGIDS:
                    data["_clarify_button_title"] = button_reply.get("title", "")
                    if btn_msgid == QuickReplyId.NON_TEXT_BROWSE.value:
                        data["_non_text_button_title"] = button_reply.get("title", "")
                        if handle_non_text_quick_reply(btn_msgid, user_profile, data):
                            return data
                    elif handle_clarification_quick_reply(btn_msgid, user_profile, data):
                        return data

                if btn_msgid == "menu$back":
                    user_profile["service_selected"] = ""
                    data["bot_response"] = [build_main_menu_bot_response()]
                    logger.info(
                        "Text help sent via menu$back",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if btn_msgid == QuickReplyId.RATING_REQUEST.value:
                    _handle_rating_button(button_reply, data, phone_number)
                    return data

                if btn_msgid == QuickReplyId.COMPLAINT_REGISTER.value:
                    data["bot_response"] = [build_complaint_flow_bot_response()]
                    return data

                if btn_msgid in (HELP_CALLBACK_QR_MSGID, HELP_CALLBACK_POSTBACK):
                    _handle_help_center_selection(
                        HELP_CALLBACK_POSTBACK,
                        user_profile,
                        data,
                        phone_number,
                    )
                    return data

                if _is_delegated_button(btn_msgid):
                    return data

            parsed = _parse_list_reply(messages)
            if parsed:
                list_msgid, title, postback = parsed
                logger.info(
                    "List reply received",
                    extra={
                        "phone_number": phone_number,
                        "list_msgid": list_msgid,
                        "title": title,
                        "postback": postback,
                    },
                )

                if list_msgid.startswith("variant_select$"):
                    user_profile["service_selected"] = SL.PRE_ORDER.value
                    return data

                if list_msgid.startswith("product_select$"):
                    user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                    return data

                if list_msgid == _EXPLORE_CAT_LIST_MSGID:
                    user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                    return data

                if list_msgid.startswith("help$") or (postback or "").startswith("help$"):
                    if list_msgid == _HELP_CENTER_MSGID and not postback:
                        user_profile["service_selected"] = ""
                        data["bot_response"] = [build_main_menu_bot_response()]
                    else:
                        _handle_help_center_selection(
                            postback or list_msgid,
                            user_profile,
                            data,
                            phone_number,
                        )
                    return data

                if list_msgid == ListIds.SERVICE_LIST_ID.value or postback:
                    logger.info(
                        "User selected menu option",
                        extra={
                            "phone_number": phone_number,
                            "title": title,
                            "postback": postback,
                        },
                    )
                    _handle_menu_selection(
                        title, user_profile, data, postback, phone_number
                    )
                    return data

            if user_profile.get("service_selected", "") == "":
                logger.info(
                    "Sending text help (no service selected)",
                    extra={"phone_number": phone_number},
                )
                data["bot_response"] = [build_main_menu_bot_response()]

            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in ServiceList",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
