import json

from kisna_chatbot.integrations.clara_api import ClaraAPIError, search_products
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.product_search_agent_v3 import (
    _build_search_success_response,
    build_product_media_message,
)
from kisna_chatbot.processors.entity_extractor import (
    entities_to_api_params,
    extract_entities,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.product_formatter import format_product_image_caption

_RETRY_SEARCH_TEXT = "Let me search for that again."
_SEARCH_ERROR_TEXT = (
    "Sorry, we couldn't search the catalogue right now. Please try again."
)
_CACHE_MISS_TEXT = (
    "Sorry, we couldn't find that product. Try searching again from the menu."
)


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


def _parse_product_list_selection(messages: dict) -> tuple[str | None, str]:
    """Extract product_id and list row title from product search results list."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return None, ""

    list_reply = interactive.get("list_reply", {})
    raw_id = list_reply.get("id", "")
    title = (list_reply.get("title") or "").strip()
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
        return None, title
    if product_id:
        return str(product_id), title
    return None, title


def _find_cached_product(user_profile: dict, product_id: str) -> dict | None:
    for product in user_profile.get("last_search_products") or []:
        if not isinstance(product, dict):
            continue
        pid = product.get("_id") or product.get("id")
        if pid and str(pid) == str(product_id):
            return product
    return None


def _build_cached_product_response(product: dict) -> list:
    media = build_product_media_message(product)
    if media:
        return [media]
    caption = format_product_image_caption(product)
    return [{"type": "text", "text": caption}]


async def _retry_product_search(
    data: dict,
    query: str,
) -> list | None:
    """Run a fresh catalog search and return bot_response items."""
    if not query.strip():
        return None

    try:
        entities = extract_entities(query)
        api_params = entities_to_api_params(entities)
        if not api_params.get("title") and query.strip():
            api_params = {**api_params, "title": query.strip()}

        result = await search_products(**api_params, page_no=1, page_size=5)
    except ClaraAPIError:
        return [{"type": "text", "text": _SEARCH_ERROR_TEXT}]
    except Exception:
        logger.exception("Product details retry search failed")
        return [{"type": "text", "text": _SEARCH_ERROR_TEXT}]

    products = result.get("products") or []
    total_count = result.get("total_count", 0)
    page = result.get("page", 1)

    user_profile = data.get("user_profile", {})
    user_profile["last_search_products"] = products[:5]
    user_profile["last_search_filters"] = entities
    user_profile["last_search_page"] = page
    user_profile["last_search_total"] = total_count

    if not products:
        return [{"type": "text", "text": "No matching pieces found. Try another search."}]

    search_items = _build_search_success_response(products, total_count, page, entities)
    return [{"type": "text", "text": _RETRY_SEARCH_TEXT}, *search_items]


class ProductDetailsAgent(Processor):
    """Handles product detail view when user taps a product from search results."""

    def should_run(self, data: dict) -> bool:
        """Run for details$ buttons or product search list selections."""
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        product_id, _ = _parse_product_list_selection(messages)
        if product_id:
            return True

        interactive = messages.get("interactive", {})
        if interactive.get("type") != "button_reply":
            return False

        button_reply = interactive.get("button_reply", {})
        raw_id = button_reply.get("id", "")
        return _parse_details_button_id(raw_id) is not None

    async def process(self, data: dict) -> dict:
        """Serve product details from cached search results (no GET by product ID)."""
        phone_number = data["phone_number"]
        messages = data.get("messages", {})

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
            list_product_id, list_title = _parse_product_list_selection(messages)
            product_id = list_product_id
            is_list_selection = bool(list_product_id)

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

            user_profile = data.get("user_profile", {})
            cached = _find_cached_product(user_profile, product_id)

            if cached:
                data["bot_response"] = _build_cached_product_response(cached)
                logger.info(
                    "Product details from cache",
                    extra={
                        "phone_number": phone_number,
                        "product_id": product_id,
                    },
                )
                return data

            if is_list_selection:
                retry = await _retry_product_search(data, list_title)
                if retry:
                    data["bot_response"] = retry
                    return data

            data["bot_response"] = [{"type": "text", "text": _CACHE_MISS_TEXT}]
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred while loading product details.",
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
