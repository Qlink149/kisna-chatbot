import json

from kisna_chatbot.models.enums import ListIds, QuickReplyId
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.order_tracking_agent import build_track_order_bot_response
from kisna_chatbot.utils.logger_config import logger

_GENERIC_ERROR = "Something went wrong. Please try again."

_MENU_BODY = (
    "Hello! I'm your KISNA jewellery assistant.\n\n"
    "I can help you explore jewellery, check offers, find stores, track orders, "
    "and more. Pick an option below or just type your question."
)

_EXPLORE_CAT_LIST_MSGID = "search$cat$list"

_FIND_STORE_TEXT = (
    "Share your pincode or city and I'll help you find the nearest Kisna store."
)

_WELCOME_TEXT = (
    "Welcome to KISNA! I'm your jewellery assistant.\n"
    "Pick an option from the menu below, or type your question anytime."
)

_WELCOME_BACK_TEXT = (
    "Welcome back to KISNA! Great to see you again.\n"
    "Pick an option from the menu below, or type your question anytime."
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
    "*FAQs & Help*\n\n"
    "• *Returns & refunds* — Share your order ID and we'll guide you through the process.\n"
    "• *Delivery* — Standard delivery timelines apply; tracking is available once shipped.\n"
    "• *Care* — Product-specific care tips are on each item page.\n"
    "• *Contact* — Type *human* anytime to speak with our team.\n\n"
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
    """Welcome for new users (menu) or returning users (text + menu)."""
    history = chat_history if chat_history is not None else []
    if is_new_session(history):
        return [_build_main_menu_list()]

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
                        "title": "Raise a Complaint",
                        "description": "Report an issue with your order",
                        "postbackText": "raise_complaint",
                    },
                    {
                        "type": "text",
                        "title": "FAQs & Help",
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
        "locate store": "find_store",
        "locate_store": "find_store",
        "find store near me": "find_store",
        "explore products": "explore_products",
        "view offers": "view_offers",
        "track my order": "track_order",
        "faqs & help": "faqs_help",
    }
    return aliases.get(title_key, title_key)


def build_explore_products_list() -> dict:
    """Public wrapper for the category browse list (Phase 3 explore menu)."""
    return _build_explore_products_list()


def build_explore_products_list_with_prompt() -> dict:
    """Category menu with vague-browse prompt body."""
    payload = _build_explore_products_list()
    payload["body"] = "What type of jewellery are you looking for?"
    return payload


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
                        "description": "Gold & diamond rings",
                        "postbackText": "search$cat$ring",
                    },
                    {
                        "type": "text",
                        "title": "Earrings",
                        "description": "Studs, hoops & jhumkas",
                        "postbackText": "search$cat$earring",
                    },
                    {
                        "type": "text",
                        "title": "Necklaces",
                        "description": "Chains & haars",
                        "postbackText": "search$cat$necklace",
                    },
                    {
                        "type": "text",
                        "title": "Pendants",
                        "description": "Lockets & charms",
                        "postbackText": "search$cat$pendant",
                    },
                    {
                        "type": "text",
                        "title": "Bracelets",
                        "description": "Kadas & cuffs",
                        "postbackText": "search$cat$bracelet",
                    },
                    {
                        "type": "text",
                        "title": "Bangles",
                        "description": "Traditional bangles",
                        "postbackText": "search$cat$bangle",
                    },
                    {
                        "type": "text",
                        "title": "Mangalsutra",
                        "description": "Bridal mangalsutra",
                        "postbackText": "search$cat$mangalsutra",
                    },
                    {
                        "type": "text",
                        "title": "Browse All",
                        "description": "Top picks across categories",
                        "postbackText": "search$explore",
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
    return (postback or "").strip().startswith("search$")


def _handle_menu_selection(title: str, user_profile: dict, data: dict, postback: str = "") -> None:
    """Route Kisna main menu selection (legacy postbacks mapped via aliases)."""
    if _is_product_search_postback(postback):
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        return

    key = _normalize_menu_key(title, postback)

    if key in ("explore_products",):
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
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

            if interactive.get("type") == "button_reply":
                button_reply = interactive.get("button_reply", {})
                raw_id = button_reply.get("id", "")
                btn_msgid = _parse_button_msgid(raw_id)

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
