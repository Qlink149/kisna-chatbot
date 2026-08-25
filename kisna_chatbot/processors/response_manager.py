from kisna_chatbot.whatsapp_functions.cta.send_cta import send_cta_url
from kisna_chatbot.whatsapp_functions.flow.send_site_visit import (
    send_site_visit_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_budget_input_flow import (
    send_budget_input_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_callback_request_flow import (
    send_callback_request_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_damage_complaint import (
    send_damage_complaint_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_video_call_request_flow import (
    send_video_call_request_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_store_locator import (
    send_store_locator_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_store_visit_datetime import (
    send_store_visit_datetime_flow,
)
from kisna_chatbot.whatsapp_functions.list.send_service_list import (
    send_service_list,
)
from kisna_chatbot.whatsapp_functions.media.send_audio_message import (
    send_audio_message,
)
from kisna_chatbot.whatsapp_functions.media.send_document_message import (
    send_file_message,
)
from kisna_chatbot.whatsapp_functions.media.send_image_message import (
    send_image_message,
)
from kisna_chatbot.whatsapp_functions.media.send_image_with_cta import (
    send_image_with_cta,
)
from kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply import (
    send_quickreply_with_retry,
)
from kisna_chatbot.whatsapp_functions.list.send_list import send_list_with_retry
from kisna_chatbot.whatsapp_functions.send_text_message import (
    send_text_message_with_retry,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.rate_limiter import outbound_rate_limiter
from kisna_chatbot.utils.whatsapp_window import is_window_open
from kisna_chatbot.whatsapp_functions.send_kisna_welcome_template import (
    send_kisna_welcome_template,
)
import re
import time

# The LLM (GeneralAgent especially, but any free-generation path can do it)
# frequently reaches for standard Markdown **bold** despite prompt
# instructions -- confirmed live, 5/6 runs of one KB query used it, never
# the same message twice. WhatsApp's own bold syntax is a SINGLE asterisk
# pair (*bold*); a double pair renders as literal, visible asterisks (the
# reported bug) because WhatsApp's parser doesn't special-case "**" as an
# escaped single star. Fixed once, centrally, here -- every response type
# passes through this loop before send, so no per-prompt fix can miss a
# future free-generation path the way a prompt-only instruction can.
#
# **bold** was the first and loudest case, but a long FAQ answer ("Tell me
# everything about KMR in full detail") also shipped literal "### KMR Overview"
# headings and "[meriroshni.kisna.com](https://meriroshni.kisna.com)" link
# syntax, which WhatsApp renders verbatim -- brackets, parentheses and all.
# WhatsApp supports *bold*, _italic_, ~strike~ and ```mono``` ONLY.
_MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MARKDOWN_UNDERSCORE_BOLD_RE = re.compile(r"__(.+?)__")
# Heading -> bold on its own line. Applied per-line, so a "#" mid-sentence
# (or a hex colour) is left alone.
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
# [label](url) -> "label: url". WhatsApp auto-links a bare URL, so this drops
# the literal punctuation while keeping the destination tappable.
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(\s*<?([^)\s]+)>?\s*\)")
_MARKDOWN_AUTOLINK_RE = re.compile(r"<(https?://[^>\s]+)>")
# Leading "-" / "*" / "+" bullet -> "•". MUST run after the bold rules, or a
# line starting "**Note**" is mistaken for a bullet.
_MARKDOWN_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(?=\S)")
_MARKDOWN_FENCE_RE = re.compile(r"^\s*```[^\n]*$")


def _fix_whatsapp_markdown(text: str) -> str:
    """Rewrite Markdown into what WhatsApp actually renders."""
    if not text:
        return text

    text = _MARKDOWN_BOLD_RE.sub(r"*\1*", text)
    text = _MARKDOWN_UNDERSCORE_BOLD_RE.sub(r"*\1*", text)
    text = _MARKDOWN_LINK_RE.sub(
        lambda m: (
            m.group(2)
            if m.group(1).strip().rstrip("/").endswith(
                m.group(2).split("//")[-1].rstrip("/")
            )
            else f"{m.group(1)}: {m.group(2)}"
        ),
        text,
    )
    text = _MARKDOWN_AUTOLINK_RE.sub(r"\1", text)

    lines = []
    for line in text.split("\n"):
        if _MARKDOWN_FENCE_RE.match(line):
            continue
        heading = _MARKDOWN_HEADING_RE.match(line)
        if heading:
            title = heading.group(1).strip()
            # Don't double-wrap a heading the bold rule already starred.
            lines.append(title if title.startswith("*") else f"*{title}*")
            continue
        lines.append(_MARKDOWN_BULLET_RE.sub(r"\1• ", line))
    return "\n".join(lines)


def _sanitize_response_text(response: dict) -> dict:
    """Fix Markdown emphasis in every user-visible text field of one response."""
    for key in ("text", "caption"):
        value = response.get(key)
        if isinstance(value, str):
            response[key] = _fix_whatsapp_markdown(value)
    return response


class ResponseManager:
    """Singleton class to manage and send bot responses based on their type."""

    _instance = None

    def __new__(cls):
        """Ensures that only a single instance of the ResponseManager exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
            cls._instance._register_default_handlers()
        return cls._instance

    def _register_default_handlers(self):
        """Registers default handlers for known response types.

        New types can be added dynamically using the `register_handler` method.
        """
        self.register_handler("text", self._handle_text)
        self.register_handler("media", self._handle_media)
        self.register_handler("flow", self._handle_flow)
        self.register_handler("list", self._handle_list)
        self.register_handler("quickreply", self._handle_quick_reply)
        self.register_handler("skip", self._handle_skip)
        self.register_handler("cta_url", self._handle_url)
        self.register_handler("image_with_cta", self._handle_image_with_cta)

    def register_handler(self, response_type, handler):
        """Registers a handler for a specific response type.

        This allows adding new response types without modifying existing code.

        :param response_type: The type of response to handle (e.g., "text", "flow").
        :param handler: The function that handles this response type.
        """
        self._handlers[response_type] = handler

    def handle_responses(self, data):
        """Iterate through the list of bot responses and routes to its appropriate handler."""
        bot_responses = data.get("bot_response", [])
        phone_number = data["phone_number"]
        user_profile = data.get("user_profile") or {}

        if bot_responses and not is_window_open(user_profile):
            template_result = send_kisna_welcome_template(phone_number)
            if template_result is not None:
                data["_window_reopened"] = True
                time.sleep(0.4)

        for response in bot_responses:
            outbound_rate_limiter.wait_if_needed(phone_number)
            response = _sanitize_response_text(response)
            response_type = response.get("type")
            handler = self._handlers.get(response_type)

            if handler:
                try:
                    result = handler(phone_number=phone_number, bot_response=response)
                except Exception as exc:
                    # One flaky send must not swallow the rest of the turn: the
                    # senders re-raise on network errors, and an escaping
                    # exception used to drop every remaining card / CTA while
                    # the dashboard still showed the full saved response.
                    logger.exception(
                        "Failed to send bot_response — continuing with the rest",
                        extra={
                            "phone_number": phone_number,
                            "response_type": response_type,
                            "error": str(exc),
                        },
                    )
                    continue
                if result:
                    if result.get("status") != "submitted":
                        logger.warning(f"Message not confirmed: {result}")
                    else:
                        logger.info("message submitted")
                        time.sleep(0.4)
            else:
                logger.error(
                    "Unknown bot_response type: %s — skipping send",
                    response_type,
                    extra={
                        "phone_number": phone_number,
                        "response_type": response_type,
                        "response": response,
                    },
                )

    def _handle_text(self, phone_number, bot_response):
        """Processes text responses (e.g., sending cta urls).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return send_text_message_with_retry(
            phone_number=phone_number, bot_response=bot_response
        )

    def _handle_quick_reply(self, phone_number, bot_response):
        """Processes quick reply.

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return send_quickreply_with_retry(
            phone_number=phone_number, bot_response=bot_response
        )

    def _handle_skip(self, phone_number, bot_response):
        """Processes text responses (e.g., sending cta urls).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        logger.warning(
            "Skipping bot_response send (type=skip)",
            extra={"phone_number": phone_number},
        )
        return {"status": "submitted"}

    def _handle_url(self, phone_number, bot_response):
        """Processes text responses (e.g., sending cta urls).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return send_cta_url(phone_number=phone_number, bot_response=bot_response)

    def _handle_image_with_cta(self, phone_number, bot_response):
        """Processes product image responses with inline buy button."""
        return send_image_with_cta(
            phone_number=phone_number, bot_response=bot_response
        )

    def _handle_list(self, phone_number, bot_response):
        """Processes list responses (e.g., sending lists).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        list_name = bot_response["list"]
        if list_name == "service_list":
            # Legacy alias: main menu list is gone — send text help instead.
            from kisna_chatbot.processors.service_list import build_main_menu_bot_response
            from kisna_chatbot.whatsapp_functions.send_text_message import (
                send_text_message,
            )

            return send_text_message(
                phone_number=phone_number,
                bot_response=build_main_menu_bot_response(),
            )
        elif list_name == "list":
            return send_list_with_retry(
                phone_number=phone_number, bot_response=bot_response
            )
        else:
            raise ValueError(f"Unknown list: {list_name}")

    def _handle_flow(self, phone_number, bot_response):
        """Processes flow responses (e.g., sending registration flow).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        flow_name = bot_response["flow"]

        if flow_name == "site_visit":
            return send_site_visit_flow(phone_number=phone_number)
        elif flow_name == "damage_complaint":
            try:
                return send_damage_complaint_flow(phone_number=phone_number)
            except Exception as e:
                logger.exception(
                    "Failed to send damage complaint flow",
                    extra={"phone_number": phone_number, "error": str(e)},
                )
                return send_text_message_with_retry(
                    phone_number=phone_number,
                    bot_response={
                        "type": "text",
                        "text": (
                            "Sorry, we couldn't open the complaint form right now. "
                            "Please try again in a moment or type *human* for support."
                        ),
                    },
                )
        elif flow_name == "store_locator":
            return send_store_locator_flow(phone_number=phone_number, name=bot_response.get("name", "there"))
        elif flow_name == "store_visit_datetime":
            return send_store_visit_datetime_flow(phone_number=phone_number, bot_response=bot_response)
        elif flow_name == "budget_custom_input":
            try:
                return send_budget_input_flow(phone_number=phone_number)
            except Exception as e:
                logger.exception(
                    "Failed to send budget input flow",
                    extra={"phone_number": phone_number, "error": str(e)},
                )
                return send_text_message_with_retry(
                    phone_number=phone_number,
                    bot_response={
                        "type": "text",
                        "text": (
                            "Sorry, couldn't open the budget form right now. "
                            "Please type your budget, e.g. '25000', '15000-35000', or '1 lakh'."
                        ),
                    },
                )
        elif flow_name == "callback_request":
            result = send_callback_request_flow(phone_number=phone_number)
            if result is None:
                return send_text_message_with_retry(
                    phone_number=phone_number,
                    bot_response={
                        "type": "text",
                        "text": "Please share the mobile number we should call you on.",
                    },
                )
            return result
        elif flow_name == "video_call_request":
            result = send_video_call_request_flow(phone_number=phone_number)
            if result is None:
                return send_text_message_with_retry(
                    phone_number=phone_number,
                    bot_response={
                        "type": "text",
                        "text": "Please share the mobile number for your video call.",
                    },
                )
            return result
        else:
            raise ValueError(f"Unknown flow: {flow_name}")

    def _handle_media(self, phone_number, bot_response):
        """Processes media response.

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        media_type = bot_response["media_type"]
        if media_type == "image":
            return send_image_message(
                phone_number=phone_number, bot_response=bot_response
            )
        elif media_type == "doc":
            return send_file_message(
                phone_number=phone_number, bot_response=bot_response
            )
        elif media_type == "audio":
            return send_audio_message(
                phone_number=phone_number, bot_response=bot_response
            )
        else:
            raise ValueError(f"Unknown media type: {media_type}")
