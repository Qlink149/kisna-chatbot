import json

from kisna_chatbot.config.gupshup import get_damage_complaint_flow_id
from kisna_chatbot.models.enums import FLowId, FlowId, ListIds, QuickReplyId
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.order_tracking_agent import build_track_order_bot_response
from kisna_chatbot.utils.logger_config import logger

_GENERIC_ERROR = "Apologies — something went wrong on my end. Could you please try again?"

_MENU_BODY = (
    "You can pick an option from the menu below, or simply type what's on your mind — "
    "whether that's \"gold earrings under ₹80,000\" or \"what's your return policy\" — I'll understand."
)

_EXPLORE_CAT_LIST_MSGID = "search$cat$list"
_PREF_STEP1_MSGID = "pref$step1$list"
_PREF_STEP2_MSGID = "pref$step2$list"
_PREF_STEP3_MSGID = "pref$step3$list"

_FIND_STORE_TEXT = (
    "Share your pincode or city and I'll help you find the nearest Kisna store."
)

_WELCOME_TEXT = (
    "✨ Namaste! Welcome to Kisna Diamond & Gold. 💎\n"
    "I'm KIA, your personal jewellery assistant — here to help you discover the perfect piece, find answers, and make your Kisna experience truly special."
)

_WELCOME_BACK_TEXT = (
    "✨ Namaste! Welcome back to Kisna Diamond & Gold. 💎\n"
    "I'm KIA, your personal jewellery assistant — here to help you discover the perfect piece, find answers, and make your Kisna experience truly special."
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
    "• Support — +91 80651 55600, 9am–6pm Mon–Fri / 9am–4pm Sat\n\n"
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


def build_greeting_welcome_bot_responses(
    phone_number: str | None = None,
    chat_history: list | None = None,
) -> list[dict]:
    """Welcome for new users (text + menu) or returning users (text + menu)."""
    history = chat_history if chat_history is not None else []
    if is_new_session(history):
        return [
            {"type": "text", "text": _WELCOME_TEXT},
            _build_main_menu_list(),
        ]

    return [
        {"type": "text", "text": _WELCOME_BACK_TEXT},
        _build_main_menu_list(),
    ]


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
    data["bot_response"] = [build_explore_products_list_with_prompt()]
    return True


def build_main_menu_bot_response() -> dict:
    """Public menu builder used by other processors."""
    return _build_main_menu_list()


def build_acknowledgement_bot_response() -> list[dict]:
    """Lightweight thank-you / acknowledgement with next-step quick replies."""
    return [
        {
            "type": "quickreply",
            "text": (
                "You're welcome! Is there anything else I can help you with today? 💎"
            ),
            "caption": "",
            "options": [
                {"title": "Explore Products"},
                {"title": "View Offers"},
                {"title": "Open Menu"},
            ],
            "msgid": QuickReplyId.NON_TEXT_BROWSE.value,
        }
    ]


def build_complaint_flow_bot_response() -> dict:
    """WhatsApp Flow payload for damage / quality complaints."""
    return {
        "type": "flow",
        "flow": "damage_complaint",
        "text": "Please provide your order details and describe the issue.",
    }


def build_complaint_entry_cta_bot_response() -> dict:
    """Quick reply CTA that opens the complaint flow on click."""
    return {
        "type": "quickreply",
        "text": (
            "To register a complaint, tap *Register Complaint* below. "
            "It will open a form to capture your order details."
        ),
        "caption": "",
        "options": [{"title": "Register Complaint"}],
        "msgid": QuickReplyId.COMPLAINT_REGISTER.value,
    }


def _build_main_menu_list() -> dict:
    """Build WhatsApp list payload for the main service menu."""
    return {
        "type": "list",
        "list": "list",
        "body": _MENU_BODY,
        "footer": "Kisna",
        "msgid": ListIds.SERVICE_LIST_ID.value,
        "globalButtons": [{"type": "text", "title": "Open Menu"}],
        "items": [
            {
                "title": "How can we help?",
                "subtitle": "",
                "options": [
                    {
                        "type": "text",
                        "title": "Explore Products",
                        "description": "Browse rings, earrings, necklaces & more",
                        "postbackText": "explore_products",
                    },
                    {
                        "type": "text",
                        "title": "View Offers",
                        "description": "Discounts, bank offers & promo codes",
                        "postbackText": "view_offers",
                    },
                    {
                        "type": "text",
                        "title": "Find Store Near Me",
                        "description": "Locate your nearest Kisna showroom",
                        "postbackText": "find_store",
                    },
                    {
                        "type": "text",
                        "title": "Track My Order",
                        "description": "Check delivery status",
                        "postbackText": "track_order",
                    },
                    {
                        "type": "text",
                        "title": "Help / Complaint",
                        "description": "Report an issue with your order",
                        "postbackText": "raise_complaint",
                    },
                    {
                        "type": "text",
                        "title": "FAQs / About Kisna",
                        "description": "Returns, delivery, care & contact",
                        "postbackText": "faqs_help",
                    },
                ],
            }
        ],
    }


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
        "help / complaint": "raise_complaint",
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
    user_profile["shown_product_ids"] = []
    user_profile["pref_material"] = None
    user_profile["pref_type"] = None
    user_profile.pop("pref_category", None)
    user_profile.pop("pending_explore_search", None)


def build_pref_step1_material_list() -> dict:
    """Step 1 — material preference list (fresh Explore Products)."""
    return {
        "type": "list",
        "list": "list",
        "body": "What material are you looking for? 💎",
        "footer": "KISNA Diamond & Gold",
        "msgid": _PREF_STEP1_MSGID,
        "globalButtons": [{"type": "text", "title": "Choose Material"}],
        "items": [
            {
                "title": "Materials",
                "subtitle": "",
                "options": [
                    {
                        "type": "text",
                        "title": "Gold",
                        "description": "Hallmarked gold jewellery",
                        "postbackText": "pref$material$gold",
                    },
                    {
                        "type": "text",
                        "title": "Diamond",
                        "description": "Certified diamond pieces",
                        "postbackText": "pref$material$diamond",
                    },
                    {
                        "type": "text",
                        "title": "Gemstone",
                        "description": "Ruby, emerald & more",
                        "postbackText": "pref$material$gemstone",
                    },
                ],
            }
        ],
    }


def build_pref_step2_type_list() -> dict:
    """Step 2 — jewellery type preference list."""
    return {
        "type": "list",
        "list": "list",
        "body": "What type of jewellery? ✨",
        "footer": "KISNA Diamond & Gold",
        "msgid": _PREF_STEP2_MSGID,
        "globalButtons": [{"type": "text", "title": "Choose Type"}],
        "items": [
            {
                "title": "Types",
                "subtitle": "",
                "options": [
                    {
                        "type": "text",
                        "title": "Rings",
                        "description": "Gold & diamond rings",
                        "postbackText": "pref$type$ring",
                    },
                    {
                        "type": "text",
                        "title": "Earrings",
                        "description": "Studs, hoops & jhumkas",
                        "postbackText": "pref$type$earring",
                    },
                    {
                        "type": "text",
                        "title": "Necklace",
                        "description": "Chains & haars",
                        "postbackText": "pref$type$necklace",
                    },
                    {
                        "type": "text",
                        "title": "Pendants",
                        "description": "Lockets & charms",
                        "postbackText": "pref$type$pendant",
                    },
                    {
                        "type": "text",
                        "title": "Bracelets",
                        "description": "Kadas & cuffs",
                        "postbackText": "pref$type$bracelet",
                    },
                    {
                        "type": "text",
                        "title": "Bangles",
                        "description": "Traditional bangles",
                        "postbackText": "pref$type$bangle",
                    },
                    {
                        "type": "text",
                        "title": "Mangalsutra",
                        "description": "Bridal mangalsutra",
                        "postbackText": "pref$type$mangalsutra",
                    },
                ],
            }
        ],
    }


def build_pref_step3_budget_list() -> dict:
    """Step 3 — budget preference list."""
    return {
        "type": "list",
        "list": "list",
        "body": "What's your budget? 💰",
        "footer": "KISNA Diamond & Gold",
        "msgid": _PREF_STEP3_MSGID,
        "globalButtons": [{"type": "text", "title": "Choose Budget"}],
        "items": [
            {
                "title": "Budget",
                "subtitle": "",
                "options": [
                    {
                        "type": "text",
                        "title": "Under ₹10,000",
                        "description": "Budget-friendly picks",
                        "postbackText": "pref$budget$0-10000",
                    },
                    {
                        "type": "text",
                        "title": "₹10k – ₹20k",
                        "description": "Everyday elegance",
                        "postbackText": "pref$budget$10000-20000",
                    },
                    {
                        "type": "text",
                        "title": "₹20k – ₹30k",
                        "description": "Mid-range favourites",
                        "postbackText": "pref$budget$20000-30000",
                    },
                    {
                        "type": "text",
                        "title": "₹30k – ₹40k",
                        "description": "Premium selection",
                        "postbackText": "pref$budget$30000-40000",
                    },
                    {
                        "type": "text",
                        "title": "₹40k – ₹50k",
                        "description": "Statement pieces",
                        "postbackText": "pref$budget$40000-50000",
                    },
                    {
                        "type": "text",
                        "title": "₹50k & above",
                        "description": "Luxury collection",
                        "postbackText": "pref$budget$50000-9999999",
                    },
                    {
                        "type": "text",
                        "title": "Type my range",
                        "description": "Enter a custom budget",
                        "postbackText": "pref$budget$custom",
                    },
                ],
            }
        ],
    }


def build_custom_budget_prompt() -> dict:
    """Prompt user to type a custom budget after pref step 3."""
    return {
        "type": "text",
        "text": (
            "Please type your budget, e.g.:\n"
            "• '25000' (we'll find products around ₹25k)\n"
            "• '15000-35000' (range)\n"
            "• '50000 tak' (up to ₹50k)"
        ),
    }


def build_explore_products_list() -> dict:
    """Public wrapper for the category browse list (Phase 3 explore menu)."""
    return _build_explore_products_list()


def build_explore_products_list_with_prompt() -> dict:
    """Category menu with vague-browse prompt body."""
    payload = _build_explore_products_list()
    payload["body"] = "What type of jewellery are you looking for?"
    return payload


_SERVICE_LABELS = {
    SL.PRODUCT_SEARCH.value: "jewellery browsing",
    SL.OFFERS.value: "offers",
    SL.ORDER_TRACKING.value: "order tracking",
    SL.RETURNS_REFUND.value: "returns and refunds",
    SL.COMPLAINT.value: "complaints",
    SL.AD_FLOW.value: "store locator",
    SL.GENERAL.value: "general help",
}


def build_flow_switch_bot_response(current_service: str, new_intent: str) -> list[dict]:
    """Return a quick-reply confirmation when switching between active flows."""
    new_intent = (new_intent or "").strip().lower()
    current_service = (current_service or "").strip()

    transitions: dict[tuple[str, str], tuple[str, str, str]] = {
        (SL.PRODUCT_SEARCH.value, "offers"): (
            "It looks like you're asking about offers!\n"
            "Want me to show you current deals?\n"
            "(Your jewellery browsing session will be saved)",
            "Yes, show offers",
            "No, keep browsing",
        ),
        (SL.PRODUCT_SEARCH.value, "order_tracking"): (
            "Want me to help you track your order?\n"
            "You can come back to browsing after.",
            "Yes, track order",
            "No, keep browsing",
        ),
        (SL.PRODUCT_SEARCH.value, "returns_refund"): (
            "I can help with returns and refunds.\n"
            "Should I switch to that?",
            "Yes, help with return",
            "No, keep browsing",
        ),
        (SL.PRODUCT_SEARCH.value, "complaint"): (
            "I can help you report an issue with your order.\n"
            "Should I switch to that?",
            "Yes, report issue",
            "No, keep browsing",
        ),
        (SL.PRODUCT_SEARCH.value, "store_info"): (
            "Looking for a KISNA store near you?",
            "Yes, find a store",
            "No, keep browsing",
        ),
        (SL.OFFERS.value, "product_search"): (
            "Want to browse jewellery?\n"
            "I'll switch from offers to the catalogue.",
            "Yes, browse jewellery",
            "No, stay on offers",
        ),
        (SL.AD_FLOW.value, "product_search"): (
            "You were looking for a store near you —\n"
            "want me to switch and help you with that instead?",
            "Yes, switch",
            "No, find store",
        ),
        (SL.AD_FLOW.value, "offers"): (
            "You were looking for a store near you —\n"
            "want me to switch and help you with that instead?",
            "Yes, switch",
            "No, find store",
        ),
        (SL.AD_FLOW.value, "order_tracking"): (
            "You were looking for a store near you —\n"
            "want me to switch and help you with that instead?",
            "Yes, switch",
            "No, find store",
        ),
    }

    text, yes_label, no_label = transitions.get(
        (current_service, new_intent),
        (
            f"Shall I switch from {_SERVICE_LABELS.get(current_service, current_service)} "
            "to help with that?",
            "Yes, switch",
            "No, continue",
        ),
    )

    return [
        {
            "type": "quickreply",
            "text": text,
            "caption": "",
            "options": [{"title": yes_label}, {"title": no_label}],
            "msgid": QuickReplyId.FLOW_SWITCH_CONFIRM.value,
        }
    ]


def handle_flow_switch_quick_reply(
    btn_msgid: str, user_profile: dict, data: dict
) -> bool:
    """Route flow-switch quick-reply taps; return True if handled."""
    if btn_msgid != QuickReplyId.FLOW_SWITCH_CONFIRM.value:
        return False

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
        data["bot_response"].append(build_explore_products_list_with_prompt())
    return True


def build_clarification_bot_response(intent: str, confidence: float) -> list[dict]:
    """Return one quick-reply clarification message for low-confidence classification."""
    intent = (intent or "").strip().lower()
    conf = float(confidence or 0)

    if conf < 0.3:
        return [
            {
                "type": "quickreply",
                "text": (
                    "I want to make sure I help you correctly!\n"
                    "What would you like to do today?"
                ),
                "caption": "",
                "options": [
                    {"title": "Browse Jewellery"},
                    {"title": "View Offers"},
                    {"title": "Track Order"},
                    {"title": "Find Store"},
                    {"title": "Ask a Question"},
                ],
                "msgid": QuickReplyId.CLARIFY_BROWSE.value,
            }
        ]

    if intent in ("store_info",):
        return [
            {
                "type": "quickreply",
                "text": "Are you looking for a KISNA store near you?",
                "caption": "",
                "options": [
                    {"title": "Yes, find a store"},
                    {"title": "No, something else"},
                ],
                "msgid": QuickReplyId.CLARIFY_STORE_YES.value,
            }
        ]

    if intent in ("order_tracking", "complaint", "returns_refund"):
        return [
            {
                "type": "quickreply",
                "text": (
                    "Is this about tracking an existing order, or reporting an issue?"
                ),
                "caption": "",
                "options": [
                    {"title": "Track my order"},
                    {"title": "Report a problem"},
                ],
                "msgid": QuickReplyId.CLARIFY_TRACK.value,
            }
        ]

    if intent in ("offers",) or (
        intent == "product_search" and conf < 0.42
    ):
        return [
            {
                "type": "quickreply",
                "text": "Are you looking for jewellery to browse, or current offers?",
                "caption": "",
                "options": [
                    {"title": "Browse jewellery"},
                    {"title": "See offers"},
                ],
                "msgid": QuickReplyId.CLARIFY_OFFERS.value,
            }
        ]

    return [
        {
            "type": "quickreply",
            "text": (
                "Are you looking for a specific jewellery piece, or did you "
                "have a question about KISNA's policies?"
            ),
            "caption": "",
            "options": [
                {"title": "Browse Jewellery"},
                {"title": "Ask a Question"},
            ],
            "msgid": QuickReplyId.CLARIFY_BROWSE.value,
        }
    ]


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
        data["bot_response"] = [build_explore_products_list_with_prompt()]
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
        data["bot_response"] = [build_explore_products_list_with_prompt()]
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


def _build_explore_products_list() -> dict:
    """Category browse list shown when user taps Explore Products."""
    return build_main_category_list()


def build_main_category_list() -> dict:
    """Main 9-row category list for Explore Products."""
    return {
        "type": "list",
        "list": "list",
        "body": "What are you looking for? Tap a category to browse 💎",
        "footer": "KISNA Diamond & Gold",
        "msgid": _EXPLORE_CAT_LIST_MSGID,
        "globalButtons": [{"type": "text", "title": "Select Category"}],
        "items": [
            {
                "title": "Categories",
                "subtitle": "",
                "options": [
                    {
                        "type": "text",
                        "title": "Rings",
                        "description": "Gold, diamond & solitaires",
                        "postbackText": "pref$cat$ring",
                    },
                    {
                        "type": "text",
                        "title": "Earrings",
                        "description": "Studs, hoops & jhumkas",
                        "postbackText": "pref$cat$earring",
                    },
                    {
                        "type": "text",
                        "title": "Necklaces & Chains",
                        "description": "Sets, layered chains & more",
                        "postbackText": "pref$cat$necklace",
                    },
                    {
                        "type": "text",
                        "title": "Pendants",
                        "description": "Gold & diamond lockets",
                        "postbackText": "pref$cat$pendant",
                    },
                    {
                        "type": "text",
                        "title": "Bangles & Bracelets",
                        "description": "Kadas, cuffs & adjustable bands",
                        "postbackText": "pref$cat$bangle_bracelet",
                    },
                    {
                        "type": "text",
                        "title": "Mangalsutra",
                        "description": "Traditional & modern styles",
                        "postbackText": "pref$cat$mangalsutra",
                    },
                    {
                        "type": "text",
                        "title": "Maang Tikka",
                        "description": "Bridal & everyday wear",
                        "postbackText": "pref$cat$maang_tikka",
                    },
                    {
                        "type": "text",
                        "title": "Other Jewellery",
                        "description": "Solitaire, Nose Ring, Watch, Chain, Sets...",
                        "postbackText": "pref$cat$other",
                    },
                    {
                        "type": "text",
                        "title": "Browse All",
                        "description": "See the full KISNA collection",
                        "postbackText": "pref$cat$any",
                    },
                ],
            }
        ],
    }


def build_other_jewellery_list() -> dict:
    """Secondary category list for Other Jewellery."""
    return {
        "type": "list",
        "list": "list",
        "body": "Choose a specific jewellery type:",
        "footer": "KISNA Diamond & Gold",
        "msgid": "pref$cat$other$list",
        "globalButtons": [{"type": "text", "title": "Select"}],
        "items": [
            {
                "title": "More Categories",
                "subtitle": "",
                "options": [
                    {
                        "type": "text",
                        "title": "Solitaire Rings",
                        "description": "Diamond solitaire collection",
                        "postbackText": "pref$cat$solitaire",
                    },
                    {
                        "type": "text",
                        "title": "Nose Wear",
                        "description": "Nose pins & nose rings",
                        "postbackText": "pref$cat$nose_wear",
                    },
                    {
                        "type": "text",
                        "title": "Watch Wear",
                        "description": "Watches & accessories",
                        "postbackText": "pref$cat$watch_wear",
                    },
                    {
                        "type": "text",
                        "title": "Mangalsutra Bracelets",
                        "description": "Mangalsutra in bracelet style",
                        "postbackText": "pref$cat$mangalsutra_bracelet",
                    },
                    {
                        "type": "text",
                        "title": "Pendant Sets",
                        "description": "Necklace & pendant set combos",
                        "postbackText": "pref$cat$pendant_set",
                    },
                    {
                        "type": "text",
                        "title": "Necklace Sets",
                        "description": "Matching necklace & earring sets",
                        "postbackText": "pref$cat$necklace_set",
                    },
                    {
                        "type": "text",
                        "title": "← Back to Categories",
                        "description": "Go back to main category list",
                        "postbackText": "pref$cat$back",
                    },
                ],
            }
        ],
    }


def _build_rating_quickreply() -> dict:
    return {
        "type": "quickreply",
        "text": "How was your experience with Kisna?",
        "caption": "",
        "options": [
            {"title": "1"},
            {"title": "2"},
            {"title": "3"},
            {"title": "4"},
            {"title": "5"},
        ],
        "msgid": QuickReplyId.RATING_REQUEST.value,
    }


def _is_product_search_postback(postback: str) -> bool:
    """True if list postback should be handled by ProductSearchAgentV3."""
    postback = (postback or "").strip()
    return postback.startswith("search$") or postback.startswith("pref$")


def _handle_menu_selection(title: str, user_profile: dict, data: dict, postback: str = "") -> None:
    """Route Kisna main menu selection (legacy postbacks mapped via aliases)."""
    if _is_product_search_postback(postback):
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        return

    key = _normalize_menu_key(title, postback)

    if key in ("explore_products",):
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        _clear_explore_browse_session(user_profile)
        data["bot_response"] = [_build_explore_products_list()]
        return

    if key in ("view_offers",):
        user_profile["service_selected"] = SL.OFFERS.value
        data["classified_category"] = "offers"
        return

    if key in ("find_store", "store_info"):
        user_profile["service_selected"] = SL.AD_FLOW.value
        user_profile["awaiting_store_pincode"] = True
        data["bot_response"] = [{"type": "text", "text": _FIND_STORE_TEXT}]
        return

    if key in ("track_order",):
        user_profile["service_selected"] = SL.ORDER_TRACKING.value
        data["bot_response"] = build_track_order_bot_response()
        return

    if key in ("raise_complaint", "damage_complaint", "complaint"):
        user_profile["service_selected"] = SL.COMPLAINT.value
        data["bot_response"] = [build_complaint_flow_bot_response()]
        return

    if key in ("faqs_help",):
        user_profile["service_selected"] = SL.GENERAL.value
        data["bot_response"] = [{"type": "text", "text": _FAQ_TEXT}]
        return

    logger.warning(
        "Unknown service list selection",
        extra={"title": title, "postback": postback, "key": key},
    )
    data["bot_response"] = [
        {
            "type": "text",
            "text": (
                "Sorry, I didn't recognize that option. "
                "Type *hi* to open the menu again."
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

            # ── nfm_reply: WhatsApp Flow form submission ──────────────────────
            # This is the ONLY message type that carries completed form data.
            # We must detect it here and set service_selected so main.py routes
            # to the correct pipeline (ComplaintPipeline). Without this block,
            # the nfm_reply falls through with service_selected unchanged and
            # the complaint is never saved. This mirrors the NKL production pattern.
            nfm_payload = interactive.get("nfm_reply") or messages.get("nfm_reply")
            if nfm_payload:
                if nfm_payload.get("name") == "flow":
                    try:
                        flow_data = json.loads(nfm_payload.get("response_json", "{}"))
                        flow_token = flow_data.get("flow_token", "")
                        complaint_tokens = {
                            FLowId.DAMAGE_COMPLAINT.value,
                            FlowId.COMPLAINT_FLOW.value,
                            get_damage_complaint_flow_id(),
                        }
                        if flow_token in complaint_tokens:
                            logger.info(
                                "nfm_reply complaint flow submission detected — routing to ComplaintPipeline",
                                extra={"phone_number": phone_number, "flow_token": flow_token},
                            )
                            user_profile["service_selected"] = SL.COMPLAINT.value
                            return data
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(
                            "Failed to parse nfm_reply response_json in ServiceList",
                            extra={"phone_number": phone_number, "error": str(e)},
                        )
            # ─────────────────────────────────────────────────────────────────

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
                    data["bot_response"] = [_build_main_menu_list()]
                    logger.info(
                        "Main menu sent via menu$back",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if btn_msgid == QuickReplyId.RATING_REQUEST.value:
                    _handle_rating_button(button_reply, data, phone_number)
                    return data

                if btn_msgid == QuickReplyId.COMPLAINT_REGISTER.value:
                    data["bot_response"] = [build_complaint_flow_bot_response()]
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

                if list_msgid == ListIds.SERVICE_LIST_ID.value or postback:
                    logger.info(
                        "User selected menu option",
                        extra={
                            "phone_number": phone_number,
                            "title": title,
                            "postback": postback,
                        },
                    )
                    _handle_menu_selection(title, user_profile, data, postback)
                    return data

            if user_profile.get("service_selected", "") == "":
                logger.info(
                    "Sending service list",
                    extra={"phone_number": phone_number},
                )
                data["bot_response"] = [_build_main_menu_list()]

            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in ServiceList",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
