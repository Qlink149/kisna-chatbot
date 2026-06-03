import json
import os

from kisna_chatbot.integrations.clara_api import ClaraAPIError, search_products
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.entity_extractor import (
    build_search_context,
    entities_to_api_params,
    extract_entities,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.product_formatter import (
    format_product_image_caption,
    format_product_list_message,
    format_zero_results_message,
    get_product_image_url,
)

_MAX_IMAGE_PRODUCTS = 3

_GENERIC_ERROR = (
    "Sorry, we couldn't search the catalogue right now. Please try again in a moment."
)
_CATALOG_NOT_CONFIGURED = (
    "Our jewellery catalogue isn't connected yet. You can still check offers, "
    "find a store, or track an order from the menu — type *hi* to open it."
)
_PROMPT_TEXT = (
    "Tell me what you're looking for — e.g. *gold ring*, "
    "*diamond necklace under 50k*, or *rivaah collection*."
)


def _parse_button_msgid(raw_id: str) -> str:
    btn_msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            btn_msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    return btn_msgid if isinstance(btn_msgid, str) else raw_id


def _parse_list_reply(messages: dict) -> tuple[str, str] | None:
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return None

    list_reply = interactive.get("list_reply", {})
    title = list_reply.get("title", "")
    raw_id = list_reply.get("id", "")
    list_msgid = raw_id

    try:
        payload = json.loads(raw_id)
        if isinstance(payload, dict):
            list_msgid = payload.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass

    if not isinstance(list_msgid, str):
        return None
    return list_msgid, title


def _build_prompt_response() -> list:
    return [{"type": "text", "text": _PROMPT_TEXT}]


def _build_catalog_not_configured_response() -> list:
    return [{"type": "text", "text": _CATALOG_NOT_CONFIGURED}]


def _clara_configured() -> bool:
    return bool(
        (os.getenv("KISNA_CLARA_BASE_URL") or "").strip()
        and (os.getenv("CLARA_API_KEY") or "").strip()
    )


_MATERIAL_BUTTON_MSGIDS = frozenset({"search$material$gold", "search$material$diamond"})


def _material_button_msgid(messages: dict) -> str | None:
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return None
    btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
    if btn_msgid in _MATERIAL_BUTTON_MSGIDS:
        return btn_msgid
    return None


def _material_type_from_msgid(msgid: str) -> str:
    if msgid == "search$material$diamond":
        return "diamond"
    return "gold"


def _extract_search_query(messages: dict) -> str | None:
    text_body = messages.get("text", {}).get("body", "")
    if text_body and text_body.strip():
        return text_body.strip()

    interactive = messages.get("interactive", {})
    if interactive.get("type") == "button_reply":
        btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
        if btn_msgid == "search$explore":
            return ""

    return None


def _build_search_success_response(
    products: list[dict],
    total_count: int,
    page: int,
    entities: dict,
) -> list[dict]:
    bot_response: list[dict] = []
    search_context = build_search_context(entities)
    images_sent = 0

    for product in products:
        if images_sent >= _MAX_IMAGE_PRODUCTS:
            break
        url = get_product_image_url(product)
        if not url:
            continue
        bot_response.append(
            {
                "type": "media",
                "media_type": "image",
                "url": url,
                "caption": format_product_image_caption(product),
            }
        )
        images_sent += 1

    if total_count > _MAX_IMAGE_PRODUCTS:
        bot_response.append(
            {
                "type": "quickreply",
                "text": f"We found *{total_count}* pieces matching your search.",
                "caption": "",
                "options": [{"title": "Show More"}],
                "msgid": "search$more",
            }
        )
        bot_response.append(
            format_product_list_message(
                products,
                total_count,
                page,
                search_context=search_context,
            )
        )
    elif images_sent == 0 and products:
        bot_response.append(
            format_product_list_message(
                products,
                total_count,
                page,
                search_context=search_context,
            )
        )

    return bot_response


def build_product_media_message(product: dict) -> dict | None:
    """Single image + caption for a product (used by search and details agents)."""
    url = get_product_image_url(product)
    if not url:
        return None
    return {
        "type": "media",
        "media_type": "image",
        "url": url,
        "caption": format_product_image_caption(product),
    }


class ProductSearchAgentV3(Processor):
    """Product catalog search via Clara API and WhatsApp media/list UI."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        if _material_button_msgid(messages):
            return True

        user_profile = data.get("user_profile", {})

        if user_profile.get("service_selected") not in (
            SL.PRODUCT_SEARCH.value,
            SL.PRE_ORDER.value,
        ) and data.get("classified_category") not in (
            "product_search",
            "product_info",
        ):
            return False

        parsed = _parse_list_reply(messages)
        if parsed and parsed[0].startswith("product_select$"):
            return False

        if _extract_search_query(messages) is not None:
            return True

        interactive = messages.get("interactive", {})
        if interactive.get("type") == "button_reply":
            btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
            if btn_msgid in ("search$back", "search$more"):
                return True

        return False

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        messages = data.get("messages", {})

        if not self.should_run(data):
            return data

        user_profile = data.get("user_profile", {})
        material_msgid = _material_button_msgid(messages)
        if material_msgid:
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            material = _material_type_from_msgid(material_msgid)
            entities = {"material_type": material, "category": None, "min_price": None,
                        "max_price": None, "title": None, "city": None, "pincode": None}
            return await self._execute_search(
                data, phone_number, entities, query_label=material
            )

        interactive = messages.get("interactive", {})
        if interactive.get("type") == "button_reply":
            btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
            if btn_msgid == "search$back":
                data["user_profile"]["service_selected"] = SL.PRODUCT_SEARCH.value
                data["bot_response"] = _build_prompt_response()
                return data

        query = _extract_search_query(messages)
        if query == "":
            data["bot_response"] = _build_prompt_response()
            return data

        if not query:
            return data

        if not _clara_configured():
            logger.warning(
                "Product search skipped — KISNA_CLARA_BASE_URL / CLARA_API_KEY not configured",
                extra={"phone_number": phone_number, "query": query},
            )
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        entities = extract_entities(query)
        return await self._execute_search(
            data, phone_number, entities, query_label=query
        )

    async def _execute_search(
        self,
        data: dict,
        phone_number: str,
        entities: dict,
        *,
        query_label: str,
    ) -> dict:
        api_params = entities_to_api_params(entities)
        search_context = build_search_context(entities)

        logger.info(
            "Product search",
            extra={
                "phone_number": phone_number,
                "query": query_label,
                "entities": entities,
                "api_params": api_params,
            },
        )

        try:
            result = await search_products(**api_params, page_no=1, page_size=5)
        except ClaraAPIError as e:
            logger.exception(
                "Product search failed",
                extra={
                    "phone_number": phone_number,
                    "query": query_label,
                    "error": str(e),
                },
            )
            data["bot_response"] = [{"type": "text", "text": e.args[0]}]
            return data
        except Exception as e:
            logger.exception(
                "Unexpected product search error",
                extra={
                    "phone_number": phone_number,
                    "error": str(e),
                },
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data

        products = result.get("products") or []
        total_count = result.get("total_count", 0)
        page = result.get("page", 1)

        user_profile = data.get("user_profile", {})
        user_profile["last_search_filters"] = entities
        user_profile["last_search_page"] = page
        user_profile["last_search_total"] = total_count
        user_profile["last_search_products"] = products[:5]

        if not products:
            data["bot_response"] = [
                {"type": "text", "text": format_zero_results_message(entities)}
            ]
            return data

        shown = user_profile.setdefault("shown_product_ids", [])
        for product in products:
            pid = product.get("_id") or product.get("id")
            if pid and pid not in shown:
                shown.append(pid)

        data["bot_response"] = _build_search_success_response(
            products, total_count, page, entities
        )
        logger.info(
            "Product search results sent",
            extra={
                "phone_number": phone_number,
                "search_context": search_context,
                "total_count": total_count,
                "returned": len(products),
            },
        )
        return data
