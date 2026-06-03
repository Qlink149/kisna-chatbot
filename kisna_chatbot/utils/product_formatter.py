"""
Format Clara API product objects for WhatsApp messages.
"""

import re
from typing import Any, Optional

from kisna_chatbot.integrations.clara_api import get_discount_for_product
from kisna_chatbot.processors.entity_extractor import build_search_context

_PRODUCT_LIST_MSGID = "product_select$results"
_KARAT_RE = re.compile(
    r"(\d{1,2})\s*(?:kt|karat|carat|k\b)",
    re.I,
)


def _truncate(text: str, max_len: int, ellipsis: str = "…") -> str:
    if len(text) <= max_len:
        return text
    if max_len <= len(ellipsis):
        return text[:max_len]
    return text[: max_len - len(ellipsis)] + ellipsis


def _extract_karat(variant_title: str) -> str:
    if not variant_title:
        return ""
    m = _KARAT_RE.search(variant_title)
    if m:
        return f"{m.group(1)}KT"
    return variant_title.strip()[:20]


def _material_label(product: dict) -> str:
    material = product.get("materialType") or product.get("material") or ""
    if isinstance(material, list):
        return " + ".join(m.title() for m in material if m) or "Jewellery"
    if isinstance(material, dict):
        material = material.get("name") or material.get("title") or ""
    return str(material).strip() or "Jewellery"


def build_product_url(product: dict) -> str:
    """Build canonical KISNA product page URL from API seo slug."""
    base = "https://www.kisna.com"
    slug = (product.get("seos") or {}).get("slug", "")
    if slug.startswith("products_"):
        path = "products/" + slug[len("products_") :]
    elif slug:
        path = slug.replace("_", "/", 1)
    else:
        return base
    return f"{base}/{path}"


def _product_caption_lines(product: dict) -> list[str]:
    """Shared caption body for product image messages."""
    title = product.get("title") or "Product"
    price_block = product.get("price") or {}
    variant_price = price_block.get("variantPrice", 0)
    try:
        price_int = int(float(variant_price))
    except (TypeError, ValueError):
        price_int = 0

    variant = product.get("variant") or {}
    variant_title = variant.get("title") or ""
    material = _material_label(product)
    karat = _extract_karat(variant_title)
    material_line = f"{material} · {karat}" if karat else material

    shipping = product.get("shipping") or {}
    edd = shipping.get("edd", "?")

    lines = [
        f"*{title}*",
        f"₹{price_int:,}",
        material_line,
        f"🚚 Delivery in {edd} days",
    ]

    if product.get("withChain") == "noChain":
        lines.append("⚠️ Chain not included")

    discount = get_discount_for_product(product)
    if discount:
        lines.append(f"🏷 {discount.replace(' %', '%')}")

    return lines


def format_product_buy_caption(product: dict) -> str:
    """Image caption for product detail / Buy Now (no URL — CTA carries link)."""
    return "\n".join(_product_caption_lines(product))


def _normalize_image_url(url: Any) -> Optional[str]:
    """Return a usable HTTPS image URL, or None."""
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("http://"):
        text = "https://" + text[len("http://") :]
    if not text.startswith("https://"):
        return None
    return text


def _url_from_media_item(item: dict) -> Optional[str]:
    """Extract image URL from a single mediaUrl[] entry (Clara uses ``image``)."""
    media_type = item.get("type")
    if media_type is not None and str(media_type).lower() != "image":
        return None
    raw = item.get("image") or item.get("url") or item.get("mediaUrl")
    return _normalize_image_url(raw)


def _url_from_media_list(media: list) -> Optional[str]:
    """Prefer isDefault image entry, else first valid image in the list."""
    default_url: Optional[str] = None
    fallback_url: Optional[str] = None

    for item in media:
        if isinstance(item, str):
            normalized = _normalize_image_url(item)
            if normalized and fallback_url is None:
                fallback_url = normalized
            continue
        if not isinstance(item, dict):
            continue
        url = _url_from_media_item(item)
        if not url:
            continue
        if item.get("isDefault"):
            default_url = url
        elif fallback_url is None:
            fallback_url = url

    return default_url or fallback_url


