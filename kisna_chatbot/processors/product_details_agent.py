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
    extract_category_from_product,
    combine_search_entities,
    extract_structured_fields,
    finalize_search_entities,
    normalize_material_for_api,
)
from kisna_chatbot.utils.jewellery_profile import (
    entities_to_jewellery_profile,
    merge_jewellery_profile,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.product_formatter import (
    build_product_url,
    format_product_buy_caption,
    get_product_image_url,
    get_product_image_url_for_whatsapp,
    get_product_price_bundle,
    get_whatsapp_safe_image_url,
)

_RETRY_SEARCH_TEXT = "Let me search for that again."
_SEARCH_ERROR_TEXT = (
    "Sorry, we couldn't search the catalogue right now. Please try again."
)
_CACHE_MISS_TEXT = (
    "Sorry, we couldn't find that product. Try searching again — tell me what you're looking for."
)
_BUY_CTA_TEXT = (
    "Tap below to choose size, metal & colour and place your order on kisna.com."
)
_IMAGE_UNAVAILABLE_LINE = (
    "Image unavailable — view on kisna.com via the Buy button below."
)
def _product_facts(product: dict) -> str:
    """Every fact we actually hold about one product, one per line.

    The answerer below may use NOTHING else, so an attribute missing here comes
    back as "I don't have that" instead of an invented number. Diamond carat
    weight is deliberately absent: Clara does not return it, and the reported
    failure was the bot implying the 14KT GOLD karat answered a question about
    diamond carats.
    """
    from kisna_chatbot.utils.product_formatter import (
        _variant_attributes_line,
        format_price_line,
        get_product_display_price,
    )

    bundle = get_product_price_bundle(product) or {}
    shipping = product.get("shipping") or {}
    facts = [f"name: {product.get('title') or 'Product'}"]
    # Omit the price entirely rather than list a zero. A malformed record
    # rendered as "price: Rs 0", and the answerer would then state Rs 0 to the
    # customer with complete confidence. Absent means "say you don't have it".
    price = get_product_display_price(product)
    if price and price > 0:
        facts.append(f"price: {format_price_line(product)}")
        facts.append("price note: varies with the live gold rate")
    attrs = _variant_attributes_line(product)
    if attrs:
        facts.append(f"metal / karat / colour / size: {attrs}")
    if shipping.get("edd"):
        facts.append(f"ships in: {shipping['edd']} days")
    if bundle.get("sku"):
        facts.append(f"SKU: {bundle['sku']}")
    if product.get("withChain") == "noChain":
        facts.append("chain: NOT included")
    if bundle.get("promo_label"):
        facts.append(f"offer: {bundle['promo_label']}")
    return "\n".join(facts)


# A reply covering several pieces still has to fit a WhatsApp message.
_MAX_PRODUCTS_ANSWERED = 3


async def _answer_product_question(
    question: str,
    product: dict | list[dict],
    *,
    phone_number: str | None,
    client_id: str,
) -> str | None:
    """Answer a question about the viewed product(s), or None to fall back.

    Replaces re-printing the product card. "iska price kya hai?" used to come
    back as the same card the customer was already looking at, and "isme kitne
    carat ka diamond hai" never routed here at all. The model reads the
    question in any language; the facts are enumerated so it cannot invent one.

    Accepts a LIST when the customer asked about a shown set without singling
    one out. Answering across all of them beats asking which they meant: with
    two rings on screen, "isme kitne carat ka diamond hai" has the same honest
    answer for both, and a question is a worse reply than the answer.
    """
    from kisna_chatbot.ai.factory import complete_chat
    from kisna_chatbot.ai.types import AgentName

    products = product if isinstance(product, list) else [product]
    products = [p for p in products if isinstance(p, dict)][:_MAX_PRODUCTS_ANSWERED]
    if not products:
        return None

    if len(products) == 1:
        subject = (
            "A KISNA jewellery customer is asking about ONE product they are "
            "looking at."
        )
        facts_block = _product_facts(products[0])
    else:
        subject = (
            f"A KISNA jewellery customer is asking about the {len(products)} "
            "products currently shown to them, without singling one out. "
            "Answer for ALL of them. Name each piece so it is clear which is "
            "which, and if the answer is the same for every one, say so once "
            "rather than repeating it."
        )
        facts_block = "\n\n".join(
            f"PRODUCT {i}:\n{_product_facts(p)}" for i, p in enumerate(products, 1)
        )

    instruction = (
        f"{subject} Answer their question using ONLY the facts listed, in "
        "their own language, in 1-4 short WhatsApp lines. Bold is a SINGLE "
        "asterisk. "
        "If the answer is not among the facts, say plainly that you do not "
        "have that detail and name what you do have. NEVER "
        "guess or invent a number. "
        "The product NAME is a proper noun: copy it EXACTLY as given, in "
        "English. Never translate or transliterate it. It is how the "
        "customer finds the piece on the card, on kisna.com and in their "
        "order — a renamed product is a wrong answer, not a style choice. "
        "The karat figure is the GOLD purity (14KT/18KT). It is NOT a diamond "
        "carat weight -- if asked about diamond carats, say you do not have it."
    )
    try:
        reply = await complete_chat(
            agent=AgentName.GENERAL,
            instruction=instruction,
            messages=[
                {
                    "role": "user",
                    "content": f"FACTS:\n{facts_block}\n\nQUESTION: {question}",
                }
            ],
            max_output_tokens=300 if len(products) == 1 else 500,
            phone_number=phone_number,
            client_id=client_id,
        )
    except Exception:
        logger.warning(
            "product_details: question answering failed, falling back to card",
            extra={"phone_number": phone_number},
            exc_info=True,
        )
        return None
    return (reply or "").strip() or None


_SIZE_VARIANT_REPLY = (
    "Sizes and variants are available on the product page. "
    "Tap 'Buy on KISNA' above to select your size and place your order."
)

_SIZE_QUERY_RE = re.compile(
    r"\b(size|sizes|variant|variants|karat|kt\b|available)\b",
    re.I,
)
_PRICE_AVAILABILITY_RE = re.compile(
    r"\b("
    r"price|cost|kitna|rate|mrp|how\s+much|"
    r"available|in\s+stock|stock|delivery\s+time|edd"
    r")\b|"
    r"(isme|is\s+me|iska|is\s+ka)\s+(kitna|price|cost)",
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
    bundle = get_product_price_bundle(product)
    image_url = get_product_image_url(product)
    user_profile["last_viewed_product"] = {
        "_id": product.get("_id") or product.get("id"),
        "title": product.get("title"),
        "category": extract_category_from_product(product),
        "materialType": normalize_material_for_api(product.get("materialType"))
        or product.get("materialType"),
        "price": bundle["display_price"],
        "mrp_price": bundle.get("mrp_price"),
        "sku": bundle.get("sku"),
        "image_url_snapshot": image_url,
        "mediaUrl": product.get("mediaUrl"),
    }


def _merge_product_media(target: dict, source: dict) -> dict:
    """Copy media fields from a fresher API row into a cached product."""
    merged = dict(target)
    for key in ("mediaUrl", "media", "images", "image", "image_url", "thumbnail"):
        if source.get(key):
            merged[key] = source[key]
    return merged


async def _enrich_product_image(product: dict, *, title_hint: str = "") -> dict:
    """Re-fetch media from Clara when cached product lacks a resolvable image."""
    if get_product_image_url_for_whatsapp(product):
        return product

    search_title = (title_hint or product.get("title") or "").strip()
    if not search_title:
        return product

    try:
        result = await search_products(title=search_title, page_no=1, page_size=3)
    except (ClaraAPIError, Exception):
        logger.warning(
            "Product image enrichment search failed",
            extra={"title": search_title, "product_id": product.get("_id")},
            exc_info=True,
        )
        return product

    product_id = str(product.get("_id") or product.get("id") or "")
    for row in result.get("products") or []:
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("_id") or row.get("id") or "")
        if product_id and row_id and row_id != product_id:
            continue
        if get_product_image_url_for_whatsapp(row):
            return _merge_product_media(product, row)

    for row in result.get("products") or []:
        if isinstance(row, dict) and get_product_image_url_for_whatsapp(row):
            return _merge_product_media(product, row)

    return product


def _build_buy_now_response(product: dict) -> list:
    """Image + Buy CTA + action quick replies for a cached product."""
    responses: list = []
    raw_url = get_product_image_url_for_whatsapp(product)
    image_url = get_whatsapp_safe_image_url(raw_url)
    caption = format_product_buy_caption(product)
    if image_url:
        responses.append(
            {
                "type": "media",
                "media_type": "image",
                "url": image_url,
                "caption": caption,
            }
        )
    else:
        text = f"{caption}\n\n_{_IMAGE_UNAVAILABLE_LINE}_"
        responses.append({"type": "text", "text": text})

    responses.append(
        {
            "type": "cta_url",
            "text": _BUY_CTA_TEXT,
            "display_text": "Buy on KISNA",
            "url": build_product_url(product),
            "_compose": "product_buy_cta",
        }
    )

    responses.append(
        {
            "type": "text",
            "text": (
                "You can ask me for *similar designs*, a *store near you*, "
                "or keep browsing 💎"
            ),
            "_compose": "product_next_steps",
        }
    )
    return responses


def _product_from_last_viewed(user_profile: dict) -> dict | None:
    """Rebuild a minimal product dict from last_viewed_product snapshot."""
    snapshot = user_profile.get("last_viewed_product")
    if not isinstance(snapshot, dict):
        return None
    product_id = snapshot.get("_id")
    if not product_id:
        return None
    cached = _find_cached_product(user_profile, str(product_id))
    if cached:
        return cached
    price = snapshot.get("price")
    if price is None:
        return None
    return {
        "_id": product_id,
        "title": snapshot.get("title"),
        "materialType": snapshot.get("materialType"),
        "price": {"variantPrice": price},
        "variant": {"mrpPrice": snapshot.get("mrp_price")},
    }


async def _retry_product_search(
    data: dict,
    query: str,
    product_id: str | None = None,
) -> list | None:
    """Run a fresh catalog search and return bot_response items."""
    if not query.strip():
        return None

    try:
        entities = finalize_search_entities(
            combine_search_entities({}, extract_structured_fields(query)),
            query=query,
        )
        api_params = entities_to_api_params(entities)
        if not api_params.get("title") and query.strip():
            api_params = {**api_params, "title": query.strip()}

        result = await search_products(**api_params, page_no=1, page_size=5)
    except ClaraAPIError:
        return [{"type": "text", "text": _SEARCH_ERROR_TEXT, "_compose": "system_error"}]
    except Exception:
        logger.exception("Product details retry search failed")
        return [{"type": "text", "text": _SEARCH_ERROR_TEXT, "_compose": "system_error"}]

    products = result.get("products") or []
    total_count = result.get("total_count", 0)
    page = result.get("page", 1)

    user_profile = data.get("user_profile", {})
    user_profile["last_search_products"] = products[:5]
    user_profile["last_search_filters"] = entities
    profile_updates = entities_to_jewellery_profile(
        entities,
        source_text=query,
    )
    if profile_updates:
        existing_profile = user_profile.get("jewellery_profile") or {}
        user_profile["jewellery_profile"] = merge_jewellery_profile(
            existing_profile,
            profile_updates,
        )
    user_profile["last_search_page"] = page
    user_profile["last_search_total"] = total_count
    user_profile["last_search_filter_ratio"] = 1.0
    user_profile["last_search_api_total"] = total_count

    if not products:
        return [{"type": "text", "text": "No matching pieces found. Try another search.", "_compose": "search_empty"}]

    matched = None
    if product_id:
        matched = _find_cached_product(user_profile, product_id)
    if not matched and products:
        matched = products[0]
    if matched:
        _save_last_viewed_product(user_profile, matched)

    search_items = _build_search_success_response(products, total_count, page, entities)
    return [{"type": "text", "text": _RETRY_SEARCH_TEXT, "_compose": "search_retry"}, *search_items]


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
        text = (messages.get("text", {}) or {}).get("body", "") or ""
        if user_profile.get("last_viewed_product") and text.strip():
            # The classifier already read the sentence and said this is a
            # question about a product. Requiring a Latin keyword on top of
            # that vetoed its correct call: "isme kitne CARAT ka diamond hai"
            # missed _SIZE_QUERY_RE (which lists "karat", not "carat") and fell
            # through to search, which re-printed the card. The keyword regex
            # stays below as the fallback for when the classifier did NOT say
            # product_info.
            if data.get("classified_category") == "product_info":
                return True
            if _PRICE_AVAILABILITY_RE.search(text) or _SIZE_QUERY_RE.search(text):
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
                and text_body.strip()
                and not _parse_product_list_selection(messages)[0]
                and not _parse_details_button_id(
                    (messages.get("interactive", {}) or {})
                    .get("button_reply", {})
                    .get("id", "")
                )
            ):
                asks_about_product = (
                    data.get("classified_category") == "product_info"
                    or _PRICE_AVAILABILITY_RE.search(text_body)
                )
                if asks_about_product:
                    product = _product_from_last_viewed(user_profile)
                    if product:
                        _save_last_viewed_product(user_profile, product)
                        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                        answer = await _answer_product_question(
                            text_body,
                            product,
                            phone_number=phone_number,
                            client_id=data.get("client_id", "kisna"),
                        )
                        # Falling back to the card is only for an LLM failure —
                        # it is what the customer is already looking at.
                        data["bot_response"] = [
                            {
                                "type": "text",
                                "text": answer or format_product_buy_caption(product),
                            }
                        ]
                        return data
                if (
                    data.get("classified_category") == "product_info"
                    and _SIZE_QUERY_RE.search(text_body)
                ):
                    data["bot_response"] = [{"type": "text", "text": _SIZE_VARIANT_REPLY, "_compose": "product_size"}]
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
                data["bot_response"] = [{"type": "text", "text": _CACHE_MISS_TEXT, "_compose": "system_error"}]
                return data

            cached = _find_cached_product(user_profile, product_id)

            if cached:
                enriched = await _enrich_product_image(
                    cached,
                    title_hint=list_title,
                )
                _save_last_viewed_product(user_profile, enriched)
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                data["bot_response"] = _build_buy_now_response(enriched)
                logger.info(
                    "Product Buy Now flow from cache",
                    extra={
                        "phone_number": phone_number,
                        "product_id": product_id,
                    },
                )
                return data

            if is_list_selection:
                retry = await _retry_product_search(data, list_title, product_id)
                if retry:
                    data["bot_response"] = retry
                    return data

            data["bot_response"] = [{"type": "text", "text": _CACHE_MISS_TEXT, "_compose": "system_error"}]
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
                    "_compose": "system_error",
                }
            ]
            return data
