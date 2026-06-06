import json
import os
import re

from kisna_chatbot.integrations.clara_api import ClaraAPIError, search_products
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.service_list import build_explore_products_list_with_prompt
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.entity_extractor import (
    build_search_context,
    entities_to_api_params,
    extract_entities,
    filter_products_by_entities,
    has_strict_product_filters,
    is_unrecognizable_input,
    merge_search_entities,
    normalize_category_for_api,
    normalize_material_for_api,
)
from kisna_chatbot.utils.jewellery_profile import (
    entities_to_jewellery_profile,
    merge_jewellery_profile,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.product_formatter import (
    BROWSE_PRODUCTS_GLOBAL_TITLE,
    format_product_buy_caption,
    format_product_image_caption,
    format_product_list_message,
    format_zero_results_message,
    get_product_display_price,
    get_product_image_url_for_whatsapp,
)

_MAX_IMAGE_PRODUCTS = 3
PAGE_SIZE = 5
_CAROUSEL_SCAN_LIMIT = 15
_API_FETCH_PAGE_SIZE = 15
_SHOW_MORE_PAGE_RETRIES = 2

_SEARCH_CAT_LIST_MSGID = "search$cat$list"

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
_SESSION_EXPIRED_TEXT = (
    "Your search session has expired. What jewellery are you looking for?"
)
_ALL_RESULTS_SEEN_TEXT = (
    "You have seen all {total} results!\n"
    "Browse more on our website: https://www.kisna.com"
)
_NO_MORE_NEW_TEXT = (
    "No more new results. Browse full collection: https://www.kisna.com"
)
_NO_MORE_IN_BUDGET_TEXT = (
    "No more results within your budget.\n"
    "Browse full collection: https://www.kisna.com"
)

_ENTITY_KEYS = ("category", "material_type", "min_price", "max_price", "title")

_MATERIAL_BUTTON_MSGIDS = frozenset({"search$material$gold", "search$material$diamond"})
_PRODUCT_BUTTON_MSGIDS = frozenset(
    {"product$similar", "product$store", "product$browse"}
)
_SEARCH_BUTTON_MSGIDS = frozenset({"search$more", "search$explore"})
_UNSUPPORTED_CATEGORY_NOTE = (
    "I'll show you our full collection since we don't have a specific filter for that."
)
_SIZE_QUERY_RE = re.compile(
    r"\b(size|sizes|variant|variants|karat|kt\b|available|18kt|14kt|22kt|chain)\b",
    re.I,
)

_CHEAPEST_RE = re.compile(
    r"\b(cheapest|cheaper|sabse\s+sasta|most\s+affordable|lowest\s+price|sasta)\b",
    re.I,
)

_BROWSE_ALL_RE = re.compile(
    r"\b(sab\s+dikhao|show\s+me\s+everything|browse\s+all)\b",
    re.I,
)


def _entities_all_none(entities: dict) -> bool:
    if entities.get("multi_category") or entities.get("categories"):
        return False
    return all(entities.get(key) is None for key in _ENTITY_KEYS)


def _handle_product_info_followup(data: dict, query: str) -> dict | None:
    """Answer product_info follow-ups from cached search/viewed products."""
    user_profile = data.get("user_profile", {})
    if data.get("classified_category") != "product_info":
        return None

    last_search = user_profile.get("last_search_products") or []
    last_viewed = user_profile.get("last_viewed_product")

    if last_search and _CHEAPEST_RE.search(query):
        priced = [
            (get_product_display_price(p), p)
            for p in last_search
            if get_product_display_price(p) > 0
        ]
        if not priced:
            return None
        priced.sort(key=lambda item: item[0])
        cheapest = priced[0][1]
        user_profile["last_viewed_product"] = cheapest
        bot_response: list[dict] = [
            {
                "type": "text",
                "text": "The most affordable from your recent search:",
            }
        ]
        url = get_product_image_url_for_whatsapp(cheapest)
        if url:
            bot_response.append(
                {
                    "type": "media",
                    "media_type": "image",
                    "url": url,
                    "caption": format_product_image_caption(cheapest),
                }
            )
        bot_response.append(
            {"type": "text", "text": format_product_buy_caption(cheapest)}
        )
        data["bot_response"] = bot_response
        return data

    if last_viewed and _SIZE_QUERY_RE.search(query):
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    "Sizes and variants are available on the product page. "
                    "Tap 'Buy on KISNA' above to select your size and place your order."
                ),
            }
        ]
        return data

    if last_viewed and re.search(r"\b(chain|included|come\s+with)\b", query, re.I):
        variant = last_viewed.get("variant") or {}
        chain_note = variant.get("title") or last_viewed.get("title") or "This piece"
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    f"{chain_note}: chain and variant details are shown on the "
                    "product page. Tap 'Buy on KISNA' to see all options."
                ),
            }
        ]
        return data

    return None


