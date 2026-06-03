import json
import re

from kisna_chatbot.integrations.clara_api import ClaraAPIError, search_products
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.product_search_agent_v3 import (
    _build_search_success_response,
)
from kisna_chatbot.processors.entity_extractor import (
    entities_to_api_params,
    extract_entities,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.product_formatter import (
    build_product_url,
    format_product_buy_caption,
    get_product_image_url,
)

_RETRY_SEARCH_TEXT = "Let me search for that again."
_SEARCH_ERROR_TEXT = (
    "Sorry, we couldn't search the catalogue right now. Please try again."
)
_CACHE_MISS_TEXT = (
    "Sorry, we couldn't find that product. Try searching again from the menu."
)
_BUY_CTA_TEXT = (
    "Tap below to view full details and place your order on the KISNA website."
)
_SIZE_VARIANT_REPLY = (
    "Sizes and variants are available on the product page. "
    "Tap 'Buy on KISNA' above to select your size and place your order."
)

_SIZE_QUERY_RE = re.compile(
    r"\b(size|sizes|variant|variants|karat|kt\b|available)\b",
    re.I,
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


def _save_last_viewed_product(user_profile: dict, product: dict) -> None:
    user_profile["last_viewed_product"] = {
        "_id": product.get("_id") or product.get("id"),
        "title": product.get("title"),
        "category": product.get("category"),
        "materialType": product.get("materialType"),
    }


def _build_buy_now_response(product: dict) -> list:
    """Image + Buy CTA + action quick replies for a cached product."""
    responses: list = []
    image_url = get_product_image_url(product)
    if image_url:
        responses.append(
            {
                "type": "media",
                "media_type": "image",
                "url": image_url,
                "caption": format_product_buy_caption(product),
            }
        )
    else:
        responses.append(
            {"type": "text", "text": format_product_buy_caption(product)}
        )

    responses.append(
        {
            "type": "cta_url",
            "text": _BUY_CTA_TEXT,
            "display_text": "Buy on KISNA",
            "url": build_product_url(product),
        }
    )

    responses.extend(
        [
            {
                "type": "quickreply",
                "text": "What would you like to do next?",
                "caption": "",
                "options": [{"title": "🔍 See Similar"}],
                "msgid": "product$similar",
            },
            {
                "type": "quickreply",
                "text": "Need a showroom?",
                "caption": "",
                "options": [{"title": "🏪 Find a Store"}],
                "msgid": "product$store",
            },
            {
                "type": "quickreply",
                "text": "Back to your search results:",
                "caption": "",
                "options": [{"title": "◀ Browse More"}],
                "msgid": "product$browse",
            },
        ]
    )
    return responses


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
        """Run for details$ buttons, list selections, or size questions after view."""
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        product_id, _ = _parse_product_list_selection(messages)
        if product_id:
            return True

        interactive = messages.get("interactive", {})
        if interactive.get("type") == "button_reply":
            raw_id = interactive.get("button_reply", {}).get("id", "")
            if _parse_details_button_id(raw_id):
                return True

        user_profile = data.get("user_profile", {})
        if user_profile.get("last_viewed_product") and data.get("classified_category") == "product_info":
            text = (messages.get("text", {}) or {}).get("body", "") or ""
            if text.strip() and _SIZE_QUERY_RE.search(text):
                return True

        return False

    async def process(self, data: dict) -> dict:
        """Serve product details from cached search results (no GET by product ID)."""
        phone_number = data["phone_number"]
        messages = data.get("messages", {})
        user_profile = data.get("user_profile", {})

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
            text_body = (messages.get("text", {}) or {}).get("body", "") or ""
            if (
                user_profile.get("last_viewed_product")
                and data.get("classified_category") == "product_info"
                and text_body.strip()
                and _SIZE_QUERY_RE.search(text_body)
                and not _parse_product_list_selection(messages)[0]
            ):
                data["bot_response"] = [{"type": "text", "text": _SIZE_VARIANT_REPLY}]
                return data

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

            cached = _find_cached_product(user_profile, product_id)

            if cached:
                _save_last_viewed_product(user_profile, cached)
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                data["bot_response"] = _build_buy_now_response(cached)
                logger.info(
                    "Product Buy Now flow from cache",
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