def get_product_image_url(product: dict) -> Optional[str]:
    """Return primary product image URL from Clara ``mediaUrl[].image`` or fallbacks."""
    media = product.get("mediaUrl") or product.get("media")
    if isinstance(media, list) and media:
        url = _url_from_media_list(media)
        if url:
            return url

    if isinstance(media, str):
        url = _normalize_image_url(media)
        if url:
            return url

    for key in ("image", "image_url", "thumbnail"):
        url = _normalize_image_url(product.get(key))
        if url:
            return url

    images = product.get("images")
    if isinstance(images, list):
        url = _url_from_media_list(images)
        if url:
            return url

    variant = product.get("variant")
    if isinstance(variant, dict):
        variant_media = variant.get("mediaUrl") or variant.get("media")
        if isinstance(variant_media, list):
            url = _url_from_media_list(variant_media)
            if url:
                return url
        url = _normalize_image_url(variant.get("image"))
        if url:
            return url

    return None


def format_product_image_caption(product: dict) -> str:
    """WhatsApp image caption for search carousel (includes product link)."""
    lines = _product_caption_lines(product)
    lines.extend(["", f"🔗 {build_product_url(product)}"])
    return "\n".join(lines)


def format_product_list_row(product: dict) -> dict:
    """Single row for WhatsApp interactive list."""
    title = _truncate(product.get("title") or "Product", 24)
    price_block = product.get("price") or {}
    try:
        price_int = int(float(price_block.get("variantPrice", 0)))
    except (TypeError, ValueError):
        price_int = 0
    material = _material_label(product)
    shipping = product.get("shipping") or {}
    edd = shipping.get("edd", "?")
    description = _truncate(f"₹{price_int:,} · {material} · {edd}d delivery", 72)
    return {
        "title": title,
        "description": description,
        "id": str(product.get("_id") or product.get("id") or ""),
    }


def format_product_list_message(
    products: list[dict],
    total_count: int,
    page: int,
    search_context: str = "",
    page_size: int = 5,
) -> dict:
    """WhatsApp interactive list message dict."""
    header = f"💎 {search_context}" if search_context else "💎 KISNA Jewellery"
    start = (page - 1) * page_size + 1 if total_count else 0
    end = min(page * page_size, total_count)
    body = (
        f"Found *{total_count}* piece{'s' if total_count != 1 else ''}.\n"
        f"Showing {start}–{end}. Tap to view details."
    )

    options = []
    for product in products[:10]:
        row = format_product_list_row(product)
        if not row["id"]:
            continue
        options.append(
            {
                "type": "text",
                "title": row["title"],
                "description": row["description"],
                "postbackText": row["id"],
            }
        )

    return {
        "type": "list",
        "list": "list",
        "title": header[:60],
        "body": body,
        "footer": "KISNA Diamond & Gold",
        "msgid": _PRODUCT_LIST_MSGID,
        "globalButtons": [{"type": "text", "title": "Browse Products"}],
        "items": [{"title": "Results", "subtitle": "", "options": options}],
    }


def format_zero_results_message(entities: dict[str, Any]) -> str:
    """Helpful zero-results message; never invents products."""
    context = build_search_context(entities)
    lines = [
        f"We couldn't find *{context}* in our catalogue right now.",
        "",
    ]

    suggestions = []
    if entities.get("max_price") is not None or entities.get("min_price") is not None:
        suggestions.append("Try a wider price range")
    if entities.get("material_type"):
        suggestions.append("Try a different material (gold, diamond, gemstone)")
    if entities.get("category"):
        suggestions.append("Try a different jewellery type (ring, necklace, earring)")

    if suggestions:
        lines.append("Suggestions:")
        for s in suggestions[:3]:
            lines.append(f"• {s}")
        lines.append("")

    lines.append("Browse full collection: https://kisna.com")
    return "\n".join(lines)
