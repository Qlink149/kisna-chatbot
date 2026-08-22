import json
import math
import os
import re
import time

from kisna_chatbot.integrations.clara_api import ClaraAPIError, search_products
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.classifier import is_greeting_message
from kisna_chatbot.processors.service_list import (
    build_budget_text_prompt,
    build_custom_budget_prompt,
    build_greeting_welcome_bot_responses,
    build_main_menu_bot_response,
    build_vague_slot_fill_response,
)
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.entity_extractor import (
    _NEVER_INHERIT_FIELDS,
    apply_llm_evidence_gate,
    apply_occasion_style_hints,
    build_search_context,
    enrich_entities_for_client_filter,
    entities_to_api_params,
    entities_for_client_filter,
    combine_search_entities,
    extract_fulfillment,
    extract_fulfillment_change,
    has_clara_search_scope,
    merge_search_entities,
    normalize_entities_for_clara,
    merge_entity_llm_supplement,
    extract_entities,
    extract_entities_with_llm,
    extract_structured_fields,
    filter_products_by_entities,
    filter_products_by_extracted_extras,
    is_unrecognizable_input,
    normalize_category_for_api,
    normalize_material_for_api,
    finalize_search_entities,
    resolve_api_page_size,
    title_redundant_with_category,
)
from kisna_chatbot.utils.jewellery_profile import (
    entities_to_jewellery_profile,
    merge_jewellery_profile,
)
from kisna_chatbot.utils.session_state import start_store_lookup
from kisna_chatbot.processors.search_confirmation import (
    build_confirm_prompt,
    build_correction_prompt,
    build_search_recap,
    clear_confirm_state,
    get_pending_search,
    has_pending_search,
    is_awaiting_correction,
    is_confirm_enabled,
    is_confirm_interactive,
    parse_confirm_reply,
    pop_pending_search,
    set_pending_search,
    should_confirm,
    AWAITING_CORRECTION_KEY,
)
from kisna_chatbot.processors.filter_validation import (
    is_filter_fix_interactive,
    parse_filter_fix_button,
    pop_pending_filter_fix,
    resolve_filter_fix_value,
)
from kisna_chatbot.processors.shopping_wizard import (
    ANY_SLOT,
    WIZARD_CARRYOVER_KEYS as _WIZARD_CARRYOVER_KEYS,
    advance_wizard,
    build_wizard_summary,
    clear_wizard_state,
    entities_from_wizard,
    filter_wizard_carryover,
    is_wizard_active,
    is_wizard_interactive,
    should_start_wizard,
    start_wizard,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.kisna_url_tracking import kisna_home_url
from kisna_chatbot.utils.rakhi_season import (
    apply_rakhi_title_hint,
    inherit_rakhi_title,
    prior_rakhi_title,
)
from kisna_chatbot.utils.product_formatter import (
    BROWSE_PRODUCTS_GLOBAL_TITLE,
    build_catalogue_url,
    build_product_url,
    format_product_buy_caption,
    format_product_image_caption,
    format_zero_results_message,
    get_product_display_price,
    get_product_image_url_for_whatsapp,
    get_whatsapp_safe_image_url,
)

_MAX_IMAGE_PRODUCTS = 3
PAGE_SIZE = 3
_CAROUSEL_SCAN_LIMIT = 15
_BUDGET_SCAN_MAX_PAGES = 5
_SHOW_MORE_PAGE_RETRIES = 2
_MAX_SHOWN_IDS = 100
_SHOWN_IDS_TRIM_TO = 50
_SEARCH_SESSION_EXPIRY_SECONDS = 2 * 60 * 60  # 2 hours
_MAX_CUSTOM_BUDGET_ATTEMPTS = 3

# Price-only refinement fast-path — regex for price signals only
_PRICE_ONLY_SIGNAL_RE = re.compile(
    r"\b("
    r"under|below|above|over|upto|up\s+to|maximum|minimum|max|min|"
    r"tak|se\s+upar|se\s+zyada|se\s+kam|"
    r"\u20b9|k\b|lakh|lac|hazaar|thousand|"
    r"\d{3,}"
    r")\b",
    re.I,
)


def _is_price_only_refinement(
    user_message: str,
    user_profile: dict,
) -> bool:
    """
    Returns True when:
      1. User is in an active product_search session
         (has last_search_filters with category or material_type)
      2. The current message adds ONLY price information
         (no category, material, title, collection, etc.)

    In this case the intent is unambiguous regardless of
    classifier confidence — inherit prior context + apply price.
    """
    prior = user_profile.get("last_search_filters") or {}
    has_prior_context = bool(
        prior.get("category")
        or prior.get("material_type")
        or prior.get("collection")
        or prior_rakhi_title(prior)
    )
    if not has_prior_context:
        return False

    # Use regex-only extractor (fast, no LLM)
    entities = extract_entities(user_message)

    has_price = bool(
        entities.get("min_price") is not None
        or entities.get("max_price") is not None
        or _PRICE_ONLY_SIGNAL_RE.search(user_message)
    )
    has_other = any(
        entities.get(k)
        for k in [
            "category",
            "material_type",
            "title",
            "collection",
            "karat",
            "metal_colour",
            "occasion",
            "style",
            "gender",
            "action",
        ]
    )
    return has_price and not has_other


def _compute_show_more_retries(filter_ratio: float, api_page_size: int) -> int:
    """Total API pages to attempt per show-more when client filters may be sparse.

    ``filter_ratio`` = client_survivors / server_page_size (not vs full catalogue).

    Worked examples (PAGE_SIZE=10, api_page_size=30):
      - rose gold rings under 50k: 4 survivors of 30 → ratio≈0.133 →
        ceil(10/(0.133*30))≈3 pages → max(base, 3)
      - 18KT only (client-side leftover after colour server filter): 12/30 →
        ratio=0.4 → ceil(10/(0.4*30))≈1 → base retries only
      - no client filter: ratio=1.0 → base (1+_SHOW_MORE_PAGE_RETRIES)

    With ratio=1.0 (no filtering) returns the default 1+_SHOW_MORE_PAGE_RETRIES.
    For low ratios, fetches enough pages to have a reasonable chance of finding
    PAGE_SIZE new matching products, capped at 15 to avoid runaway fetching.
    """
    base = 1 + _SHOW_MORE_PAGE_RETRIES
    if filter_ratio >= 1.0 or filter_ratio <= 0.0:
        return base
    pages_needed = math.ceil(PAGE_SIZE / (filter_ratio * api_page_size))
    return max(base, min(pages_needed, 15))


_SEARCH_CAT_LIST_MSGID = "search$cat$list"

_PREF_CAT_REFINE_TITLES = {
    "rings": "pref$cat$ring",
    "earrings": "pref$cat$earring",
    "necklaces": "pref$cat$necklace",
}

_PREF_CAT_ENTITY_MAP: dict[str, dict] = {
    "ring": {"category": "ring"},
    "earring": {"category": "earring"},
    "necklace": {"category": "necklace"},
    "pendant": {"category": "pendant"},
    "bangle_bracelet": {"categories": ["bangle", "bracelet"]},
    "mangalsutra": {"category": "mangalsutra"},
    "maang_tikka": {"category": "maang_tikka"},
    "solitaire": {"category": "ring", "title": "solitaire"},
    "nose_wear": {"category": "nosewear"},
    "watch_wear": {"category": "watchwear"},
    "mangalsutra_bracelet": {"category": "mangalsutra", "title": "bracelet"},
    "pendant_set": {"category": "pendant_set"},
    "necklace_set": {"category": "necklace_set"},
}

_GENERIC_ERROR = (
    "Sorry, we couldn't search the catalogue right now. Please try again in a moment."
)
_CATALOG_NOT_CONFIGURED = (
    "Our jewellery catalogue isn't connected yet. You can still check offers, "
    "find a store, or track an order — just tell me what you need."
)
_PROMPT_TEXT = (
    "Tell me what you're looking for — e.g. *gold ring*, "
    "*diamond necklace under 50k*, or *evil eye collection*."
)
_SESSION_EXPIRED_TEXT = (
    "Your search session has expired. What jewellery are you looking for?"
)


def _all_results_seen_text(total: int) -> str:
    return (
        f"You have seen all {total} results!\n"
        f"Browse more on our website: {kisna_home_url()}"
    )


def _no_more_new_text() -> str:
    return (
        f"No more new results. Browse full collection: "
        f"{kisna_home_url()}"
    )


def _no_more_in_budget_text() -> str:
    return (
        f"No more results within your budget.\n"
        f"Browse full collection: {kisna_home_url()}"
    )


_ENTITY_KEYS = (
    "category",
    "material_type",
    "min_price",
    "max_price",
    "title",
    "gender",
    "fulfillment",
    # Server-side meta / collection (Phase 3) — must be in the identity key so
    # drop_meta is not deduped against the full strategy.
    "karat",
    "metal_colour",
    "collection",
)

_MATERIAL_BUTTON_MSGIDS = frozenset({"search$material$gold", "search$material$diamond"})
_PRODUCT_BUTTON_MSGIDS = frozenset(
    {"product$similar", "product$store", "product$browse"}
)
_SEARCH_BUTTON_MSGIDS = frozenset({"search$more", "search$explore"})
_UNSUPPORTED_CATEGORY_NOTE = (
    "I'll show you our full collection since we don't have a specific filter for that."
)

# KISNA carries only gold, diamond, and gemstone — silver / platinum / pearl are
# not sold. Never imply we have them; be honest and pivot to what we do offer.
_UNSUPPORTED_MATERIAL_NOTE = (
    "We specialise in *gold, diamond, and gemstone* jewellery — we don't carry "
    "silver, platinum, or pearl. Here are some beautiful options we do have 💎"
)
_SIZE_QUERY_RE = re.compile(
    r"\b(size|sizes|variant|variants|karat|kt\b|available|18kt|14kt|22kt|chain)\b",
    re.I,
)

_CHEAPEST_RE = re.compile(
    r"\b(cheapest|cheaper|sabse\s+sasta|most\s+affordable|lowest\s+price|sasta)\b",
    re.I,
)

# Price / details question about an already-shown product ("iska price kya hai",
# "what's the price", "kitna hai", "cost").
_PRICE_INFO_RE = re.compile(
    r"\b(price|cost|kitna|kitne|kimat|keemat|daam|rate|mrp|how\s+much)\b",
    re.I,
)
# Demonstrative reference to something already shown.
_REF_PRONOUN_RE = re.compile(
    r"\b(this|that|it|its|these|those|iska|iski|isme|is\s+ka|is\s+me|"
    r"yeh|ye|woh|wo|uska|inka|inki)\b",
    re.I,
)

_BROWSE_ALL_RE = re.compile(
    r"\b(sab\s+dikhao|show\s+me\s+everything|browse\s+all)\b",
    re.I,
)

_SHOW_MORE_RE = re.compile(
    r"\b(show\s+more|more|next|aur\s+dikhao|next\s+3|kuch\s+aur|show\s+next|and\s+more|"
    r"any\s+other\s+options?|anything\s+else|something\s+else|other\s+options?|"
    r"alternate\s*s?|alternatives?|aur\s+kuch|koi\s+aur)\b",
    re.I,
)

_SIMILAR_REQUEST_RE = re.compile(
    r"\b(similar|see\s+similar|more\s+like\s+this|like\s+this|"
    r"is\s+jaisa|isi?\s+jaisa|jaisa\s+aur|aise\s+hi|same\s+style)\b",
    re.I,
)

_ASK_PINCODE_TEXT = (
    "Share your pincode or city and I'll help you find the nearest Kisna store."
)

_BUDGET_POSTBACK_RE = re.compile(r"^pref\$budget\$(\d+)-(\d+)$")
_CUSTOM_BUDGET_RANGE_RE = re.compile(
    r"^\s*([\d,]+)\s*(?:-|to|se)\s*([\d,]+)(?:\s*tak)?\s*$",
    re.I,
)


def _entities_from_pref_cat(cat_key: str) -> dict | None:
    mapped = _PREF_CAT_ENTITY_MAP.get(cat_key)
    if not mapped:
        return None
    entities = _empty_entities()
    for key, val in mapped.items():
        entities[key] = val
    if entities.get("categories"):
        entities["multi_category"] = len(entities["categories"]) >= 2
    return entities


def _parse_pref_cat_button_postback(messages: dict) -> str | None:
    """Extract pref$cat$ postback from a quick-reply button tap."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return None
    button_reply = interactive.get("button_reply", {})
    raw_id = button_reply.get("id", "")
    postback = ""
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            postback = str(parsed.get("postbackText") or "")
    except (json.JSONDecodeError, TypeError):
        pass
    if postback.startswith("pref$cat$"):
        return postback
    title = (button_reply.get("title") or "").strip().lower()
    return _PREF_CAT_REFINE_TITLES.get(title)


def _category_label_plural(category: str | None) -> str:
    if not category:
        return "pieces"
    label = category if category.endswith("s") else f"{category}s"
    if label == "mangalsutras":
        return "mangalsutra"
    return label.replace("_", " ")


def _material_display_label(material: str | None) -> str:
    if not material:
        return ""
    if material in ("rose_gold", "white_gold"):
        return "gold"
    return material.replace("_", " ")


# Varied natural openers so the intro never feels like the same canned line.
# {desc} = a phrase like "gold rings under ₹40,000". Kept in English by design
# (product listings stay English); variety alone removes the robotic feel.
_INTRO_TEMPLATES = (
    "Here are some lovely {desc} I picked for you ✨",
    "Great choice! Take a look at these {desc} 💍",
    "These {desc} are gorgeous — have a look 💎",
    "Found some beautiful {desc} for you ✨",
    "Here's what caught my eye in {desc} 💍",
    "Ooh, these {desc} are stunning — check them out 💎",
    "A few {desc} you might love 👇",
)
_INTRO_OCCASION_TEMPLATES = (
    "Here are some beautiful options for your {occ} 💎",
    "Perfect for your {occ} — take a look ✨",
    "These would be lovely for your {occ} 💍",
)
_INTRO_GENERIC_TEMPLATES = (
    "Here are a few pieces I think you'll love 💍",
    "Take a look at some of our favourites ✨",
    "Here's a handpicked selection for you 💎",
)


def _intro_descriptor(entities: dict) -> str:
    """Compact natural noun phrase, e.g. 'rose gold 18KT rings'.

    Never labels the results with an unsupported material (silver/platinum/
    pearl) — those products aren't actually that material, so calling them
    "silver rings" would be misleading.
    """
    parts: list[str] = []
    if entities.get("metal_colour"):
        parts.append(str(entities["metal_colour"]).lower())
    if entities.get("karat"):
        parts.append(str(entities["karat"]))
    material = (
        None
        if entities.get("unsupported_material")
        else _material_display_label(entities.get("material_type"))
    )
    if material:
        parts.append(material)
    category = _category_label_plural(entities.get("category"))
    parts.append(category or "pieces")
    desc = " ".join(p for p in parts if p)
    return " ".join(desc.split())


def build_search_intro(entities: dict, *, relaxed: bool = False) -> str:
    """Varied, natural intro reflecting the active search filters (English)."""
    import random

    entities = enrich_entities_for_client_filter(entities)
    prefix = ""
    if relaxed:
        prefix = "Couldn't find an exact match, but here are the closest options:\n\n"

    occasion = entities.get("occasion")
    if occasion and not entities.get("category"):
        occ_label = str(occasion).replace("_", " ")
        return prefix + random.choice(_INTRO_OCCASION_TEMPLATES).format(occ=occ_label)

    context = build_search_context(entities)
    if context == "KISNA Jewellery" and not entities.get("category"):
        return prefix + random.choice(_INTRO_GENERIC_TEMPLATES)

    desc = _intro_descriptor(entities)
    return prefix + random.choice(_INTRO_TEMPLATES).format(desc=desc)


async def _current_message_entities(data: dict, text: str | None) -> dict:
    """Entities stated by the CURRENT message, for paths off the search route.

    The shopping wizard and the search-confirmation correction handler used to
    read the classifier's extraction because it was the only entity source that
    reads native script — ``extract_entities`` is Latin-only. That made them
    inherit the classifier's context bleed: it sees chat history and shown
    products, so "under 20k" after a women's gold-ring search comes back
    carrying category=ring, material=gold, gender=women.

    The context-free entity extractor is the single source of truth for what
    THIS message states, in any script (the same call the main search path
    makes at _execute_search). It returns {} on any failure, in which case we
    fall back to whatever the classifier left on ``data`` so these paths never
    lose their Indic capability if the extractor call is down.
    """
    if not (text or "").strip():
        return dict(data.get("llm_extracted_entities") or {})
    extracted = await extract_entities_with_llm(
        user_query=text,
        client_id=data.get("client_id", "kisna"),
        phone_number=data.get("phone_number"),
    )
    if extracted:
        return dict(extracted)
    return dict(data.get("llm_extracted_entities") or {})


# Slots that NARROW a pending recap instead of replacing it. Naming a different
# category / collection / title is a new request; adding a budget or an audience
# to the search we just read back is not.
_CONFIRM_REFINEMENT_SLOTS = (
    "min_price",
    "max_price",
    "gender",
    "material_type",
    "karat",
    "metal_colour",
    "fulfillment",
)


def _confirm_refinement_merge(pending: dict, text: str | None) -> dict | None:
    """Merge a narrowing reply into a pending recap, or None if it is a new ask.

    Uses the deterministic extractor on purpose: it is free (this runs on every
    non-yes/no turn during a confirmation) and budgets are exactly what it reads
    best. A native-script refinement it cannot read simply falls through to the
    previous behaviour — no regression, just no rescue.
    """
    if not (text or "").strip():
        return None
    entities = dict(pending.get("entities") or {})
    if not entities:
        return None

    stated = extract_entities(text)
    for key in ("category", "collection", "title"):
        value = stated.get(key)
        if value is not None and value != entities.get(key):
            return None
    if stated.get("categories"):
        return None

    refinement = {
        key: stated[key]
        for key in _CONFIRM_REFINEMENT_SLOTS
        if stated.get(key) is not None
    }
    if not refinement:
        return None
    # A price refinement replaces the old band outright rather than merging one
    # half of it ("under 20k" after "10k-30k" must not keep min=10000).
    if "min_price" in refinement or "max_price" in refinement:
        entities["min_price"] = stated.get("min_price")
        entities["max_price"] = stated.get("max_price")
        refinement.pop("min_price", None)
        refinement.pop("max_price", None)
    entities.update(refinement)
    return entities


def _handle_product_reference(data: dict) -> dict | None:
    """Open the shown product the LLM resolved (1-based product_reference).

    The LLM matches "the second one" / "बीच वाला" / "the gold one" against the
    numbered shown list and returns its index — this just opens that product.
    """
    user_profile = data.get("user_profile", {})
    entities = data.get("llm_extracted_entities") or {}
    ref = entities.get("product_reference")
    if not ref:
        return None
    shown = user_profile.get("last_search_products") or []
    if not (1 <= ref <= len(shown)):
        return None
    return _open_shown_product(data, shown[ref - 1])


def _normalize_product_title_query(text: str) -> str:
    cleaned = (text or "").strip().strip("*").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold()


def _match_shown_product_by_title(query: str, shown: list[dict]) -> dict | None:
    """Exact / containment match against currently shown product titles."""
    needle = _normalize_product_title_query(query)
    if not needle or len(needle) < 4:
        return None
    best: dict | None = None
    best_len = 0
    for product in shown:
        title = product.get("title") or product.get("name") or ""
        norm = _normalize_product_title_query(title)
        if not norm:
            continue
        if needle == norm or needle in norm or norm in needle:
            if len(norm) > best_len:
                best = product
                best_len = len(norm)
    return best


def _open_shown_product(data: dict, product: dict) -> dict:
    user_profile = data.get("user_profile", {})
    from kisna_chatbot.processors.product_details_agent import _save_last_viewed_product
    from kisna_chatbot.processors.shopping_wizard import clear_wizard_state

    clear_wizard_state(user_profile)
    _save_last_viewed_product(user_profile, product)
    image_msg = build_product_image_with_cta_message(product)
    responses: list[dict] = []
    if image_msg:
        responses.append(image_msg)
    else:
        name = product.get("title") or product.get("name") or "This piece"
        price = get_product_display_price(product)
        price_txt = f"₹{int(price):,}" if price and price > 0 else "on the product page"
        buy_url = build_product_url(product)
        responses.append(
            {
                "type": "cta_url",
                "text": f"*{name}* — {price_txt}",
                "display_text": "Buy on KISNA",
                "url": buy_url,
            }
        )
    data["bot_response"] = responses
    data["classified_category"] = "product_info"
    return data


def _handle_typed_product_title(data: dict, query: str) -> dict | None:
    """User typed a shown product name — open that card, do not restart wizard."""
    user_profile = data.get("user_profile", {})
    shown = user_profile.get("last_search_products") or []
    if not shown:
        return None
    product = _match_shown_product_by_title(query, shown)
    if not product:
        return None
    return _open_shown_product(data, product)


def _handle_compare(data: dict) -> dict | None:
    """Grounded comparison of the shown products — factual, never invented.

    Uses only the shown products' real names/prices/material. Price facts are
    deterministic; the closing note is honest and non-fabricated.
    """
    user_profile = data.get("user_profile", {})
    shown = user_profile.get("last_search_products") or []
    priced = [
        (get_product_display_price(p), p)
        for p in shown[:5]
        if get_product_display_price(p) > 0 and (p.get("title") or p.get("name"))
    ]
    if len(priced) < 2:
        return None
    priced.sort(key=lambda x: x[0])
    cheapest_price, cheapest = priced[0]
    priciest_price, priciest = priced[-1]

    def _nm(p: dict) -> str:
        return p.get("title") or p.get("name") or "piece"

    lines = ["Here's how they compare 👇", ""]
    for price, p in priced:
        lines.append(f"• {_nm(p)} — ₹{int(price):,}")
    lines.append("")
    lines.append(
        f"The most affordable is *{_nm(cheapest)}* at ₹{int(cheapest_price):,}; "
        f"the most premium is *{_nm(priciest)}* at ₹{int(priciest_price):,}. "
        "They're all lovely — it really comes down to your style and budget 💍 "
        "Want a closer look at any one?"
    )
    data["bot_response"] = [
        {"type": "text", "text": "\n".join(lines), "_compose": "compare"}
    ]
    return data


def _entities_all_none(entities: dict) -> bool:
    if entities.get("multi_category") or entities.get("categories"):
        return False
    return all(entities.get(key) is None for key in _ENTITY_KEYS)


def _collection_browse_skips_wizard(entities: dict) -> bool:
    """A named, resolvable collection with no category is itself enough to
    search directly -- "show me something in evil eye" shouldn't have to
    answer "what are you looking for" first when the API happily returns a
    mixed-category spread for collectionId alone (verified: 34 products,
    rings/pendants/bracelets mixed, for Evil Eye Collection).
    """
    if entities.get("category") or entities.get("categories"):
        return False
    collection = entities.get("collection")
    if not collection:
        return False
    from kisna_chatbot.integrations.clara_filters import get_collection_id

    return bool(get_collection_id(str(collection)))


def _handle_product_info_followup(data: dict, query: str) -> dict | None:
    """Answer product_info follow-ups from cached search/viewed products."""
    user_profile = data.get("user_profile", {})
    # Treat as a follow-up when classified product_info, OR when the message is
    # clearly a reference-price question ("iska price kya hai") that names no new
    # search subject — so it never re-runs a fresh search by mistake.
    ref_price_followup = bool(
        _PRICE_INFO_RE.search(query)
        and _REF_PRONOUN_RE.search(query)
        and not _names_new_search_subject(query)
    )
    if data.get("classified_category") != "product_info" and not ref_price_followup:
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
        from kisna_chatbot.processors.product_details_agent import _save_last_viewed_product
        _save_last_viewed_product(user_profile, cheapest)
        bot_response: list[dict] = [
            {
                "type": "text",
                "text": "The most affordable from your recent search:",
                "_compose": "product_info",
            }
        ]
        raw_url = get_product_image_url_for_whatsapp(cheapest)
        url = get_whatsapp_safe_image_url(raw_url)
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
                "_compose": "product_info",
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
                "_compose": "product_info",
            }
        ]
        return data

    # Generic "what's the price / kitna hai" about an already-shown item.
    if _PRICE_INFO_RE.search(query):
        # A specific product was viewed → answer about that one.
        if last_viewed:
            from kisna_chatbot.processors.product_details_agent import (
                _product_from_last_viewed,
            )

            product = _product_from_last_viewed(user_profile) or last_viewed
            image_msg = build_product_image_with_cta_message(product)
            responses: list[dict] = []
            if image_msg:
                responses.append(image_msg)
            else:
                price = get_product_display_price(product)
                name = product.get("title") or product.get("name") or "This piece"
                price_txt = f"₹{int(price):,}" if price and price > 0 else "on the product page"
                responses.append(
                    {"type": "text", "text": f"*{name}* — {price_txt}"}
                )
            data["bot_response"] = responses
            return data

        # Only a list was shown → recap the shown pieces with prices, ask which.
        if last_search:
            priced_lines: list[str] = []
            for p in last_search[:5]:
                price = get_product_display_price(p)
                name = p.get("title") or p.get("name")
                if name and price and price > 0:
                    priced_lines.append(f"• {name} — ₹{int(price):,}")
            if priced_lines:
                text = (
                    "Here are the ones I showed you, with prices 👇\n\n"
                    + "\n".join(priced_lines)
                    + "\n\nWant a closer look at any of them? Just tell me the name 💍"
                )
                data["bot_response"] = [
                    {"type": "text", "text": text, "_compose": "product_info"}
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
        "karat": None,
        "metal_colour": None,
        "size": None,
        "collection": None,
        "gender": None,
        "occasion": None,
        "style": None,
        "action": None,
        "fulfillment": None,
    }


def _category_only_entities(entities: dict) -> dict:
    """Strip all filters except category scope for final fallback search."""
    cat_only = _empty_entities()
    if entities.get("categories"):
        cat_only["categories"] = list(entities["categories"])
        cat_only["multi_category"] = entities.get("multi_category", False)
        cat_only["secondary_category"] = entities.get("secondary_category")
    if entities.get("category"):
        cat_only["category"] = entities["category"]
    return cat_only


def _format_price_range_suffix(entities: dict) -> str:
    """Human-readable price constraint for fallback prefix notes."""
    min_p = entities.get("min_price")
    max_p = entities.get("max_price")
    if min_p is not None and max_p is not None:
        return f" in the ₹{int(min_p):,}–₹{int(max_p):,} range"
    if max_p is not None:
        return f" under ₹{int(max_p):,}"
    if min_p is not None:
        return f" above ₹{int(min_p):,}"
    return ""


def _category_singular_label(category: str | None) -> str:
    """Display label for 'in {category}' phrasing (e.g. maang tikka, ring)."""
    plural = _category_label_plural(category)
    if plural == "mangalsutra":
        return plural
    if plural.endswith("s"):
        return plural[:-1]
    return plural


def _clear_preference_state(user_profile: dict) -> None:
    for key in (
        "preference_step",
        "pref_material",
        "pref_type",
        "pref_category",
        "pref_title",
        "awaiting_custom_budget",
    ):
        user_profile.pop(key, None)


def _entities_from_preferences(user_profile: dict) -> dict:
    entities = {
        **_empty_entities(),
        "material_type": user_profile.get("pref_material"),
        "category": user_profile.get("pref_category") or user_profile.get("pref_type"),
    }
    if user_profile.get("pref_title"):
        entities["title"] = user_profile.get("pref_title")
    return entities


def _snap_single_price_to_band(price: float) -> tuple[int, int | None]:
    """Delegates to the single source of truth in entity_extractor."""
    from kisna_chatbot.processors.entity_extractor import (
        _snap_single_price_to_band as _snap,
    )

    lo, hi = _snap(price)
    return int(lo), (int(hi) if hi is not None else None)


def _parse_custom_budget_text(text: str) -> tuple[int | None, int | None]:
    extracted = extract_entities(text or "")
    min_p = extracted.get("min_price")
    max_p = extracted.get("max_price")
    if min_p is not None or max_p is not None:
        if min_p is not None and max_p is not None:
            return int(min_p), int(max_p)
        if max_p is not None:
            # "Under X" / "Below X" — entity extractor already resolved the direction;
            # don't snap to a band above X, treat it as a hard ceiling.
            return 0, int(max_p)
        if min_p is not None:
            # "Above X" / "Over X" — entity extractor resolved direction; no upper cap.
            return int(min_p), None

    normalized = (text or "").strip().replace(",", "")
    range_match = _CUSTOM_BUDGET_RANGE_RE.match(normalized)
    if range_match:
        low = int(range_match.group(1))
        high = int(range_match.group(2))
        return min(low, high), max(low, high)

    if normalized.isdigit():
        return _snap_single_price_to_band(float(normalized))
    return None, None


def _parse_budget_flow_reply(messages: dict) -> str | None:
    """Return the budget_input string from a WhatsApp Flow nfm_reply, or None."""
    interactive = messages.get("interactive") if messages else None
    if not interactive or "nfm_reply" not in interactive:
        return None
    try:
        flow_data = json.loads(interactive["nfm_reply"].get("response_json", "{}"))
    except (ValueError, TypeError):
        return None
    budget_text = flow_data.get("budget_input")
    return str(budget_text).strip() if budget_text else None


def _names_new_search_subject(query: str) -> bool:
    """Deterministic: does the current message name a category/material/collection?

    Regex-only (no LLM). A message that names a subject is a NEW search, never
    pagination — even if the LLM loosely tagged action='more' because the text
    contained 'dikhao' / 'show'. Guards against 'gold rings dikhao' paging the
    previous necklace results.
    """
    ents = extract_entities(query or "")
    return bool(
        ents.get("category")
        or ents.get("categories")
        or ents.get("material_type")
        or ents.get("collection")
        or ents.get("title")
    )


def _is_show_more_request(query: str, data: dict) -> bool:
    user_profile = data.get("user_profile", {})
    # Gap 8: If classifier explicitly routed to a non-product intent, don't hijack
    # with show-more. Prevents "more" in order tracking context from surfacing stale
    # product results.
    classified = data.get("classified_category") or ""
    if classified and classified not in ("product_search", "product_info"):
        return False
    filters = user_profile.get("last_search_filters")
    if not filters:
        return False
    # A message naming a new subject ("gold rings", "necklaces", "नेकलेस") is a
    # fresh search, never pagination — overrides a stray action='more'. Check the
    # LLM's extracted category/material FIRST (language-agnostic) and fall back to
    # the Latin regex only for romanized text the LLM may have skipped.
    llm_entities = data.get("llm_extracted_entities") or {}
    if llm_entities.get("category") or llm_entities.get("material_type"):
        return False
    if _names_new_search_subject(query):
        return False
    if llm_entities.get("action") == "more":
        # If the classifier also extracted new price bounds that differ from the
        # saved session, this is a budget refinement, not pagination — let it
        # fall through to the normal search path so the new prices are applied.
        new_min = llm_entities.get("min_price")
        new_max = llm_entities.get("max_price")
        if new_min is not None or new_max is not None:
            if (
                new_min != filters.get("min_price")
                or new_max != filters.get("max_price")
            ):
                return False
        return True
    return bool(_SHOW_MORE_RE.search(query or ""))


def _sort_products_by_price_target(
    products: list[dict], entities: dict
) -> list[dict]:
    min_p = entities.get("min_price")
    max_p = entities.get("max_price")
    target: float | None = None
    if min_p is not None and max_p is not None:
        target = (float(min_p) + float(max_p)) / 2
    elif max_p is not None:
        target = float(max_p)
    elif min_p is not None:
        target = float(min_p)

    if target is None or not products:
        return list(products)

    def _distance(product: dict) -> float:
        price = get_product_display_price(product)
        if price <= 0:
            return float("inf")
        return abs(price - target)

    return sorted(products, key=_distance)


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


def _product_id_key(product: dict) -> str:
    return str(product.get("_id") or product.get("id") or "")


async def _fetch_budget_filtered_products(
    api_params: dict,
    strategy_entities: dict,
    *,
    max_pages: int = _BUDGET_SCAN_MAX_PAGES,
    page_size: int | None = None,
) -> tuple[list[dict], int, int, list[dict]]:
    """Scan multiple API pages with price filters before budget fallback.

    Returns (matched_products, api_total_count, last_page, raw_api_sample).
    raw_api_sample is the first page from Clara (pre client-filter) for traces.
    """
    fetch_size = page_size or resolve_api_page_size(strategy_entities)
    collected: list[dict] = []
    seen_ids: set[str] = set()
    api_total = 0
    last_page = 1
    raw_sample: list[dict] = []

    for page_no in range(1, max_pages + 1):
        result = await search_products(
            **api_params, page_no=page_no, page_size=fetch_size
        )
        raw_products = result.get("products") or []
        if not raw_sample:
            raw_sample = list(raw_products)
        api_total = max(api_total, int(result.get("total_count") or 0))
        last_page = int(result.get("page") or page_no)

        for product in filter_products_by_entities(raw_products, strategy_entities):
            pid = _product_id_key(product)
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)
            collected.append(product)

        if collected:
            break
        if not _has_more_pages(page_no, api_total, fetch_size):
            break

    return collected, api_total, last_page, raw_sample


async def _fetch_multi_category_products(
    api_params: dict,
    clara_categories: list[str],
    strategy_entities: dict,
    *,
    page_size: int,
) -> tuple[list[dict], int, int, list[dict]]:
    """Query Clara once per category, merge, dedupe by product id, sort by price.

    Returns (matched_products, api_total_count, page, raw_api_sample).
    """
    collected: list[dict] = []
    seen_ids: set[str] = set()
    api_total = 0
    raw_sample: list[dict] = []

    for clara_category in clara_categories:
        params = dict(api_params)
        params["category"] = clara_category
        result = await search_products(
            **params, page_no=1, page_size=page_size
        )
        api_total += int(result.get("total_count") or 0)
        raw_products = result.get("products") or []
        if not raw_sample:
            raw_sample = list(raw_products)
        for product in filter_products_by_entities(raw_products, strategy_entities):
            pid = _product_id_key(product)
            if pid and pid in seen_ids:
                continue
            if pid:
                seen_ids.add(pid)
            collected.append(product)

    collected.sort(
        key=lambda product: get_product_display_price(product) or 0
    )
    return collected, api_total, 1, raw_sample

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
    """Return (filter_entities, note_kind, log_label) for progressive relaxation.

    Softest filters drop first so we keep jewellery essentials (category →
    gender → material → budget) longer than availability (ready-to-ship).
    """
    strategies: list[tuple[dict, str | None, str]] = []
    seen: set[tuple] = set()

    def add(ent: dict, note_kind: str | None, label: str) -> None:
        key = tuple(_normalize_entities(ent).items())
        if key not in seen:
            seen.add(key)
            strategies.append((ent, note_kind, label))

    add(entities, None, "full")

    # Ready-to-ship is a catalog subset — expand before dropping gold/budget.
    if entities.get("fulfillment"):
        no_fulfillment = {**entities, "fulfillment": None}
        add(no_fulfillment, "fulfillment", "drop_fulfillment")

    # Impossible karat/colour (and unmatched collectionId) hard-zero results;
    # drop before softening budget so we don't waste a round-trip.
    if (
        entities.get("karat")
        or entities.get("metal_colour")
        or entities.get("collection")
    ):
        no_meta = {
            **entities,
            "karat": None,
            "metal_colour": None,
            "collection": None,
        }
        # A named collection with real inventory can still be genuinely
        # empty for the requested gender/category (most named collections
        # skew heavily toward one gender) -- that reads very differently
        # from a fuzzy karat/colour mismatch, so it gets its own note_kind
        # when collection is the only reason this rung exists.
        has_karat_or_colour = bool(entities.get("karat") or entities.get("metal_colour"))
        meta_note = "meta" if has_karat_or_colour else "collection"
        add(no_meta, meta_note, "drop_meta")

    if entities.get("min_price") is not None or entities.get("max_price") is not None:
        no_price = {**entities, "min_price": None, "max_price": None}
        add(no_price, "budget", "drop_price")
        # Price-out + still ready-to-ship often stays empty; try budget-free
        # full catalog with material kept.
        if entities.get("fulfillment"):
            no_price_no_fulfillment = {
                **entities,
                "min_price": None,
                "max_price": None,
                "fulfillment": None,
            }
            add(no_price_no_fulfillment, "budget", "drop_price_fulfillment")

    if entities.get("title"):
        no_title = {**entities, "title": None}
        add(no_title, None, "drop_title")

    if entities.get("material_type"):
        no_material = {**entities, "material_type": None}
        if title_redundant_with_category(entities):
            no_material["title"] = None
        add(no_material, "material", "drop_material")

    if entities.get("title") and not title_redundant_with_category(entities):
        title_only = {**_empty_entities(), "title": entities["title"]}
        add(title_only, None, "title_only")

    cat_only = _category_only_entities(entities)
    if cat_only.get("category") or cat_only.get("categories"):
        add(cat_only, "category", "category_only")

    return strategies


def _fallback_prefix_note(
    note_kind: str | None,
    products: list[dict],
    original_entities: dict,
    strategy_entities: dict,
) -> str | None:
    if note_kind == "budget":
        min_p = original_entities.get("min_price")
        max_p = original_entities.get("max_price")
        if min_p is not None and max_p is not None and float(min_p) > 0:
            return (
                f"No pieces found in ₹{int(min_p):,}–₹{int(max_p):,} right now — "
                f"here are our closest picks ✨"
            )
        if max_p is not None:
            return (
                f"No pieces found under ₹{int(max_p):,} right now — "
                f"here are our closest picks ✨"
            )
        if min_p is not None:
            return (
                f"No pieces found above ₹{int(min_p):,} right now — "
                f"here are our closest picks ✨"
            )
        lowest = _lowest_price(products)
        if lowest is not None:
            return (
                f"Showing results outside your budget — "
                f"prices in this category start from ₹{lowest:,} ✨"
            )
        return "Showing results outside your budget:"
    if note_kind == "fulfillment":
        if original_entities.get("fulfillment") == "ready":
            return (
                "No ready-to-ship pieces matched those filters right now — "
                "here are matching options you might like ✨"
            )
        return "Here are more options beyond that availability filter ✨"

    if note_kind == "meta":
        return (
            "Couldn't match that karat/colour/collection exactly — "
            "here are the closest options ✨"
        )

    if note_kind == "collection":
        # Collection resolved fine and has real inventory -- it's just
        # genuinely empty for this gender/category combo (most named
        # collections skew heavily toward one gender). Naming it directly
        # is more honest than the generic "couldn't match" line above,
        # which reads like a fuzzy-matching failure rather than "0 in
        # stock for this combination."
        collection = original_entities.get("collection")
        collection_label = str(collection).strip().title() if collection else None
        if collection_label and not collection_label.lower().endswith("collection"):
            collection_label = f"{collection_label} Collection"
        gender_possessive = {
            "men": "men's",
            "women": "women's",
            "kids": "kids'",
        }.get(original_entities.get("gender") or "")
        cat_label = _category_label_plural(original_entities.get("category"))
        what = f"{gender_possessive} {cat_label}".strip() if gender_possessive else cat_label
        if collection_label:
            return (
                f"{collection_label} doesn't have {what} right now — "
                f"here are other {cat_label} you might like ✨"
            )
        return (
            "Couldn't match that collection exactly — "
            "here are the closest options ✨"
        )

    if note_kind == "material":
        material = original_entities.get("material_type") or "matching"
        cat_label = _category_label_plural(original_entities.get("category") or "jewellery")
        return (
            f"I couldn't find {material} {cat_label}, "
            f"but here are other {cat_label} options you might like:"
        )

    if note_kind == "category":
        category = original_entities.get("category") or "jewellery"
        cat_label = _category_label_plural(category)
        cat_in = _category_singular_label(category)
        material = original_entities.get("material_type")
        mat_label = _material_display_label(material) if material else ""
        price_suffix = _format_price_range_suffix(original_entities)
        if material:
            target = f"{mat_label} {cat_label}".strip()
        else:
            target = cat_label
        if price_suffix:
            missing = f"I couldn't find {target}{price_suffix}"
        elif material:
            missing = f"I couldn't find {target}"
        else:
            missing = f"I couldn't find an exact match for {cat_label}"
        return f"{missing}, but here's what we have in {cat_in}:"
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
    carousel_pool: list[dict] | None = None,
    prefix_note: str | None = None,
    show_more_intro: bool = True,
    page_size: int = PAGE_SIZE,
    intro_relaxed: bool = False,
) -> list[dict]:
    bot_response: list[dict] = []
    intro_text: str | None = None
    if show_more_intro:
        intro_text = build_search_intro(entities, relaxed=intro_relaxed)
    if prefix_note:
        intro_text = (
            f"{prefix_note}\n\n{intro_text}" if intro_text else prefix_note
        )
    if intro_text:
        bot_response.append(
            {"type": "text", "text": intro_text, "_compose": "search_intro"}
        )

    scan_pool = carousel_pool if carousel_pool is not None else products
    carousel_products, skipped_product_ids, scanned_count = _collect_carousel_products(
        scan_pool
    )

    for product in carousel_products:
        image_msg = build_product_image_with_cta_message(product)
        if image_msg:
            bot_response.append(image_msg)

    images_sent = len(carousel_products)

    if images_sent == 0 and products:
        # Grounded text fallback from API products — never invent names/weights.
        entries = []
        for product in products[:page_size]:
            name = product.get("title") or product.get("name") or "KISNA piece"
            price = get_product_display_price(product)
            heading = f"*{name}*"
            if price and price > 0:
                heading = f"{heading} — ₹{int(price):,}"
            entries.append(f"{heading}\n{build_product_url(product)}")
        bot_response.append(
            {
                "type": "text",
                "text": "Here are your results:\n\n" + "\n\n".join(entries),
                "_compose": "search_results_text",
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

    if products[:page_size]:
        bot_response.append(
            {
                "type": "cta_url",
                "text": "Want to explore more? See the full collection 👇",
                "display_text": "See Collection",
                "url": build_catalogue_url(entities),
            }
        )

    return bot_response


def build_product_image_with_cta_message(product: dict) -> dict | None:
    """Single product image with inline Buy on KISNA button."""
    raw_url = get_product_image_url_for_whatsapp(product)
    url = get_whatsapp_safe_image_url(raw_url)
    if not url:
        return None
    return {
        "type": "image_with_cta",
        "url": url,
        "caption": format_product_image_caption(product),
        "cta_url": build_product_url(product),
        "cta_title": "Buy on KISNA",
    }


def build_product_media_message(product: dict) -> dict | None:
    """Single image + caption for a product (used by search and details agents)."""
    raw_url = get_product_image_url_for_whatsapp(product)
    url = get_whatsapp_safe_image_url(raw_url)
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
    # Cap to avoid unbounded MongoDB growth (keep newest entries)
    if len(shown) > _MAX_SHOWN_IDS:
        user_profile["shown_product_ids"] = shown[-_SHOWN_IDS_TRIM_TO:]


def _filter_unshown_products(
    products: list[dict], shown_product_ids: list
) -> list[dict]:
    shown_set = {str(x) for x in shown_product_ids}
    return [p for p in products if _product_id(p) and _product_id(p) not in shown_set]


_BUDGET_REPLY_SIGNAL_RE = re.compile(
    r"\d|₹|\b(lakh|lac|lacs|lakhs|hazaar|hazar|hajar|crore|thousand|"
    r"das|bees|tees|chalis|pachas|paanch|panch|ek|do|teen|char|sau|"
    r"budget|tak|under|upto|below|above|between)\b",
    re.I,
)


# "Cheaper" moves the band to ~30% below the anchor; "pricier" ~30% above.
# Detection is LLM-only (price_direction entity from classifier / entity
# extractor prompts) — regex cannot cover multilingual phrasings. Only the
# band math lives here.
_PRICE_DIRECTION_FACTOR = 0.7


def _entities_for_price_direction(
    user_profile: dict, direction: str
) -> tuple[dict | None, int | None]:
    """Entities for a cheaper/pricier follow-up: keep category/material from the
    active search, move the price band ~30% from the anchor. Anchor = the active
    price filter, else the shown products' price range. (None, None) without
    context — caller falls through to normal routing."""
    filters = user_profile.get("last_search_filters") or {}
    prices = [
        p.get("price")
        for p in (user_profile.get("last_search_products") or [])
        if isinstance(p.get("price"), (int, float)) and p.get("price") > 0
    ]
    base = {
        k: v
        for k, v in filters.items()
        if k not in _NEVER_INHERIT_FIELDS and v is not None
    }
    base.pop("min_price", None)
    base.pop("max_price", None)
    entities = inherit_rakhi_title({**_empty_entities(), **base}, filters)

    if direction == "lower":
        anchor = filters.get("max_price") or (min(prices) if prices else None)
        if not anchor:
            return None, None
        bound = max(int(anchor * _PRICE_DIRECTION_FACTOR), 2000)
        entities["min_price"] = None
        entities["max_price"] = bound
        return entities, bound

    anchor = (
        filters.get("min_price")
        or filters.get("max_price")
        or (max(prices) if prices else None)
    )
    if not anchor:
        return None, None
    bound = int(anchor * (2 - _PRICE_DIRECTION_FACTOR))
    entities["min_price"] = bound
    entities["max_price"] = None
    return entities, bound


def _looks_like_budget_reply(user_message: str) -> bool:
    """True when the message plausibly contains a budget (digit or amount word).

    A sentence with neither ("इसका price बहुत ज्यादा है", "that's too costly")
    must NOT be force-parsed as a budget — it escapes to normal routing.
    """
    return bool(_BUDGET_REPLY_SIGNAL_RE.search(user_message or ""))


def _should_escape_custom_budget(user_message: str) -> bool:
    """
    Return True when the message is clearly a new product query or service
    request — not a budget answer.  Used to break out of the
    awaiting_custom_budget loop without requiring a valid budget string.

    Uses regex-only entity extraction (fast, zero latency, no LLM cost).
    """
    if not user_message or not user_message.strip():
        return False

    msg_lower = user_message.strip().lower()

    # Explicit escape keywords
    _ESCAPE_WORDS = {
        "menu", "cancel", "back", "nahi", "no", "skip",
        "nevermind", "change", "different", "kuch aur",
    }
    if msg_lower in _ESCAPE_WORDS:
        return True

    # A pagination/continuation phrase ("any other option", "kuch aur", ...) means
    # the user has moved on from the budget question — let it fall through to the
    # active search context instead of being swallowed by budget parsing.
    if _SHOW_MORE_RE.search(user_message):
        return True

    # Category keywords (English + common Hindi/Hinglish)
    _CATEGORY_KW = {
        "ring", "rings", "earring", "earrings", "necklace", "necklaces",
        "pendant", "pendants", "bangle", "bangles", "bracelet", "bracelets",
        "mangalsutra", "chain", "chains", "maang tikka", "maang tika",
        "nose pin", "watch", "solitaire",
        # Hindi
        "anguthi", "bali", "jhumka", "jhumki", "haar", "kangan", "kada", "payal",
    }
    for kw in _CATEGORY_KW:
        if kw in msg_lower:
            return True

    # Material keywords
    _MATERIAL_KW = {
        "gold", "diamond", "sona", "heera", "gemstone",
        "rose gold", "white gold", "silver",
    }
    for kw in _MATERIAL_KW:
        if kw in msg_lower:
            return True

    # Service-intent keywords
    _SERVICE_KW = {
        "offer", "store", "showroom", "track", "order",
        "return", "exchange", "complaint", "help",
        "hi", "hello", "hey", "namaste",
    }
    for kw in _SERVICE_KW:
        if kw in msg_lower:
            return True

    # Regex entity extraction (category or material_type present → product query)
    quick = extract_entities(user_message)
    if quick.get("category") or quick.get("material_type"):
        return True

    return False


def _clear_session_if_expired(user_profile: dict) -> None:
    """Clear all search/preference state when the search session has expired."""
    last_at = user_profile.get("last_search_at") or 0
    if last_at and (time.time() - last_at) > _SEARCH_SESSION_EXPIRY_SECONDS:
        from kisna_chatbot.processors.service_list import _clear_explore_browse_session
        _clear_explore_browse_session(user_profile)
        user_profile["awaiting_custom_budget"] = False
        user_profile["custom_budget_attempts"] = 0
        _clear_preference_state(user_profile)
        logger.info(
            "product_search: session expired — state cleared",
            extra={"age_seconds": int(time.time() - last_at)},
        )


class ProductSearchAgentV3(Processor):
    """Product catalog search via Clara API and WhatsApp media/list UI."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        user_profile = data.get("user_profile", {})

        if _material_button_msgid(messages):
            return True
        if _parse_pref_cat_button_postback(messages):
            return True
        if is_filter_fix_interactive(messages):
            return True
        if is_wizard_interactive(messages):
            return True
        if is_wizard_active(user_profile):
            return True
        # A pending recap owns the next turn ("yes" / "no" / the correction).
        if has_pending_search(user_profile):
            return True
        if is_confirm_interactive(messages):
            return True
        if _product_button_msgid(messages):
            return True
        if _search_button_msgid(messages):
            return True

        query_for_escape = _extract_search_query(messages)
        if user_profile.get("awaiting_custom_budget") and query_for_escape:
            # If the message is a product/service query, let it escape the budget loop
            if _should_escape_custom_budget(query_for_escape):
                user_profile["awaiting_custom_budget"] = False
                user_profile["custom_budget_attempts"] = 0
                # Fall through to normal routing (return True so process() runs)
            return True
        if _parse_budget_flow_reply(messages) is not None:
            return True

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
            if parsed[0].startswith("pref$"):
                return True
            if parsed[0] == _SEARCH_CAT_LIST_MSGID:
                return True
            if _is_browse_products_global_tap(parsed):
                return True
            if parsed[0].startswith("product_select$"):
                return False

        if _size_query_with_last_viewed(data):
            return False

        query = _extract_search_query(messages)
        if query is not None:
            if is_greeting_message(query):
                return True
            if _is_show_more_request(query, data):
                return True
            return True

        return False

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        messages = data.get("messages", {})

        if not self.should_run(data):
            return data

        user_profile = data.get("user_profile", {})

        # Honor Yes/No on a live recap BEFORE session expiry. Recap does not
        # previously stamp last_search_at, so a 2h-old browse timestamp would
        # pop pending_search and the tap would fall through to the generic
        # "couldn't help" fallback (button replies have no text.body).
        confirmed = await self._handle_search_confirmation(data, phone_number)
        if confirmed is not None:
            return confirmed

        _clear_session_if_expired(user_profile)

        filter_fix = parse_filter_fix_button(messages)
        if filter_fix is not None:
            entity_key, title = filter_fix
            return await self._handle_filter_fix(data, phone_number, entity_key, title)

        # Guided shopping wizard (smart-skip funnel)
        # Typed title of a currently shown product wins over wizard restart --
        # but ONLY when there's no active wizard step already claiming this
        # turn. A short, in-vocabulary slot answer ("gold" for material) can
        # collide with a shown product's title as a plain substring ("Emine
        # Evil Eye Gold Ring") once real products from an earlier browse are
        # sitting in last_search_products -- confirmed live, this silently
        # opened a product card and cleared an in-progress wizard instead of
        # accepting "gold" as the material answer it's currently asking for.
        title_query = _extract_search_query(messages)
        if title_query and not is_wizard_active(user_profile):
            titled = _handle_typed_product_title(data, title_query)
            if titled is not None:
                return titled

        if is_wizard_interactive(messages) or (
            is_wizard_active(user_profile)
            and (
                is_wizard_interactive(messages)
                or _extract_search_query(messages)
            )
        ):
            return await self._handle_shopping_wizard(data, phone_number)

        pref_postback = _parse_pref_cat_button_postback(messages)
        if pref_postback:
            return await self._handle_preference_list(
                data, phone_number, pref_postback
            )

        search_btn = _search_button_msgid(messages)
        if search_btn == "search$more":
            return await self._handle_show_more(data, phone_number)

        if search_btn and search_btn.startswith("search$also$"):
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            secondary = search_btn.rsplit("$", 1)[-1]
            last_filters = user_profile.get("last_search_filters") or _empty_entities()
            # Category change: do not reuse prior material/budget (parity with
            # merge_search_entities). Gender/fulfillment may stay; wizard asks
            # for material again so we don't silently show gold-only results.
            _also_drop = frozenset({"material_type", "min_price", "max_price"})
            inherited = {
                k: v
                for k, v in last_filters.items()
                if k not in _NEVER_INHERIT_FIELDS
                and k not in _also_drop
                and v is not None
            }
            entities = {
                **_empty_entities(),
                **inherited,
                "category": secondary,
                "categories": [secondary],
                "multi_category": False,
                "secondary_category": None,
            }
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            if should_start_wizard(entities):
                return await self._maybe_start_shopping_wizard(
                    data,
                    phone_number,
                    entities,
                    query=f"also:{secondary}",
                )
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
            if list_msgid.startswith("pref$") or (postback or "").startswith("pref$"):
                return await self._handle_preference_list(
                    data, phone_number, postback or ""
                )

            if list_msgid == _SEARCH_CAT_LIST_MSGID:
                if postback and postback.startswith("search$cat$"):
                    postback = postback.replace("search$cat$", "pref$cat$", 1)
                if postback and postback.startswith("pref$cat$"):
                    return await self._handle_preference_list(
                        data, phone_number, postback
                    )
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                if postback == "search$explore":
                    return await self._execute_search(
                        data, phone_number, _empty_entities(), query_label="browse_all"
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
                start_store_lookup(user_profile)
                data["bot_response"] = [{"type": "text", "text": _ASK_PINCODE_TEXT}]
                return data

            if product_msgid == "product$browse":
                entities = user_profile.get("last_search_filters") or {}
                if not entities:
                    data["bot_response"] = [build_vague_slot_fill_response()]
                    return data
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                # Explicit tap on already-confirmed filters — no re-ask.
                return await self._execute_search(
                    data,
                    phone_number,
                    entities,
                    query_label="browse_more",
                    confirm=False,
                )

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
                    confirm=False,
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

        budget_text = _parse_budget_flow_reply(messages)
        if budget_text is not None:
            return await self._handle_budget_flow_reply(data, phone_number, budget_text)

        query = _extract_search_query(messages)
        if not query:
            return data

        if is_greeting_message(query):
            user_profile["service_selected"] = ""
            data["classified_category"] = "greeting"
            data["bot_response"] = build_greeting_welcome_bot_responses(
                phone_number=phone_number,
                chat_history=user_profile.get("chat_history", []),
                user_profile=user_profile,
            )
            return data

        # An active pagination context (last_search_filters set) takes priority over
        # a stale awaiting_custom_budget slot-fill: a continuation phrase like "any
        # other option" should resume browsing, not get swallowed by budget parsing.
        if user_profile.get("awaiting_custom_budget") and _is_show_more_request(query, data):
            user_profile["awaiting_custom_budget"] = False
            user_profile["custom_budget_attempts"] = 0
            return await self._handle_show_more(data, phone_number)

        if user_profile.get("awaiting_custom_budget"):
            # Second escape gate (greeting check above may have passed; check again).
            # A message with no digits/amount words is not a budget answer either —
            # let normal routing (entity extraction / LLM) handle it.
            if _should_escape_custom_budget(query) or not _looks_like_budget_reply(query):
                user_profile["awaiting_custom_budget"] = False
                user_profile["custom_budget_attempts"] = 0
                # Fall through to normal search path below
            else:
                return await self._handle_custom_budget_input(data, phone_number, query)

        # Gap 5: If user interrupted a guided-browse preference flow with a direct text
        # query (not a budget answer), clear stale pref state before searching.
        if user_profile.get("preference_step") and not user_profile.get("awaiting_custom_budget"):
            logger.debug(
                "product_search: clearing interrupted preference state",
                extra={
                    "phone_number": phone_number,
                    "preference_step": user_profile.get("preference_step"),
                },
            )
            _clear_preference_state(user_profile)

        if _is_show_more_request(query, data):
            return await self._handle_show_more(data, phone_number)

        if _SIMILAR_REQUEST_RE.search(query) and user_profile.get("last_viewed_product"):
            last = user_profile.get("last_viewed_product") or {}
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            entities = _entities_from_last_viewed(last)
            label = last.get("title") or "similar pieces"
            return await self._execute_search(
                data,
                phone_number,
                entities,
                query_label=f"similar:{label}",
                confirm=False,
            )

        # Reference pick ("the second one", "बीच वाला") — the LLM resolved it to
        # a shown-product index; open that product.
        ref_result = _handle_product_reference(data)
        if ref_result is not None:
            return ref_result

        # Comparison of the shown products ("which is cheaper", "compare these").
        if data.get("classified_category") == "compare":
            compare_result = _handle_compare(data)
            if compare_result is not None:
                return compare_result
            # Nothing comparable on screen. Falling through used to reach the
            # "no entities" branch and restart the funnel, so "which is cheaper?"
            # was answered with "Hi! What are you looking for today?".
            shown = user_profile.get("last_search_products") or []
            if len(shown) == 1:
                return _open_shown_product(data, shown[0])
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "I don't have a couple of pieces on screen to compare "
                        "right now — tell me what you're after (e.g. gold rings "
                        "under 30k) and I'll line up some options 💍"
                    ),
                    "_compose": "compare_no_context",
                }
            ]
            return data

        followup = _handle_product_info_followup(data, query)
        if followup is not None:
            return followup

        if is_unrecognizable_input(query):
            user_profile["service_selected"] = SL.GENERAL.value
            data["classified_category"] = "general"
            return data

        # ── FIX 1: Price-only refinement fast-path ─────────────────────────
        # When user is in an active product_search session and sends ONLY a
        # price signal (e.g. "under 10k", "above 50k"), the intent is
        # unambiguous. Bypass classifier confidence — inherit prior
        # category/material and apply the new price.
        if _is_price_only_refinement(query, user_profile):
            price_entities = extract_entities(query)
            prior_raw = user_profile.get("last_search_filters") or {}
            prior_clean = {
                k: v
                for k, v in prior_raw.items()
                if k not in _NEVER_INHERIT_FIELDS and v is not None
            }
            # Build merged entities: prior category/material + new price.
            # Title stays None except seasonal rakhi (Clara has no rakhi category).
            search_entities = {
                **prior_clean,
                "title": prior_rakhi_title(prior_raw),
            }
            # collection is excluded from prior_clean by _NEVER_INHERIT_FIELDS
            # (a collection riding along on a category search is a narrow
            # modifier, same as karat/colour -- must not survive "under 20k"
            # the way test_collection_not_inherited_on_refinement locks in).
            # But when there's no prior category, collection WAS the search's
            # only anchor -- "show me something in evil eye" -> "under 20k"
            # must stay scoped to Evil Eye, matching merge_search_entities's
            # identical carve-out for the same shape.
            if not prior_raw.get("category") and prior_raw.get("collection"):
                search_entities["collection"] = prior_raw.get("collection")
            new_min = price_entities.get("min_price")
            new_max = price_entities.get("max_price")
            if new_min is not None:
                search_entities["min_price"] = new_min
                # Only clear prior max when no new max was given (avoids impossible range)
                if new_max is None:
                    search_entities["max_price"] = None
            if new_max is not None:
                search_entities["max_price"] = new_max
                # Only clear prior min when no new min was given (avoids impossible range)
                if new_min is None:
                    search_entities["min_price"] = None
            logger.debug(
                "product_search: price-only refinement fast-path",
                extra={
                    "query": query,
                    "inherited": {
                        k: prior_raw.get(k)
                        for k in ["category", "material_type"]
                    },
                    "price": {
                        k: search_entities.get(k)
                        for k in ["min_price", "max_price"]
                    },
                },
            )
            logger.info(
                "product_search: price-only refinement fast-path",
                extra={
                    "phone_number": phone_number,
                    "query": query,
                    "inherited": {
                        k: prior_raw.get(k)
                        for k in ["category", "material_type"]
                    },
                    "price": {
                        k: search_entities.get(k)
                        for k in ["min_price", "max_price"]
                    },
                },
            )
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            return await self._execute_search(
                data,
                phone_number,
                search_entities,
                query_label=query,
            )
        # ── end FIX 1 ──────────────────────────────────────────────────────

        if not _clara_configured():
            logger.warning(
                "Product search skipped — KISNA_CLARA_BASE_URL / CLARA_API_KEY not configured",
                extra={"phone_number": phone_number, "query": query},
            )
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        structured_fields = extract_structured_fields(query)
        llm_entities = dict(data.get("llm_extracted_entities") or {})
        llm_source = "classifier" if llm_entities else None

        is_text = "text" in messages
        if is_text and query.strip() and not _is_show_more_request(query, data):
            # CONTEXT-FREE extraction: the pass that determines search filters
            # sees ONLY the user's message — no history, no shown products. Any
            # context we pass gets copied under pressure ("stuck on diamond
            # rings" loop). Carry-over of prior filters is handled
            # deterministically by merge_search_entities below.
            #
            # The classifier already ran exactly this pass for this message, so
            # reuse it rather than paying for a second identical call. The stash
            # is keyed to the message: a miss (absent, malformed, or keyed to a
            # different message) falls through and extracts normally, because a
            # stale hit would reintroduce the context bleed we removed.
            from kisna_chatbot.processors.classifier import (
                read_context_free_entities,
            )

            extracted_llm = read_context_free_entities(data, query)
            if extracted_llm is None:
                extracted_llm = await extract_entities_with_llm(
                    user_query=query,
                    client_id=data.get("client_id", "kisna"),
                    phone_number=phone_number,
                )
            if extracted_llm:
                # SINGLE SOURCE OF TRUTH for search filters: when the
                # context-free pass runs, ALL semantic entities (category,
                # material, price, style, …) come from it alone. The classifier
                # saw history + shown products, so its entities can be
                # context-biased — we take ONLY product_reference from it (that
                # field legitimately needs the shown-products context; it's an
                # index, not a search filter). This makes context-bleed
                # structurally impossible for every filter, in every language.
                ref = (data.get("llm_extracted_entities") or {}).get(
                    "product_reference"
                )
                llm_entities = dict(extracted_llm)
                if ref is not None and llm_entities.get("product_reference") is None:
                    llm_entities["product_reference"] = ref
                if llm_source is None and extracted_llm:
                    llm_source = "entity_llm"
                elif llm_source == "classifier" and extracted_llm:
                    llm_source = "entity_llm+classifier"

            # Per-field evidence gate: LLM may not invent colour/karat/size or
            # material that the user did not write. Applies to classifier + entity LLM.
            before_gate = {
                "material_type": llm_entities.get("material_type"),
                "metal_colour": llm_entities.get("metal_colour"),
                "karat": llm_entities.get("karat"),
                "size": llm_entities.get("size"),
                "occasion": llm_entities.get("occasion"),
                "style": llm_entities.get("style"),
                "gender": llm_entities.get("gender"),
                "fulfillment": llm_entities.get("fulfillment"),
                "collection": llm_entities.get("collection"),
            }
            llm_entities = apply_llm_evidence_gate(query, llm_entities)
            if any(before_gate[k] != llm_entities.get(k) for k in before_gate):
                logger.debug(
                    "entity evidence-gate: stripped unevidenced LLM fields",
                    extra={
                        "query": query,
                        "before": before_gate,
                        "after": {k: llm_entities.get(k) for k in before_gate},
                    },
                )

            data["llm_extracted_entities"] = llm_entities
            user_profile["llm_extracted_entities"] = llm_entities

        extracted = combine_search_entities(llm_entities, structured_fields)

        # extract_structured_fields deliberately never provides collection
        # (architecture boundary, test_regex_never_provides_semantic_entities
        # -- semantic fields are LLM-only, since that's where homograph
        # ambiguity lives). But collection matching isn't a semantic guess:
        # _matched_collection_label is a deterministic lookup against the
        # live Clara collections list, the same kind of validated check as
        # pincode/city. Live-confirmed the LLM reliably catches distinctive
        # multi-word names ("Evil Eye") but consistently misses one-word
        # ones ("noor", "echo", "vachan") -- no collection, no title,
        # nothing downstream to recover from. LLM value still wins if set.
        if not extracted.get("collection"):
            from kisna_chatbot.processors.entity_extractor import (
                _matched_collection_label,
            )

            matched_collection = _matched_collection_label(query)
            if matched_collection:
                extracted["collection"] = matched_collection

        # "any" is the LLM saying the user refused an availability or has no
        # preference — that is the absence of a filter, not one to send.
        if extracted.get("fulfillment") == "any":
            extracted["fulfillment"] = None

        # Availability cues from NL ("ready to ship", "made to order")
        if not extracted.get("fulfillment"):
            inferred_fulfillment = extract_fulfillment(query)
            if inferred_fulfillment:
                extracted["fulfillment"] = inferred_fulfillment

        # NOTE: the LLM's category is authoritative. We do NOT override it with
        # a regex re-extraction of the query — that Latin regex breaks on
        # multilingual homographs (e.g. "Mala ek ring pahije" is Marathi for
        # "I want a ring"; regex reads "mala"→necklace and would wrongly force
        # necklace over the LLM's correct "ring"). Stale-category bleed is
        # already impossible because entity extraction is context-free.

        extracted, occasion_prefix = apply_occasion_style_hints(
            extracted, query=query
        )
        extracted = apply_rakhi_title_hint(extracted, query=query)

        # ── Relative price follow-up ("too costly", "thoda sasta", "aur mehnga",
        # any language) — LLM sets price_direction; we move the band ~30%.
        direction = extracted.pop("price_direction", None)
        if (
            direction in ("lower", "higher")
            and extracted.get("min_price") is None
            and extracted.get("max_price") is None
        ):
            rel_entities, bound = _entities_for_price_direction(
                user_profile, direction
            )
            if rel_entities is not None:
                # Anything the user just stated (e.g. new category) wins.
                for key in ("category", "material_type"):
                    if extracted.get(key):
                        rel_entities[key] = extracted[key]
                note = (
                    f"Got it! 👍 Showing options under ₹{bound:,}."
                    if direction == "lower"
                    else f"Sure — here are more premium picks above ₹{bound:,} ✨"
                )
                logger.info(
                    "product_search: relative price refinement",
                    extra={
                        "phone_number": phone_number,
                        "direction": direction,
                        "bound": bound,
                    },
                )
                return await self._execute_search(
                    data,
                    phone_number,
                    rel_entities,
                    query_label=f"price_{direction}",
                    occasion_prefix=note,
                )

        last_filters = user_profile.get("last_search_filters") or {}
        prior = {
            k: v
            for k, v in last_filters.items()
            if k not in _NEVER_INHERIT_FIELDS and v is not None  # FIX 4: exclude None values
        }
        # collection is excluded above by _NEVER_INHERIT_FIELDS (a narrow
        # modifier riding on a category search must not outlive a refinement
        # -- test_collection_not_inherited_on_refinement). But when the
        # prior search had no category at all, collection WAS the anchor
        # ("show me something in evil eye"); merge_search_entities has its
        # own matching logic for this shape, but only if it can actually see
        # the value -- restore it here so that logic isn't fed a dict this
        # same exclusion already stripped it from.
        if not last_filters.get("category") and last_filters.get("collection"):
            prior["collection"] = last_filters.get("collection")
        prior = prior or None
        entities = merge_search_entities(prior, extracted, query)
        entities = inherit_rakhi_title(entities, last_filters)
        entities = finalize_search_entities(
            entities,
            query=query,
            regex_entities=structured_fields,
            llm_entities=llm_entities,
        )
        if extracted.get("max_price") is not None or extracted.get("min_price") is not None:
            user_profile["user_stated_budget"] = {
                "min_price": extracted.get("min_price"),
                "max_price": extracted.get("max_price"),
            }
        logger.debug(
            "Search entity merge",
            extra={
                "query": query,
                "llm_source": llm_source,
                "llm_entities": llm_entities,
                "structured_fields": structured_fields,
                "merged": entities,
            },
        )
        logger.info(
            "Search entity merge",
            extra={
                "phone_number": phone_number,
                "query": query,
                "llm_source": llm_source,
                "prior_filters": prior,
                "llm_entities": llm_entities,
                "structured_fields": structured_fields,
                "extracted": extracted,
                "occasion": extracted.get("occasion"),
                "style": extracted.get("style"),
                "merged": entities,
                "api_params": entities_to_api_params(entities),
            },
        )

        if (
            _entities_all_none(entities)
            and not _BROWSE_ALL_RE.search(query)
            and data.get("classified_category") == "product_search"
        ):
            confidence = float(data.get("classifier_confidence") or 1.0)
            if confidence < 0.45 and not entities.get("category"):
                # Flag only. The wizard prompt below IS the clarification the
                # user sees — setting bot_response here was dead code, since
                # _maybe_start_shopping_wizard overwrites it unconditionally.
                user_profile["pending_vague_slot_fill"] = True
            return await self._maybe_start_shopping_wizard(
                data, phone_number, entities, query=query
            )

        # Fresh search with usable entities — clear vague / last-viewed bleed
        user_profile.pop("pending_vague_slot_fill", None)
        user_profile.pop("last_viewed_product", None)

        # Guided funnel: ask only missing slots (smart-skip)
        if (
            data.get("classified_category") == "product_search"
            and should_start_wizard(entities)
            and not _BROWSE_ALL_RE.search(query)
            and not _collection_browse_skips_wizard(entities)
        ):
            return await self._maybe_start_shopping_wizard(
                data, phone_number, entities, query=query
            )

        api_params_preview = entities_to_api_params(entities)
        if not has_clara_search_scope(
            api_params_preview, entities
        ) and not _BROWSE_ALL_RE.search(query):
            logger.warning(
                "Search blocked — missing category/title for Clara API",
                extra={
                    "phone_number": phone_number,
                    "query": query,
                    "entities": entities,
                    "api_params": api_params_preview,
                },
            )
            return await self._maybe_start_shopping_wizard(
                data, phone_number, entities, query=query
            )

        return await self._execute_search(
            data,
            phone_number,
            entities,
            query_label=query,
            occasion_prefix=occasion_prefix,
        )

    async def _maybe_start_shopping_wizard(
        self,
        data: dict,
        phone_number: str,
        entities: dict,
        *,
        query: str = "",
    ) -> dict:
        """Enter guided funnel; prepend welcome on brand-new sessions."""
        user_profile = data.get("user_profile", {})
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        prepend: list[dict] = []
        history = user_profile.get("chat_history") or []
        # First inbound product ask — lead with KIA intro then wizard question
        if len(history) == 0:
            prepend = build_greeting_welcome_bot_responses(
                phone_number=phone_number,
                chat_history=history,
                user_profile=user_profile,
            )
        # Slots the user already answered by tapping a button before escaping the
        # funnel this turn — apply underneath the new entities so the wizard does
        # not ask "Who is it for?" again (classifier._stash_wizard_carryover).
        # Drop material when switching category vs last completed search.
        carryover = filter_wizard_carryover(
            data.get("_wizard_carryover") or {},
            entities,
            user_profile.get("last_search_filters"),
            query=query,
        )
        if carryover:
            entities = {
                **entities,
                **{
                    k: v
                    for k, v in carryover.items()
                    if entities.get(k) is None
                },
            }
        responses = start_wizard(
            user_profile,
            entities=entities,
            prepend_welcome=prepend,
            query=query,
        )
        if user_profile.get("shopping_wizard_step") == "complete":
            return await self._complete_shopping_wizard(data, phone_number)
        data["bot_response"] = responses
        return data

    async def _handle_shopping_wizard(self, data: dict, phone_number: str) -> dict:
        """Advance or complete an active shopping wizard turn."""
        user_profile = data.get("user_profile", {})
        messages = data.get("messages", {})
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        # Drop leftover store wait so budget text never routes to AdFlow.
        user_profile.pop("awaiting_store_pincode", None)
        user_profile.pop("store_pincode_attempts", None)

        # Late start: interactive without active flag (e.g. stale session)
        if is_wizard_interactive(messages) and not is_wizard_active(user_profile):
            user_profile["shopping_wizard_active"] = True
            user_profile["shopping_wizard_data"] = user_profile.get(
                "shopping_wizard_data"
            ) or {}

        text = _extract_search_query(messages)
        # advance_wizard() wipes the collected slots on escape, so snapshot the
        # button-tapped answers first — "skip" / "koi bhi" used to throw away a
        # half-filled funnel and restart from "What are you looking for today?".
        pre_escape_slots = {
            key: value
            for key, value in (user_profile.get("shopping_wizard_data") or {}).items()
            if key in _WIZARD_CARRYOVER_KEYS
            and value is not None
            and value != ANY_SLOT
        }
        # Slot answers are read by the context-free entity extractor: it is the
        # only source that parses native script ("अंगूठी", "५० हज़ार") and,
        # unlike the classifier, it cannot bleed a slot in from the history the
        # funnel has already collected.
        status, responses = advance_wizard(
            user_profile,
            messages,
            text=text,
            llm_entities=await _current_message_entities(data, text),
        )

        if status == "escape":
            clear_wizard_state(user_profile)
            if pre_escape_slots:
                data["_wizard_carryover"] = {
                    **pre_escape_slots,
                    **(data.get("_wizard_carryover") or {}),
                }
            # Fall through to normal NL search with this message
            if text:
                data["classified_category"] = "product_search"
                # Re-enter process without wizard active — recursive call would
                # re-hit wizard gate; clear and run entity path inline via search.
                from kisna_chatbot.processors.entity_extractor import extract_entities

                ents = finalize_search_entities(extract_entities(text), query=text)
                carryover = filter_wizard_carryover(
                    data.get("_wizard_carryover") or {},
                    ents,
                    user_profile.get("last_search_filters"),
                    query=text,
                )
                for key, value in carryover.items():
                    if ents.get(key) is None:
                        ents[key] = value
                if should_start_wizard(ents):
                    return await self._maybe_start_shopping_wizard(
                        data, phone_number, ents, query=text
                    )
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                return await self._execute_search(
                    data, phone_number, ents, query_label=text
                )
            data["bot_response"] = [build_vague_slot_fill_response()]
            return data

        if status in ("prompt", "reask") and responses:
            data["bot_response"] = responses
            return data

        if status == "complete":
            return await self._complete_shopping_wizard(data, phone_number)

        data["bot_response"] = responses or [build_vague_slot_fill_response()]
        return data

    async def _handle_search_confirmation(
        self, data: dict, phone_number: str
    ) -> dict | None:
        """Resolve a pending recap. Returns None when the turn is not an answer."""
        user_profile = data.get("user_profile", {})
        pending = get_pending_search(user_profile)
        messages = data.get("messages", {})
        text = _extract_search_query(messages)
        answer = parse_confirm_reply(messages, text)

        if not pending:
            if is_confirm_interactive(messages) and answer in ("yes", "no"):
                data["bot_response"] = [
                    {
                        "type": "text",
                        "text": (
                            "That confirmation expired — tell me what you're "
                            "looking for (e.g. gold rings under 50k) and I'll "
                            "search again."
                        ),
                        "_compose": "search_confirm_expired",
                    }
                ]
                return data
            return None

        if answer == "yes":
            pop_pending_search(user_profile)
            entities = {**_empty_entities(), **(pending.get("entities") or {})}
            logger.info(
                "Search confirmation accepted",
                extra={
                    "phone_number": phone_number,
                    "query": pending.get("query_label"),
                },
            )
            return await self._execute_search(
                data,
                phone_number,
                entities,
                query_label=pending.get("query_label") or "confirmed",
                occasion_prefix=pending.get("occasion_prefix"),
                response_mode=pending.get("response_mode"),
                exclude_product_id=pending.get("exclude_product_id"),
                confirm=False,
            )

        if answer == "no":
            user_profile[AWAITING_CORRECTION_KEY] = True
            logger.info(
                "Search confirmation rejected",
                extra={
                    "phone_number": phone_number,
                    "query": pending.get("query_label"),
                },
            )
            data["bot_response"] = [build_correction_prompt()]
            return data

        if not is_awaiting_correction(user_profile):
            # A refinement of what we just read back is not a fresh request.
            # "show me something in evil eye" -> recap -> "under 20k" used to
            # land here and THROW THE RECAP AWAY (collection included), so the
            # user got "What are you looking for today?" and lost the whole
            # search. Narrowing the pending search keeps it.
            refined = _confirm_refinement_merge(pending, text)
            if refined is not None:
                clear_confirm_state(user_profile)
                user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
                logger.info(
                    "Search confirmation refined",
                    extra={
                        "phone_number": phone_number,
                        "query": pending.get("query_label"),
                    },
                )
                return await self._execute_search(
                    data,
                    phone_number,
                    {**_empty_entities(), **refined},
                    query_label=pending.get("query_label") or "refinement",
                    occasion_prefix=pending.get("occasion_prefix"),
                    response_mode=pending.get("response_mode"),
                    exclude_product_id=pending.get("exclude_product_id"),
                )
            # Genuinely something else. Drop the recap and let normal routing
            # handle the new message.
            clear_confirm_state(user_profile)
            return None

        if not text:
            return None

        # The correction is merged against what we just read back, so untouched
        # slots survive and the normal pipeline re-asks for confirmation.
        entities = dict(pending.get("entities") or {})
        llm_entities = await _current_message_entities(data, text)

        # The LLM reads the whole sentence in any script, so it is the primary
        # source: it answers "any" when the user refuses an availability
        # ("ready to ship nahi chahiye"). The regex is only the fallback for
        # when the extractor returned nothing.
        change = llm_entities.get("fulfillment")
        if change not in ("ready", "mto", "any"):
            change = extract_fulfillment_change(text)
        # A value equal to what we just read back is not a second correction,
        # so it does not send this turn to the search pipeline. The check is
        # cheap insurance: the extractor is context-free and should not echo
        # the recap, but the regex side still can.
        regex_entities = extract_entities(text)
        names_other_slot = any(
            (llm_entities.get(key) is not None and llm_entities.get(key) != entities.get(key))
            or (
                regex_entities.get(key) is not None
                and regex_entities.get(key) != entities.get(key)
            )
            for key in ("category", "material_type", "gender", "min_price", "max_price")
        )
        if change is not None and not names_other_slot:
            # An availability-only correction carries nothing for the search
            # pipeline to extract, so it used to restart the funnel: the
            # classifier echoes the category from history, which reads as a new
            # search and drops the budget. Apply it here and re-recap instead.
            entities["fulfillment"] = (
                None if change in ("any", "clear") else change
            )
            clear_confirm_state(user_profile)
            user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
            return await self._execute_search(
                data,
                phone_number,
                {**_empty_entities(), **entities},
                query_label=pending.get("query_label") or "correction",
                occasion_prefix=pending.get("occasion_prefix"),
                response_mode=pending.get("response_mode"),
                exclude_product_id=pending.get("exclude_product_id"),
            )

        user_profile["last_search_filters"] = entities
        clear_confirm_state(user_profile)
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        return None

    async def _complete_shopping_wizard(
        self, data: dict, phone_number: str
    ) -> dict:
        """Run Clara search from collected wizard slots."""
        user_profile = data.get("user_profile", {})
        collected = dict(user_profile.get("shopping_wizard_data") or {})
        explicit = dict(user_profile.get("shopping_wizard_explicit") or {})
        clear_wizard_state(user_profile)

        if not _clara_configured():
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        entities = {
            **_empty_entities(),
            **entities_from_wizard(collected, explicit),
        }
        # Wizard no longer asks occasion — skip bridal/title injection from empty occasion
        # entities (not collected) so karat/metal_colour/collection — set via
        # explicit, invisible to collected alone — reach this summary line
        # the same way they already reach the confirmation recap before it.
        summary = build_wizard_summary(entities)

        return await self._execute_search(
            data,
            phone_number,
            entities,
            query_label=(
                f"wizard:{collected.get('category')}:"
                f"{collected.get('material_type')}:"
                f"{collected.get('fulfillment')}"
            ),
            occasion_prefix=summary,
        )

    async def _handle_preference_list(
        self, data: dict, phone_number: str, postback: str
    ) -> dict:
        """Handle legacy pref$* list taps as conversational text prompts / searches."""
        user_profile = data.get("user_profile", {})
        user_profile["service_selected"] = SL.PRODUCT_SEARCH.value
        user_profile["last_search_at"] = int(time.time())
        postback = (postback or "").strip()

        if postback.startswith("pref$cat$"):
            if postback in ("pref$cat$other", "pref$cat$back"):
                data["bot_response"] = [build_vague_slot_fill_response()]
                return data
            if postback == "pref$cat$any":
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                _clear_preference_state(user_profile)
                return await self._execute_search(
                    data,
                    phone_number,
                    _empty_entities(),
                    query_label="browse_all",
                    response_mode="browse_all",
                )
            cat_key = postback.rsplit("$", 2)[-1]
            entities = _entities_from_pref_cat(cat_key)
            if entities is None:
                data["bot_response"] = [build_vague_slot_fill_response()]
                return data
            user_profile["pref_category"] = entities.get("category") or cat_key
            if entities.get("title"):
                user_profile["pref_title"] = entities.get("title")
            user_profile["preference_step"] = 2
            user_profile["awaiting_custom_budget"] = True
            data["bot_response"] = [build_budget_text_prompt()]
            return data

        if postback.startswith("pref$material$"):
            material = postback.rsplit("$", 1)[-1]
            user_profile["pref_material"] = material
            if user_profile.get("pref_category"):
                user_profile["preference_step"] = 2
                user_profile["awaiting_custom_budget"] = True
                data["bot_response"] = [build_budget_text_prompt()]
            else:
                data["bot_response"] = [build_vague_slot_fill_response()]
            return data

        if postback.startswith("pref$type$"):
            category = postback.rsplit("$", 1)[-1]
            user_profile["pref_type"] = category
            user_profile["pref_category"] = user_profile.get("pref_category") or category
            user_profile["preference_step"] = 3
            user_profile["awaiting_custom_budget"] = True
            data["bot_response"] = [build_budget_text_prompt()]
            return data

        if postback == "pref$budget$custom":
            user_profile["awaiting_custom_budget"] = True
            data["bot_response"] = [build_budget_text_prompt()]
            return data

        budget_match = _BUDGET_POSTBACK_RE.match(postback)
        if budget_match:
            if not _clara_configured():
                data["bot_response"] = _build_catalog_not_configured_response()
                return data
            min_p = int(budget_match.group(1))
            max_p = int(budget_match.group(2))
            entities = _entities_from_preferences(user_profile)
            entities["min_price"] = min_p
            entities["max_price"] = max_p
            _clear_preference_state(user_profile)
            return await self._execute_search(
                data,
                phone_number,
                entities,
                query_label=f"pref:{entities.get('material_type')}:{entities.get('category')}",
            )

        data["bot_response"] = [build_vague_slot_fill_response()]
        return data

    async def _handle_custom_budget_input(
        self, data: dict, phone_number: str, query: str
    ) -> dict:
        """Parse a free-text budget reply.  Context-isolated: only pref_category
        and pref_material flow through — never prior search title/collection/etc."""
        user_profile = data.get("user_profile", {})
        min_p, max_p = _parse_custom_budget_text(query)
        if min_p is None and max_p is None:
            # Track consecutive failures; bail out after _MAX_CUSTOM_BUDGET_ATTEMPTS
            attempts = user_profile.get("custom_budget_attempts", 0) + 1
            user_profile["custom_budget_attempts"] = attempts
            if attempts >= _MAX_CUSTOM_BUDGET_ATTEMPTS:
                # Give up on the budget loop — clear flags and fall back to open browse
                user_profile["awaiting_custom_budget"] = False
                user_profile["custom_budget_attempts"] = 0
                _clear_preference_state(user_profile)
                data["bot_response"] = [
                    {
                        "type": "text",
                        "text": (
                            "No worries! Let me show you some jewellery you might love."
                        ),
                    }
                ]
                if not _clara_configured():
                    data["bot_response"] = _build_catalog_not_configured_response()
                    return data
                return await self._execute_search(
                    data, phone_number, _empty_entities(), query_label="budget_fallback"
                )
            # Single localized re-ask — no English parse-error prefix.
            data["bot_response"] = [build_custom_budget_prompt()]
            return data

        if not _clara_configured():
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        # Gap 10: Guard — no category selected (budget arrived out of sequence)
        if not user_profile.get("pref_category"):
            _clear_preference_state(user_profile)
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": "What type of jewellery are you looking for? 💎",
                    "_compose": "slot_fill",
                },
                build_vague_slot_fill_response(),
            ]
            return data

        # Context-isolated entity build — only pref_category + pref_material,
        # never inherit title/collection/karat/etc from a prior search session.
        search_entities = {
            "category": user_profile.get("pref_category"),
            "material_type": user_profile.get("pref_material"),
            "min_price": min_p,
            "max_price": max_p,
            # All remaining fields explicitly None — never inherit from prior filter
            "title": None,
            "collection": None,
            "size": None,
            "karat": None,
            "metal_colour": None,
            "occasion": None,
            "style": None,
            "gender": None,
            "city": None,
            "pincode": None,
        }
        user_profile["awaiting_custom_budget"] = False
        user_profile["custom_budget_attempts"] = 0
        _clear_preference_state(user_profile)
        return await self._execute_search(
            data,
            phone_number,
            search_entities,
            query_label=f"custom_budget:{query}",
        )

    async def _handle_budget_flow_reply(
        self, data: dict, phone_number: str, budget_text: str
    ) -> dict:
        """Handle a WhatsApp Flow nfm_reply carrying budget_input from the user.
        Context-isolated: only pref_category + pref_material pass through."""
        user_profile = data.get("user_profile", {})
        # Flow closes itself — clear the flag regardless of parse outcome.
        user_profile["awaiting_custom_budget"] = False
        user_profile["custom_budget_attempts"] = 0

        min_p, max_p = _parse_custom_budget_text(budget_text)
        if min_p is None and max_p is None:
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "I couldn't understand that budget. Please try again, e.g. "
                        "'50000' (around ₹50,000), '15000-35000', or '50000 tak'."
                    ),
                },
                build_custom_budget_prompt(),
            ]
            return data

        if not _clara_configured():
            data["bot_response"] = _build_catalog_not_configured_response()
            return data

        # Gap 10: Guard — no category selected (budget flow arrived out of sequence)
        if not user_profile.get("pref_category"):
            _clear_preference_state(user_profile)
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": "What type of jewellery are you looking for? 💎",
                    "_compose": "slot_fill",
                },
                build_vague_slot_fill_response(),
            ]
            return data

        # Context-isolated entity build (same as text path)
        search_entities = {
            "category": user_profile.get("pref_category"),
            "material_type": user_profile.get("pref_material"),
            "min_price": min_p,
            "max_price": max_p,
            "title": None,
            "collection": None,
            "size": None,
            "karat": None,
            "metal_colour": None,
            "occasion": None,
            "style": None,
            "gender": None,
            "city": None,
            "pincode": None,
        }
        _clear_preference_state(user_profile)
        return await self._execute_search(
            data,
            phone_number,
            search_entities,
            query_label=f"custom_budget:{budget_text}",
        )

    async def _handle_show_more(self, data: dict, phone_number: str) -> dict:
        user_profile = data.get("user_profile", {})
        filters = user_profile.get("last_search_filters")
        last_page = user_profile.get("last_search_page", 1)
        total = user_profile.get("last_search_total", 0)
        filter_ratio = user_profile.get("last_search_filter_ratio", 1.0)
        api_total = user_profile.get("last_search_api_total", total)
        shown_ids = user_profile.get("shown_product_ids") or []

        if filters is None or filters == {}:
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": _SESSION_EXPIRED_TEXT,
                    "_compose": "session_expired",
                }
            ]
            return data
        filters = filters or _empty_entities()

        # UI cursor: serve the next PAGE_SIZE items from the leftover of the last
        # API fetch before making another API call. This decouples the WhatsApp
        # display page (PAGE_SIZE=3) from the Clara API page (up to 15) so items
        # already fetched but not yet shown are never skipped.
        buffer = _filter_unshown_products(
            user_profile.get("last_search_buffer") or [], shown_ids
        )
        if buffer:
            products_to_show = buffer[:PAGE_SIZE]
            user_profile["last_search_buffer"] = buffer[PAGE_SIZE:]
            user_profile["last_search_products"] = products_to_show
            user_profile["last_search_at"] = int(time.time())
            _append_shown_product_ids(user_profile, products_to_show)

            data["bot_response"] = _build_search_success_response(
                products_to_show,
                total,
                last_page,
                filters,
                carousel_pool=buffer,
                show_more_intro=False,
            )
            logger.info(
                "Show More results sent from buffer",
                extra={
                    "phone_number": phone_number,
                    "page": last_page,
                    "returned": len(products_to_show),
                    "buffer_remaining": len(user_profile["last_search_buffer"]),
                    "total": total,
                },
            )
            return data

        api_page_size = resolve_api_page_size(filters)

        # When client filters are active, judge exhaustion by API pages so we don't
        # falsely stop when post-filter total is smaller than display page size.
        if filter_ratio < 1.0:
            exhausted = (last_page * api_page_size) >= api_total
        else:
            exhausted = (last_page * PAGE_SIZE) >= total

        if exhausted:
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": _all_results_seen_text(total),
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

        max_attempts = _compute_show_more_retries(filter_ratio, api_page_size)
        for attempt in range(max_attempts):
            if attempt > 0:
                if filter_ratio < 1.0:
                    if (next_page - 1) * api_page_size >= api_total:
                        break
                elif (next_page - 1) * PAGE_SIZE >= total:
                    break

            try:
                result = await search_products(
                    **api_params,
                    page_no=next_page,
                    page_size=api_page_size,
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

            if filter_ratio < 1.0:
                if next_page * api_page_size >= api_total:
                    break
            elif next_page * PAGE_SIZE >= total:
                break
            next_page += 1

        if not products:
            if has_budget_filter:
                data["bot_response"] = [
                    {
                        "type": "text",
                        "text": _no_more_in_budget_text(),
                        "_compose": "no_more_results",
                    }
                ]
            else:
                data["bot_response"] = [
                    {
                        "type": "text",
                        "text": _no_more_new_text(),
                        "_compose": "no_more_results",
                    }
                ]
            return data

        user_profile["last_search_page"] = next_page
        user_profile["last_search_products"] = products[:PAGE_SIZE]
        user_profile["last_search_buffer"] = products[PAGE_SIZE:]
        user_profile["last_search_at"] = int(time.time())  # FIX 3: refresh session on Show More
        _append_shown_product_ids(user_profile, products[:PAGE_SIZE])

        entities = filters
        data["bot_response"] = _build_search_success_response(
            products[:PAGE_SIZE],
            total,
            next_page,
            entities,
            carousel_pool=products,
            show_more_intro=False,
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

    async def _handle_filter_fix(
        self, data: dict, phone_number: str, entity_key: str, title: str
    ) -> dict:
        """Handle a filter$fix$<entity_key> tap from build_impossible_value_prompt.

        Bug 4: this postback previously had no handler at all — tapping any
        of the "here's what we do have" buttons fell through to generic
        fallback text and left service_selected empty. Apply the corrected
        value and re-run the search immediately, same as a normal search.
        """
        user_profile = data.get("user_profile", {})
        pending = pop_pending_filter_fix(user_profile)
        if pending is None:
            # Stale tap (session/state lost since the validation message was
            # sent) — ask the user to just say what they want, same wording
            # as a lost search-recap correction.
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": "That option isn't active anymore — what are you looking for?",
                    "_compose": "filter_fix_stale",
                }
            ]
            return data

        entities = dict(pending.get("entities") or {})
        resolved = resolve_filter_fix_value(entity_key, title)
        if not resolved:
            logger.warning(
                "filter$fix$ tap resolved to no value",
                extra={"entity_key": entity_key, "title": title},
            )
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": "Sorry, I couldn't apply that — what are you looking for?",
                    "_compose": "filter_fix_unresolved",
                }
            ]
            return data

        entities[entity_key] = resolved
        logger.info(
            "filter$fix$ tap applied",
            extra={
                "phone_number": phone_number,
                "entity_key": entity_key,
                "title": title,
                "resolved_value": resolved,
            },
        )
        return await self._execute_search(
            data,
            phone_number,
            entities,
            query_label=f"filter_fix_{entity_key}",
            confirm=False,
        )

    async def _execute_search(
        self,
        data: dict,
        phone_number: str,
        entities: dict,
        *,
        query_label: str,
        exclude_product_id: str | None = None,
        occasion_prefix: str | None = None,
        response_mode: str | None = None,
        confirm: bool = True,
    ) -> dict:
        user_profile = data.get("user_profile", {})
        entities = finalize_search_entities(entities)

        # Phase 5: block impossible karat/colour/collection/gender when filters warm.
        from kisna_chatbot.processors.filter_validation import (
            build_impossible_value_prompt,
        )

        impossible = build_impossible_value_prompt(entities, user_profile)
        if impossible:
            data["bot_response"] = impossible
            return data

        # Read the filters back before spending them on an API call — an
        # inherited material/gender/budget is only wrong if the user can't see it.
        if confirm and is_confirm_enabled() and should_confirm(entities):
            set_pending_search(
                user_profile,
                entities,
                query_label=query_label,
                occasion_prefix=occasion_prefix,
                response_mode=response_mode,
                exclude_product_id=exclude_product_id,
            )
            recap = build_search_recap(entities)
            try:
                from kisna_chatbot.utils.message_trace import trace_step

                trace_step(data, "Confirmation asked", recap)
            except Exception:
                pass
            logger.info(
                "Search confirmation asked",
                extra={
                    "phone_number": phone_number,
                    "query": query_label,
                    "recap": recap,
                },
            )
            data["bot_response"] = [build_confirm_prompt(entities)]
            return data

        last_filters = user_profile.get("last_search_filters") or {}
        if not _entities_equal(entities, last_filters):
            user_profile["shown_product_ids"] = []

        try:
            from kisna_chatbot.utils.message_trace import (
                summarize_filters,
                trace_step,
            )

            trace_step(data, "Filters detected", summarize_filters(entities))
        except Exception:
            summarize_filters = None  # type: ignore
            trace_step = None  # type: ignore

        strategies = _build_fallback_strategies(entities)
        products: list[dict] = []
        raw_products: list[dict] = []
        total_count = 0
        page = 1
        winning_entities = entities
        prefix_parts: list[str] = []
        if occasion_prefix:
            prefix_parts.append(occasion_prefix)
        if response_mode == "browse_all":
            prefix_parts.insert(0, "Here's a look at our latest collection 💎")
        if entities.get("unsupported_category"):
            prefix_parts.append(_UNSUPPORTED_CATEGORY_NOTE)
        if entities.get("unsupported_material"):
            # Honest pivot: we don't carry silver/platinum/pearl. Say so, then
            # show gold/diamond/gemstone. Placed first so it reads before results.
            prefix_parts.insert(0, _UNSUPPORTED_MATERIAL_NOTE)
        intro_relaxed = False
        _filter_ratio = 1.0

        for strategy_entities, note_kind, log_label in strategies:
            api_params = entities_to_api_params(strategy_entities)
            api_page_size = resolve_api_page_size(strategy_entities)
            query_params = None
            try:
                from kisna_chatbot.utils.message_trace import (
                    build_clara_query_params,
                    fallback_drop_label,
                    summarize_api_call,
                )

                query_params = build_clara_query_params(
                    api_params, page_no=1, page_size=api_page_size
                )
            except Exception:
                build_clara_query_params = None  # type: ignore
                fallback_drop_label = None  # type: ignore
                summarize_api_call = None  # type: ignore

            logger.info(
                "Product search",
                extra={
                    "phone_number": phone_number,
                    "query": query_label,
                    "strategy": log_label,
                    "entities": strategy_entities,
                    "api_params": api_params,
                    "page_size": api_page_size,
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
                if trace_step and fallback_drop_label and summarize_api_call:
                    trace_step(
                        data,
                        "Search fallback",
                        f"No results with prior filters — retrying without "
                        f"{fallback_drop_label(log_label)}",
                        status="warn",
                    )

            has_price_filter = (
                strategy_entities.get("min_price") is not None
                or strategy_entities.get("max_price") is not None
            )

            try:
                clara_norm = normalize_entities_for_clara(strategy_entities)
                multi_cats = clara_norm.get("clara_multi_categories")
                if log_label == "full" and has_price_filter and multi_cats:
                    (
                        products,
                        api_total,
                        page,
                        raw_products,
                    ) = await _fetch_multi_category_products(
                        api_params,
                        multi_cats,
                        strategy_entities,
                        page_size=api_page_size,
                    )
                    result = {
                        "products": products,
                        "total_count": api_total,
                        "page": page,
                    }
                    if not products:
                        logger.warning(
                            "api_price_filter_mismatch",
                            extra={
                                "phone_number": phone_number,
                                "pages_scanned": len(multi_cats),
                                "entities": strategy_entities,
                                "api_total": api_total,
                                "raw_returned": len(raw_products),
                            },
                        )
                        if trace_step and summarize_api_call:
                            trace_step(
                                data,
                                "API call",
                                summarize_api_call(
                                    query_params=query_params,
                                    total_count=api_total,
                                    matched_count=0,
                                    products=raw_products,
                                ),
                                status="warn",
                            )
                        continue
                elif log_label == "full" and has_price_filter:
                    (
                        products,
                        api_total,
                        page,
                        raw_products,
                    ) = await _fetch_budget_filtered_products(
                        api_params,
                        strategy_entities,
                        page_size=api_page_size,
                    )
                    result = {
                        "products": products,
                        "total_count": api_total,
                        "page": page,
                    }
                    if not products:
                        logger.warning(
                            "api_price_filter_mismatch",
                            extra={
                                "phone_number": phone_number,
                                "pages_scanned": _BUDGET_SCAN_MAX_PAGES,
                                "entities": strategy_entities,
                                "api_total": api_total,
                                "raw_returned": len(raw_products),
                            },
                        )
                        if trace_step and summarize_api_call:
                            trace_step(
                                data,
                                "API call",
                                summarize_api_call(
                                    query_params=query_params,
                                    total_count=api_total,
                                    matched_count=0,
                                    products=raw_products,
                                ),
                                status="warn",
                            )
                        continue
                else:
                    if multi_cats:
                        (
                            products,
                            api_total,
                            page,
                            raw_products,
                        ) = await _fetch_multi_category_products(
                            api_params,
                            multi_cats,
                            strategy_entities,
                            page_size=api_page_size,
                        )
                        result = {
                            "products": products,
                            "total_count": api_total,
                            "page": page,
                        }
                    else:
                        result = await search_products(
                            **api_params, page_no=1, page_size=api_page_size
                        )
                        raw_products = result.get("products") or []
                        products = filter_products_by_entities(
                            raw_products, strategy_entities
                        )
                        if (
                            not products
                            and raw_products
                            and strategy_entities.get("title")
                        ):
                            relaxed_entities = {**strategy_entities, "title": None}
                            products = filter_products_by_entities(
                                raw_products, relaxed_entities
                            )
                            if products:
                                strategy_entities = relaxed_entities
                                if trace_step:
                                    trace_step(
                                        data,
                                        "Client filter relaxed",
                                        f"Dropped title match — kept {len(products)} of "
                                        f"{len(raw_products)} from this page",
                                        status="warn",
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

            try:
                if trace_step and summarize_api_call:
                    api_total_for_trace = int(
                        (result or {}).get("total_count")
                        or len(raw_products or [])
                        or 0
                    )
                    matched_for_trace = len(products or [])
                    # Only annotate when Clara returned hits but client filters
                    # kept none (e.g. category=ring page full of earrings).
                    # Do NOT compare page keepers to totalCount — that reads as
                    # "13 of 249 matched" when we only fetched pageSize=15.
                    matched_arg = (
                        0
                        if matched_for_trace == 0 and api_total_for_trace > 0
                        else None
                    )
                    status = "warn" if matched_for_trace == 0 else "ok"
                    # Prefer matched products for samples; if none matched, show
                    # raw Clara hits so the panel explains the mismatch.
                    top_products = products or raw_products or []
                    detail = summarize_api_call(
                        query_params=query_params,
                        total_count=api_total_for_trace,
                        matched_count=matched_arg,
                        products=top_products,
                    )
                    if log_label == "full":
                        trace_step(data, "API call", detail, status=status)
                    else:
                        dropped = (
                            fallback_drop_label(log_label)
                            if fallback_drop_label
                            else log_label
                        )
                        trace_step(
                            data,
                            "Closest-match search",
                            f"Without {dropped} — {detail}",
                            status="warn" if matched_for_trace == 0 else "ok",
                        )
                        data["_trace_outcome"] = (
                            "fallback_used"
                            if matched_for_trace > 0
                            else "no_products"
                        )
                    if log_label == "full" and matched_for_trace == 0:
                        data["_trace_outcome"] = "no_products"
            except Exception:
                pass

            if products:
                api_total = result.get("total_count", 0)
                products, extras_note = filter_products_by_extracted_extras(
                    products, entities_for_client_filter(strategy_entities)
                )
                fulfillment = (
                    strategy_entities.get("fulfillment")
                    or entities.get("fulfillment")
                )
                # Availability is handled by Clara boolean params
                # (readyTOShip / madeToOrder). Do not post-filter by EDD —
                # MTO is the full catalog by design.
                fulfill_note = None
                if fulfillment == "mto":
                    fulfill_note = (
                        "Any of these can be made to order for you ✨"
                    )
                if fulfill_note:
                    prefix_parts.append(fulfill_note)
                if extras_note:
                    intro_relaxed = True
                    if trace_step:
                        trace_step(
                            data,
                            "Extras filter relaxed",
                            extras_note,
                            status="warn",
                        )
                _actually_filtered = len(products) < len(raw_products)
                if extras_note or _actually_filtered:
                    total_count = len(products)
                    _api_fetch_count = len(raw_products)
                    _filter_ratio = (
                        len(products) / _api_fetch_count
                        if _api_fetch_count > 0
                        else 0.0
                    )
                else:
                    total_count = api_total
                    _filter_ratio = 1.0
                page = result.get("page", 1)
                winning_entities = strategy_entities
                fallback_note = _fallback_prefix_note(
                    note_kind, products, entities, strategy_entities
                )
                if fallback_note:
                    # Drop optimistic wizard/search copy that still claims the
                    # exact filters we had to relax (e.g. "ready-to-ship gold…").
                    if occasion_prefix and occasion_prefix in prefix_parts:
                        prefix_parts.remove(occasion_prefix)
                    prefix_parts.append(fallback_note)
                    intro_relaxed = True
                break

        prefix_note = "\n".join(prefix_parts) if prefix_parts else None

        if not products:
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": format_zero_results_message(entities),
                    "_compose": "zero_results",
                }
            ]
            data.setdefault("_trace_outcome", "no_products")
            return data

        if exclude_product_id:
            filtered = [
                p for p in products if _product_id(p) != str(exclude_product_id)
            ]
            if filtered:
                products = filtered
            elif total_count > 1:
                total_count = max(len(products), total_count - 1)

        carousel_pool = _sort_products_by_price_target(products, winning_entities)
        products_to_show = carousel_pool[:PAGE_SIZE]
        search_context = build_search_context(winning_entities)

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
        user_profile["last_search_filter_ratio"] = _filter_ratio
        user_profile["last_search_api_total"] = api_total
        user_profile["last_search_products"] = products_to_show
        user_profile["last_search_buffer"] = carousel_pool[PAGE_SIZE:]
        user_profile["last_search_at"] = int(time.time())
        _append_shown_product_ids(user_profile, products_to_show)
        
        # Only mark a product as "viewed" when the search narrowed to a SINGLE
        # piece — then "iska price"/"size" unambiguously refers to it. For a
        # multi-result list the user hasn't picked one, so clear last_viewed and
        # let a follow-up recap the shown pieces and ask which (never silently
        # answer about an arbitrary first result).
        if len(products_to_show) == 1:
            from kisna_chatbot.processors.product_details_agent import _save_last_viewed_product
            _save_last_viewed_product(user_profile, products_to_show[0])
        else:
            user_profile.pop("last_viewed_product", None)

        data["bot_response"] = _build_search_success_response(
            products_to_show,
            total_count,
            page,
            winning_entities,
            carousel_pool=carousel_pool,
            prefix_note=prefix_note,
            intro_relaxed=intro_relaxed,
        )
        if any(
            (s.get("label") == "Closest-match search")
            for s in (data.get("_trace_steps") or [])
        ):
            data["_trace_outcome"] = "fallback_used"
        else:
            data["_trace_outcome"] = "products_sent"

        has_product_images = any(
            r.get("type") == "image_with_cta" for r in data["bot_response"]
        )
        if products_to_show and not has_product_images:
            missing = []
            for product in products_to_show:
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
                    1 for r in data["bot_response"] if r.get("type") == "image_with_cta"
                ),
            },
        )
        return data
