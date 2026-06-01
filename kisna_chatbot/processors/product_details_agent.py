import json

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter, ClientAPIError
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_MAX_MESSAGE_CHARS = 600


def _parse_details_button_id(raw_id: str) -> str | None:
    """Extract product_id from a details$ button id (plain or JSON-encoded)."""
    btn_msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            btn_msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass

    if isinstance(btn_msgid, str) and btn_msgid.startswith("details$"):
        return btn_msgid.split("$", 1)[1]
    return None


def _parse_product_list_selection(messages: dict) -> str | None:
    """Extract product_id when user picks a row from product search results list."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return None

    list_reply = interactive.get("list_reply", {})
    raw_id = list_reply.get("id", "")
    list_msgid = raw_id
    product_id = ""

    try:
        payload = json.loads(raw_id)
        if isinstance(payload, dict):
            list_msgid = payload.get("msgid", raw_id)
            product_id = payload.get("postbackText", "")
    except (json.JSONDecodeError, TypeError):
        pass

    if not isinstance(list_msgid, str) or not list_msgid.startswith("product_select$"):
        return None
    if product_id:
        return str(product_id)
    return None


def _format_price(price) -> str:
    if price is None or price == "":
        return "Price on request"
    return f"₹{price}"


def _format_availability(availability) -> str:
    if availability is True:
        return "In stock"
    if availability is False:
        return "Out of stock"
    if availability:
        return str(availability)
    return "Check with us"


def _format_specs(specs: dict, limit: int = 5) -> str:
    if not specs:
        return ""
    lines = []
    for key, value in list(specs.items())[:limit]:
        lines.append(f"• {key}: {value}")
    if not lines:
        return ""
    return "*Key specs:*\n" + "\n".join(lines)


def _build_details_text(product: dict) -> str:
    """Build WhatsApp markdown product details body (max 600 characters)."""
    title = product.get("title") or "Product"
    description = (product.get("description") or "").strip()
    price_line = _format_price(product.get("price"))
    rating = product.get("rating")
    reviews_count = product.get("reviews_count")
    availability_line = _format_availability(product.get("availability"))

    rating_line = "Not rated yet"
    if rating is not None:
        if reviews_count:
            rating_line = f"{rating} ({reviews_count} reviews)"
        else:
            rating_line = str(rating)

    parts = [
        f"*{title}*",
        "",
        description,
        "",
        f"💰 *Price:* {price_line}",
        f"⭐ *Rating:* {rating_line}",
        f"📦 *Availability:* {availability_line}",
    ]

    specs_block = _format_specs(product.get("specs") or {})
    if specs_block:
        parts.extend(["", specs_block])

    parts.extend(["", "_Tap below to continue._"])

    text = "\n".join(parts).strip()
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[: _MAX_MESSAGE_CHARS - 3].rstrip() + "..."
    return text


def _build_bot_response(product: dict, product_id: str) -> list:
    """Build bot_response list with details text and CTA quick replies."""
    details_text = _build_details_text(product)
    return [
        {"type": "text", "text": details_text},
        {
            "type": "quickreply",
            "text": "Ready to order this piece?",
            "caption": "",
            "options": [{"title": "Pre-Order Now"}],
            "msgid": f"preorder${product_id}",
        },
        {
            "type": "quickreply",
            "text": "Want to see more options?",
            "caption": "",
            "options": [{"title": "Back to Search"}],
            "msgid": "search$back",
        },
    ]


class ProductDetailsAgent(Processor):
    """Handles product detail view when user taps a View Details button."""

    def should_run(self, data: dict) -> bool:
        """Run for details$ buttons or product search list selections."""
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        if _parse_product_list_selection(messages):
            return True

        interactive = messages.get("interactive", {})
        if interactive.get("type") != "button_reply":
            return False

        button_reply = interactive.get("button_reply", {})
        raw_id = button_reply.get("id", "")
        return _parse_details_button_id(raw_id) is not None

    async def process(self, data: dict) -> dict:
        """Fetch product details and return formatted WhatsApp response."""
        phone_number = data["phone_number"]
        messages = data.get("messages", {})
        client_config = data.get("client_config") or get_client_config(
            data.get("client_id", "kisna")
        )

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
            product_id = _parse_product_list_selection(messages)
            if not product_id:
                interactive = messages.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    raw_id = interactive["button_reply"]["id"]
                    product_id = _parse_details_button_id(raw_id)
            if not product_id:
                logger.warning(
                    "Could not parse product id from interactive message",
                    extra={"phone_number": phone_number},
                )
                return data

            logger.info(
                "Product details requested",
                extra={
                    "phone_number": phone_number,
                    "product_id": product_id,
                    "client_id": client_config.client_id,
                },
            )

            adapter = ClientAPIAdapter(client_config)
            try:
                product = await adapter.get_product_details(product_id)
                data["bot_response"] = _build_bot_response(product, product_id)
                logger.info(
                    "Product details loaded",
                    extra={
                        "phone_number": phone_number,
                        "product_id": product_id,
                    },
                )
            finally:
                await adapter.aclose()

            return data
        except ClientAPIError as e:
            logger.exception(
                "Product details API error",
                extra={
                    "phone_number": phone_number,
                    "error": str(e),
                },
            )
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "Sorry, we couldn't load product details right now. "
                        "Please try again."
                    ),
                }
            ]
            return data
        except Exception as e:
            logger.exception(
                "Exception occured while loading product details.",
                extra={"exception": e, "phone_number": phone_number},
            )
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "Sorry, we couldn't load product details right now. "
                        "Please try again."
                    ),
                }
            ]
            return data
