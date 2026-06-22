import json
import re

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_GENERIC_ERROR = "Sorry, we couldn't load tracking right now. Please try again."


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


def _parse_track_button_id(raw_id: str) -> str | None:
    """Return order_id if button id/msgid starts with track$, else None."""
    btn_msgid = _parse_button_msgid(raw_id)
    if btn_msgid.startswith("track$"):
        return btn_msgid.split("$", 1)[1]
    return None


def _is_track_button(interactive: dict) -> bool:
    if interactive.get("type") != "button_reply":
        return False
    raw_id = interactive.get("button_reply", {}).get("id", "")
    return _parse_track_button_id(raw_id) is not None


def _extract_order_id_from_text(text: str) -> str | None:
    """Extract order ID from user message using simple patterns."""
    text = (text or "").strip()
    if not text:
        return None

    match = re.search(r"#([A-Za-z0-9-]+)", text)
    if match:
        return match.group(1)

    match = re.search(
        r"(?:order|track)\s*(?:id|#|:)?\s*([A-Za-z0-9-]+)",
        text,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)

    match = re.search(r"\b([A-Z]{2,}\d{3,}[A-Za-z0-9-]*)\b", text)
    if match:
        return match.group(1)

    return None


def _resolve_order_id(data: dict, messages: dict) -> str | None:
    """Resolve order_id from track$ button or text message body."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") == "button_reply":
        raw_id = interactive.get("button_reply", {}).get("id", "")
        order_id = _parse_track_button_id(raw_id)
        if order_id:
            return order_id

    text_body = messages.get("text", {}).get("body")
    if text_body:
        return _extract_order_id_from_text(text_body)

    return None


def _build_tracking_response(order_id: str, tracking_url: str) -> list:
    return [
        {
            "type": "cta_url",
            "text": (
                f"Order *{order_id}* — click below to track your order "
                "in real-time. 🚚"
            ),
            "display_text": "Track Your Order",
            "url": tracking_url,
        },
    ]


def _build_generic_tracking_response(tracking_url: str) -> list:
    return [
        {
            "type": "cta_url",
            "text": "Click below to track your order in real-time. 🚚",
            "display_text": "Track Your Order",
            "url": tracking_url,
        },
    ]


def build_track_order_bot_response(
    order_id: str | None = None,
    client_id: str = "kisna",
) -> list:
    """Shared tracking CTA for menu taps and order_tracking agent."""
    client_config = get_client_config(client_id)
    adapter = ClientAPIAdapter(client_config)
    tracking_url = adapter.get_order_tracking_url(order_id or "")
    if order_id:
        return _build_tracking_response(order_id, tracking_url)
    return _build_generic_tracking_response(tracking_url)


def _build_error_response(text: str) -> list:
    return [{"type": "text", "text": text}]


class OrderTrackingAgent(Processor):
    """Handles order tracking via track$ buttons or order_tracking intent."""

    def should_run(self, data: dict) -> bool:
        """Run for order_tracking category or track$ button taps."""
        if "bot_response" in data:
            return False

        client_config = data.get("client_config") or get_client_config(
            data.get("client_id", "kisna")
        )
        if not client_config.has_order_tracking:
            return False

        messages = data.get("messages", {})
        interactive = messages.get("interactive", {})

        user_profile = data.get("user_profile", {})
        if data.get("classified_category") == "order_tracking":
            return True
        if user_profile.get("service_selected") == "order_tracking":
            return True

        return _is_track_button(interactive)

    async def process(self, data: dict) -> dict:
        """Resolve order ID and return tracking CTA URL."""
        phone_number = data["phone_number"]
        user_profile = data.get("user_profile", {})
        messages = data.get("messages", {})
        client_id = data.get("client_id", "kisna")
        client_config = data.get("client_config") or get_client_config(client_id)

        if not self.should_run(data):
            logger.info(
                "Skipping processor",
                extra={
                    "processor": self.__class__.__name__,
                    "phone_number": phone_number,
                },
            )
            return data

        order_id = _resolve_order_id(data, messages)

        adapter = ClientAPIAdapter(client_config)
        try:
            logger.info(
                "Order tracking requested",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "client_id": client_id,
                },
            )

            tracking_url = adapter.get_order_tracking_url(order_id or "")
            if order_id:
                data["bot_response"] = _build_tracking_response(order_id, tracking_url)
            else:
                data["bot_response"] = _build_generic_tracking_response(tracking_url)

            logger.info(
                "Order tracking URL generated",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "client_id": client_id,
                },
            )
            user_profile["service_selected"] = ""
            return data

        except ValueError as e:
            logger.error(
                "Order tracking URL configuration error",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "error": str(e),
                },
            )
            data["bot_response"] = _build_error_response(_GENERIC_ERROR)
            return data
        except Exception as e:
            logger.exception(
                "Exception occurred in OrderTrackingAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = _build_error_response(_GENERIC_ERROR)
            return data
        finally:
            await adapter.aclose()
