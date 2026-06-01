import json
from urllib.parse import urlparse

from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter, ClientAPIError
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_MAX_RESULTS = 10
_PRODUCT_LIST_MSGID = "product_select$results"

_GENERIC_ERROR = (
    "Sorry, we couldn't search the catalog right now. Please try again in a moment."
)
_CATALOG_NOT_CONFIGURED = (
    "Our product catalog isn't connected yet. You can still ask design questions, "
    "check offers, or track an order from the menu — type *hi* to open it."
)
_EMPTY_RESULTS = (
    "No products matched your search. Try different keywords — e.g. *sofa*, "
    "*dining table*, or *bed*."
)
_PROMPT_TEXT = (
    "Tell me what you're looking for — e.g. *3-seater sofa*, "
    "*dining table*, or *bedroom set* — and I'll find options for you."
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


def _format_price(price) -> str:
    if price is None or price == "":
        return "View details"
    return f"₹{price}"


def _build_product_list_response(products: list[dict], query: str) -> dict:
    options = []
    for product in products[:_MAX_RESULTS]:
        product_id = str(product.get("id") or "")
        if not product_id:
            continue
        title = (product.get("title") or "Product")[:24]
        options.append(
            {
                "type": "text",
                "title": title,
                "description": _format_price(product.get("price"))[:72],
                "postbackText": product_id,
            }
        )

    body = (
        f"Here are top matches for *{query}*:\n\n"
        "Tap a product to see full details."
    )
    return {
        "type": "list",
        "list": "list",
        "body": body,
        "footer": "Kisna",
        "msgid": _PRODUCT_LIST_MSGID,
        "globalButtons": [{"type": "text", "title": "View Products"}],
        "items": [{"title": "Results", "subtitle": "", "options": options}],
    }


def _build_prompt_response() -> list:
    return [{"type": "text", "text": _PROMPT_TEXT}]


def _build_error_response() -> list:
    return [{"type": "text", "text": _GENERIC_ERROR}]


def _build_catalog_not_configured_response() -> list:
    return [{"type": "text", "text": _CATALOG_NOT_CONFIGURED}]


def _catalog_api_host(client_config) -> str:
    base = getattr(client_config, "product_api_base", "") or ""
    if not isinstance(base, str):
        return ""
    base = base.strip()
    if not base:
        return ""
    host = urlparse(base).netloc or base
    return host.split("@")[-1]


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


class ProductSearchAgentV3(Processor):
    """Product catalog search via ClientAPIAdapter and WhatsApp list UI."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        user_profile = data.get("user_profile", {})

        if user_profile.get("service_selected") not in (
            SL.PRODUCT_SEARCH.value,
            SL.PRE_ORDER.value,
        ) and data.get("classified_category") != "product_search":
            return False

        parsed = _parse_list_reply(messages)
        if parsed and parsed[0].startswith("product_select$"):
            return False

        if _extract_search_query(messages) is not None:
            return True

        interactive = messages.get("interactive", {})
        if interactive.get("type") == "button_reply":
            btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
            if btn_msgid == "search$back":
                return True

        return False

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        messages = data.get("messages", {})
        client_config = data["client_config"]

        if not self.should_run(data):
            return data

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

        api_host = _catalog_api_host(client_config)
        if not api_host:
            logger.warning(
                "Product search skipped — KISNA_PRODUCT_API not configured",
                extra={"phone_number": phone_number, "query": query},
            )
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        logger.info(
            "Product search",
            extra={
                "phone_number": phone_number,
                "query": query,
                "catalog_host": api_host,
            },
        )

        adapter = ClientAPIAdapter(client_config)
        try:
            products = await adapter.search_products(query=query, limit=_MAX_RESULTS)
        except ValueError as e:
            logger.warning(
                "Product search configuration error",
                extra={
                    "phone_number": phone_number,
                    "query": query,
                    "catalog_host": api_host,
                    "error": str(e),
                },
            )
            data["bot_response"] = _build_catalog_not_configured_response()
            return data
        except (ClientAPIError, NotImplementedError) as e:
            logger.exception(
                "Product search failed",
                extra={
                    "phone_number": phone_number,
                    "query": query,
                    "catalog_host": api_host,
                    "error": str(e),
                },
            )
            data["bot_response"] = _build_error_response()
            return data
        except Exception as e:
            logger.exception(
                "Unexpected product search error",
                extra={
                    "phone_number": phone_number,
                    "catalog_host": api_host,
                    "error": str(e),
                },
            )
            data["bot_response"] = _build_error_response()
            return data
        finally:
            await adapter.aclose()

        if not products:
            data["bot_response"] = [{"type": "text", "text": _EMPTY_RESULTS}]
            return data

        user_profile = data.get("user_profile", {})
        shown = user_profile.setdefault("shown_product_ids", [])
        for product in products:
            pid = product.get("id")
            if pid and pid not in shown:
                shown.append(pid)

        data["bot_response"] = [_build_product_list_response(products, query)]
        return data