def _parse_button_msgid(raw_id: str) -> str:
    btn_msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            btn_msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    return btn_msgid if isinstance(btn_msgid, str) else raw_id


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


def _empty_entities() -> dict:
    return {
        "category": None,
        "material_type": None,
        "min_price": None,
        "max_price": None,
        "title": None,
        "city": None,
        "pincode": None,
    }


def _normalize_entities(entities: dict) -> dict:
    return {k: entities.get(k) for k in _ENTITY_KEYS}


def _entities_equal(a: dict, b: dict) -> bool:
    return _normalize_entities(a or {}) == _normalize_entities(b or {})


def _product_id(product: dict) -> str:
    pid = product.get("_id") or product.get("id")
    return str(pid) if pid else ""


def _is_browse_products_global_tap(parsed: tuple[str, str, str]) -> bool:
    list_msgid, title, postback = parsed
    if not list_msgid.startswith("product_select$"):
        return False
    if postback.strip():
        return False
    normalized = " ".join(title.strip().lower().split())
    return normalized == BROWSE_PRODUCTS_GLOBAL_TITLE.lower()


def _category_from_postback(postback: str) -> str | None:
    if not postback.startswith("search$cat$"):
        return None
    return postback.split("$", 2)[2] or None


def _has_more_pages(page: int, total_count: int, page_size: int = PAGE_SIZE) -> bool:
    return (page * page_size) < total_count


def _lowest_price(products: list[dict]) -> int | None:
    prices = [get_product_display_price(product) for product in products]
    prices = [p for p in prices if p > 0]
    return min(prices) if prices else None


def _build_prompt_response() -> list:
    return [{"type": "text", "text": _PROMPT_TEXT}]


def _build_catalog_not_configured_response() -> list:
    return [{"type": "text", "text": _CATALOG_NOT_CONFIGURED}]


def _clara_configured() -> bool:
    return bool(
        (os.getenv("KISNA_CLARA_BASE_URL") or "").strip()
        and (os.getenv("CLARA_API_KEY") or "").strip()
    )


def _product_button_msgid(messages: dict) -> str | None:
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return None
    btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
    if btn_msgid in _PRODUCT_BUTTON_MSGIDS:
        return btn_msgid
    return None


def _search_button_msgid(messages: dict) -> str | None:
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return None
    btn_msgid = _parse_button_msgid(interactive.get("button_reply", {}).get("id", ""))
    if btn_msgid in _SEARCH_BUTTON_MSGIDS or btn_msgid.startswith("search$also$"):
        return btn_msgid
    return None


def _humanize_category_label(category: str) -> str:
    labels = {
        "earring": "earrings",
        "ring": "rings",
        "necklace": "necklaces",
        "bracelet": "bracelets",
        "bangle": "bangles",
        "pendant": "pendants",
        "mangalsutra": "mangalsutra",
        "nosewear": "nose wear",
        "watchwear": "watch wear",
    }
    if category in labels:
        return labels[category]
    if category.endswith("s"):
        return category.replace("_", " ")
    return f"{category.replace('_', ' ')}s"


def _entities_from_last_viewed(last: dict) -> dict:
    material_type = normalize_material_for_api(last.get("materialType"))
    category = normalize_category_for_api(last.get("category"))

    return {
        "category": category,
        "material_type": material_type,
        "min_price": None,
        "max_price": None,
        "title": None,
        "city": None,
        "pincode": None,
    }


def _entities_from_category(category: str) -> dict:
    return {**_empty_entities(), "category": category}


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


def _size_query_with_last_viewed(data: dict) -> bool:
    user_profile = data.get("user_profile", {})
    if not user_profile.get("last_viewed_product"):
        return False
    if data.get("classified_category") != "product_info":
        return False
    text = (data.get("messages", {}).get("text", {}) or {}).get("body", "") or ""
    return bool(text.strip() and _SIZE_QUERY_RE.search(text))


def _extract_search_query(messages: dict) -> str | None:
    text_body = messages.get("text", {}).get("body", "")
    if text_body and text_body.strip():
        return text_body.strip()
    return None


def _build_fallback_strategies(
    entities: dict,
) -> list[tuple[dict, str | None, str]]:
    """Return (filter_entities, note_kind, log_label) for progressive relaxation."""
    strategies: list[tuple[dict, str | None, str]] = []
    seen: set[tuple] = set()

    def add(ent: dict, note_kind: str | None, label: str) -> None:
        key = tuple(_normalize_entities(ent).items())
        if key not in seen:
            seen.add(key)
            strategies.append((ent, note_kind, label))

    add(entities, None, "full")

    if entities.get("min_price") is not None or entities.get("max_price") is not None:
        no_price = {**entities, "min_price": None, "max_price": None}
        add(no_price, "budget", "drop_price")

    if entities.get("material_type"):
        no_material = {**entities, "material_type": None}
        add(no_material, "material", "drop_material")

    if entities.get("title"):
        title_only = {**_empty_entities(), "title": entities["title"]}
        add(title_only, None, "title_only")

    return strategies


def _fallback_prefix_note(
    note_kind: str | None,
    products: list[dict],
    original_entities: dict,
    strategy_entities: dict,
) -> str | None:
    if note_kind == "budget":
        lowest = _lowest_price(products)
        if lowest is not None:
            return (
                f"Showing results outside your budget — "
                f"prices in this category start from ₹{lowest:,}"
            )
        return "Showing results outside your budget:"
    if note_kind == "material":
        material = original_entities.get("material_type") or "matching"
        category = original_entities.get("category") or "jewellery"
        cat_label = category if str(category).endswith("s") else f"{category}s"
        if cat_label == "mangalsutras":
            cat_label = "mangalsutra"
        return (
            f"I couldn't find {material} {cat_label}, "
            f"but here are other {cat_label} options you might like:"
        )
    return None


def _collect_carousel_products(
    products: list[dict],
    *,
    max_images: int = _MAX_IMAGE_PRODUCTS,
    max_scan: int = _CAROUSEL_SCAN_LIMIT,
) -> tuple[list[dict], list[str], int]:
    """Return products with resolvable images, skipped ids, and scanned count."""
    carousel: list[dict] = []
    skipped_product_ids: list[str] = []
    scanned = 0

    for product in products:
        if scanned >= max_scan or len(carousel) >= max_images:
            break
        scanned += 1
        if get_product_image_url_for_whatsapp(product):
            carousel.append(product)
            continue
        pid = product.get("_id") or product.get("id")
        if pid:
            skipped_product_ids.append(str(pid))

    return carousel, skipped_product_ids, scanned


def _build_search_success_response(
    products: list[dict],
    total_count: int,
    page: int,
    entities: dict,
    *,
    prefix_note: str | None = None,
    show_more_intro: bool = True,
    page_size: int = PAGE_SIZE,
    carousel_pool: list[dict] | None = None,
    client_filtered: bool = False,
) -> list[dict]:
    bot_response: list[dict] = []
    if prefix_note:
        bot_response.append({"type": "text", "text": prefix_note})

    search_context = build_search_context(entities)
    scan_pool = carousel_pool if carousel_pool is not None else products
    carousel_products, skipped_product_ids, scanned_count = _collect_carousel_products(
        scan_pool
    )

    for product in carousel_products:
        url = get_product_image_url_for_whatsapp(product)
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

    images_sent = len(carousel_products)

    if images_sent == 0 and products:
        bot_response.append(
            {
                "type": "text",
                "text": "Here are your results (images unavailable for some items):",
            }
        )
    elif skipped_product_ids:
        logger.warning(
            "Search carousel skipped products without image URLs",
            extra={
                "images_sent": images_sent,
                "scanned_count": scanned_count,
                "skipped_product_ids": skipped_product_ids,
            },
        )

    list_products = products[:page_size]
    if list_products:
        if _has_more_pages(page, total_count, page_size):
            if client_filtered:
                qr_text = (
                    "More matching results may be available."
                    if show_more_intro
                    else "Tap below for more results."
                )
            else:
                qr_text = (
                    f"We found *{total_count}* pieces matching your search."
                    if show_more_intro
                    else "Tap below for more results."
                )
            bot_response.append(
                {
                    "type": "quickreply",
                    "text": qr_text,
                    "caption": "",
                    "options": [{"title": "Show More"}],
                    "msgid": "search$more",
                }
            )
        bot_response.append(
            format_product_list_message(
                list_products,
                total_count,
                page,
                search_context=search_context,
                page_size=page_size,
                client_filtered=client_filtered,
            )
        )

    return bot_response


def build_product_media_message(product: dict) -> dict | None:
    """Single image + caption for a product (used by search and details agents)."""
    url = get_product_image_url_for_whatsapp(product)
    if not url:
        return None
    return {
        "type": "media",
        "media_type": "image",
        "url": url,
        "caption": format_product_image_caption(product),
    }


def _append_shown_product_ids(user_profile: dict, products: list[dict]) -> None:
    shown = user_profile.setdefault("shown_product_ids", [])
    shown_set = {str(x) for x in shown}
    for product in products:
        pid = _product_id(product)
        if pid and pid not in shown_set:
            shown.append(pid)
            shown_set.add(pid)


def _filter_unshown_products(
    products: list[dict], shown_product_ids: list
) -> list[dict]:
    shown_set = {str(x) for x in shown_product_ids}
    return [p for p in products if _product_id(p) and _product_id(p) not in shown_set]


class ProductSearchAgentV3(Processor):
    """Product catalog search via Clara API and WhatsApp media/list UI."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        if _material_button_msgid(messages):
            return True
        if _product_button_msgid(messages):
            return True
        if _search_button_msgid(messages):
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
        if parsed:
            if parsed[0] == _SEARCH_CAT_LIST_MSGID:
                return True
            if _is_browse_products_global_tap(parsed):
                return True
            if parsed[0].startswith("product_select$"):
                return False

        if _size_query_with_last_viewed(data):
            return False

        if _extract_search_query(messages) is not None:
            return True

        return False

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        messages = data.get("messages", {})

        if not self.should_run(data):
            return data

        user_profile = data.get("user_profile", {})

        search_btn = _search_button_msgid(messages)
        if search_btn == "search$more":
            return await self._handle_show_more(data, phone_number)

        if search_btn and search_btn.startswith("search$also$"):
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            secondary = search_btn.rsplit("$", 1)[-1]
            last_filters = user_profile.get("last_search_filters") or _empty_entities()
            entities = {
                **last_filters,
                "category": secondary,
                "categories": [secondary],
                "multi_category": False,
                "secondary_category": None,
            }
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            return await self._execute_search(
                data,
                phone_number,
                entities,
                query_label=f"also:{secondary}",
            )

        if search_btn == "search$explore":
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            return await self._execute_search(
                data, phone_number, _empty_entities(), query_label="browse_all"
            )

        parsed = _parse_list_reply(messages)
        if parsed:
            list_msgid, _title, postback = parsed
            if list_msgid == _SEARCH_CAT_LIST_MSGID:
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                if postback == "search$explore":
                    return await self._execute_search(
                        data, phone_number, _empty_entities(), query_label="browse_all"
                    )
                category = _category_from_postback(postback)
                if category:
                    return await self._execute_search(
                        data,
                        phone_number,
                        _entities_from_category(category),
                        query_label=f"category:{category}",
                    )
                data["bot_response"] = _build_prompt_response()
                return data

            if _is_browse_products_global_tap(parsed):
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                return await self._execute_search(
                    data, phone_number, _empty_entities(), query_label="browse_all"
                )

        product_msgid = _product_button_msgid(messages)
        if product_msgid:
            if product_msgid == "product$store":
                user_profile["service_selected"] = SL.AD_FLOW.value
                user_profile["awaiting_store_pincode"] = True
                data["bot_response"] = [{"type": "text", "text": _ASK_PINCODE_TEXT}]
                return data

            if product_msgid == "product$browse":
                products = user_profile.get("last_search_products") or []
                if not products:
                    data["bot_response"] = _build_prompt_response()
                    return data
                entities = user_profile.get("last_search_filters") or {}
                total = user_profile.get("last_search_total", len(products))
                page = user_profile.get("last_search_page", 1)
                data["bot_response"] = [
                    format_product_list_message(
                        products,
                        total,
                        page,
                        search_context=build_search_context(entities),
                    )
                ]
                return data

            if product_msgid == "product$similar":
                last = user_profile.get("last_viewed_product") or {}
                if not last:
                    data["bot_response"] = _build_prompt_response()
                    return data
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                entities = _entities_from_last_viewed(last)
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                label = last.get("title") or "similar pieces"
                exclude_id = str(last.get("_id") or "")
                return await self._execute_search(
                    data,
                    phone_number,
                    entities,
                    query_label=f"similar:{label}",
                    exclude_product_id=exclude_id or None,
                )

        material_msgid = _material_button_msgid(messages)
        if material_msgid:
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            material = _material_type_from_msgid(material_msgid)
            entities = {
                "material_type": material,
                "category": None,
                "min_price": None,
                "max_price": None,
                "title": None,
                "city": None,
                "pincode": None,
            }
            return await self._execute_search(
                data, phone_number, entities, query_label=material
            )

        query = _extract_search_query(messages)
        if not query:
            return data

        followup = _handle_product_info_followup(data, query)
        if followup is not None:
            return followup

        if is_unrecognizable_input(query):
            user_profile["service_selected"] = SL.GENERAL.value
            data["classified_category"] = "general"
            return data

        if not _clara_configured():
            logger.warning(
                "Product search skipped — KISNA_CLARA_BASE_URL / CLARA_API_KEY not configured",
                extra={"phone_number": phone_number, "query": query},
            )
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        extracted = extract_entities(query)
        prior = user_profile.get("last_search_filters")
        entities = merge_search_entities(prior, extracted, query)
        if extracted.get("max_price") is not None or extracted.get("min_price") is not None:
            user_profile["user_stated_budget"] = {
                "min_price": extracted.get("min_price"),
                "max_price": extracted.get("max_price"),
            }
        logger.info(
            "Search entity merge",
            extra={
                "phone_number": phone_number,
                "query": query,
                "prior_filters": prior,
                "extracted": extracted,
                "merged": entities,
                "api_params": entities_to_api_params(entities),
            },
        )

        if (
            _entities_all_none(entities)
            and not _BROWSE_ALL_RE.search(query)
            and data.get("classified_category") == "product_search"
        ):
            data["bot_response"] = [build_explore_products_list_with_prompt()]
            return data

        return await self._execute_search(
            data, phone_number, entities, query_label=query
        )

    async def _handle_show_more(self, data: dict, phone_number: str) -> dict:
        user_profile = data.get("user_profile", {})
        filters = user_profile.get("last_search_filters")
        last_page = user_profile.get("last_search_page", 1)
        total = user_profile.get("last_search_total", 0)
        shown_ids = user_profile.get("shown_product_ids") or []

        if filters is None or filters == {}:
            data["bot_response"] = [{"type": "text", "text": _SESSION_EXPIRED_TEXT}]
            return data
        filters = filters or _empty_entities()

        if (last_page * PAGE_SIZE) >= total:
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": _ALL_RESULTS_SEEN_TEXT.format(total=total),
                }
            ]
            return data

        if not _clara_configured():
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        api_params = entities_to_api_params(filters)
        next_page = last_page + 1
        products: list[dict] = []
        has_budget_filter = (
            filters.get("min_price") is not None
            or filters.get("max_price") is not None
        )
        client_filtered = has_strict_product_filters(filters)

        for attempt in range(1 + _SHOW_MORE_PAGE_RETRIES):
            if attempt > 0 and (next_page - 1) * PAGE_SIZE >= total:
                break

            try:
                result = await search_products(
                    **api_params,
                    page_no=next_page,
                    page_size=_API_FETCH_PAGE_SIZE,
                )
            except ClaraAPIError as e:
                data["bot_response"] = [{"type": "text", "text": e.args[0]}]
                return data
            except Exception:
                logger.exception(
                    "Show More search failed",
                    extra={"phone_number": phone_number},
                )
                data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
                return data

            raw_products = result.get("products") or []
            filtered = filter_products_by_entities(raw_products, filters)
            candidates = _filter_unshown_products(filtered, shown_ids)
            if candidates:
                products = candidates
                break

            if next_page * PAGE_SIZE >= total:
                break
            next_page += 1

        if not products:
            if has_budget_filter:
                data["bot_response"] = [
                    {"type": "text", "text": _NO_MORE_IN_BUDGET_TEXT}
                ]
            else:
                data["bot_response"] = [{"type": "text", "text": _NO_MORE_NEW_TEXT}]
            return data

        user_profile["last_search_page"] = next_page
        user_profile["last_search_products"] = products[:PAGE_SIZE]
        _append_shown_product_ids(user_profile, products[:PAGE_SIZE])

        entities = filters
        data["bot_response"] = _build_search_success_response(
            products[:PAGE_SIZE],
            total,
            next_page,
            entities,
            show_more_intro=False,
            carousel_pool=products,
            client_filtered=client_filtered,
        )

        logger.info(
            "Show More results sent",
            extra={
                "phone_number": phone_number,
                "page": next_page,
                "returned": len(products),
                "total": total,
            },
        )
        return data

    async def _execute_search(
        self,
        data: dict,
        phone_number: str,
        entities: dict,
        *,
        query_label: str,
        exclude_product_id: str | None = None,
    ) -> dict:
        user_profile = data.get("user_profile", {})
        last_filters = user_profile.get("last_search_filters") or {}
        if not _entities_equal(entities, last_filters):
            user_profile["shown_product_ids"] = []

        strategies = _build_fallback_strategies(entities)
        products: list[dict] = []
        total_count = 0
        page = 1
        winning_entities = entities
        prefix_parts: list[str] = []
        if entities.get("unsupported_category"):
            prefix_parts.append(_UNSUPPORTED_CATEGORY_NOTE)
        client_filtered = False

        for strategy_entities, note_kind, log_label in strategies:
            api_params = entities_to_api_params(strategy_entities)
            logger.info(
                "Product search",
                extra={
                    "phone_number": phone_number,
                    "query": query_label,
                    "strategy": log_label,
                    "entities": strategy_entities,
                    "api_params": api_params,
                },
            )
            if log_label != "full":
                logger.info(
                    "Search fallback",
                    extra={
                        "phone_number": phone_number,
                        "dropped_filter": log_label,
                    },
                )

            try:
                result = await search_products(
                    **api_params, page_no=1, page_size=_API_FETCH_PAGE_SIZE
                )
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

            raw_products = result.get("products") or []
            products = filter_products_by_entities(raw_products, strategy_entities)
            has_price_filter = (
                strategy_entities.get("min_price") is not None
                or strategy_entities.get("max_price") is not None
            )

            without_price = filter_products_by_entities(
                raw_products,
                {**strategy_entities, "min_price": None, "max_price": None},
            )
            if (
                log_label == "full"
                and without_price
                and not products
                and has_price_filter
            ):
                logger.warning(
                    "api_price_filter_mismatch",
                    extra={
                        "phone_number": phone_number,
                        "raw_count": len(raw_products),
                        "price_eligible_count": len(without_price),
                        "filtered_count": 0,
                        "entities": strategy_entities,
                    },
                )
                continue

            if products:
                api_total = result.get("total_count", 0)
                client_filtered = len(products) < len(raw_products) or (
                    has_strict_product_filters(strategy_entities)
                    and len(products) < api_total
                )
                if client_filtered and has_strict_product_filters(strategy_entities):
                    total_count = len(products)
                else:
                    total_count = api_total
                page = result.get("page", 1)
                winning_entities = strategy_entities
                fallback_note = _fallback_prefix_note(
                    note_kind, products, entities, strategy_entities
                )
                if fallback_note:
                    prefix_parts.append(fallback_note)
                break

        search_context = build_search_context(winning_entities)
        prefix_note = "\n".join(prefix_parts) if prefix_parts else None

        if not products:
            data["bot_response"] = [
                {"type": "text", "text": format_zero_results_message(entities)}
            ]
            return data

        if exclude_product_id:
            filtered = [
                p for p in products if _product_id(p) != str(exclude_product_id)
            ]
            if filtered:
                products = filtered
            elif total_count > 1:
                total_count = max(len(products), total_count - 1)

        user_profile["last_search_filters"] = winning_entities
        profile_updates = entities_to_jewellery_profile(
            winning_entities,
            source_text=query_label,
        )
        if profile_updates:
            existing_profile = user_profile.get("jewellery_profile") or {}
            user_profile["jewellery_profile"] = merge_jewellery_profile(
                existing_profile,
                profile_updates,
            )
        user_profile["last_search_page"] = page
        user_profile["last_search_total"] = total_count
        user_profile["last_search_products"] = products[:PAGE_SIZE]
        _append_shown_product_ids(user_profile, products[:PAGE_SIZE])

        data["bot_response"] = _build_search_success_response(
            products[:PAGE_SIZE],
            total_count,
            page,
            winning_entities,
            prefix_note=prefix_note,
            carousel_pool=products,
            client_filtered=client_filtered,
        )

        if entities.get("multi_category") and entities.get("secondary_category"):
            secondary = entities["secondary_category"]
            label = _humanize_category_label(secondary)
            data["bot_response"].append(
                {
                    "type": "quickreply",
                    "text": f"Also showing {label}?",
                    "caption": "",
                    "options": [{"title": f"Show {label}"}],
                    "msgid": f"search$also${secondary}",
                }
            )

        has_media = any(r.get("type") == "media" for r in data["bot_response"])
        if products and not has_media:
            missing = []
            for product in products[:PAGE_SIZE]:
                missing.append(
                    {
                        "product_id": _product_id(product),
                        "has_mediaUrl": bool(product.get("mediaUrl")),
                        "mediaUrl_len": len(product.get("mediaUrl") or [])
                        if isinstance(product.get("mediaUrl"), list)
                        else 0,
                    }
                )
            logger.warning(
                "Product search returned items but no image URLs resolved",
                extra={
                    "phone_number": phone_number,
                    "query": query_label,
                    "products_without_image": missing,
                },
            )

        logger.info(
            "Product search results sent",
            extra={
                "phone_number": phone_number,
                "search_context": search_context,
                "total_count": total_count,
                "returned": len(products),
                "images_in_response": sum(
                    1 for r in data["bot_response"] if r.get("type") == "media"
                ),
            },
        )
        return data
