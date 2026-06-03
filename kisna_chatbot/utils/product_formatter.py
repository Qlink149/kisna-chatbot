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


def get_product_image_url(product: dict) -> Optional[str]:
    """Return default mediaUrl or first image URL."""
    media = product.get("mediaUrl") or product.get("media") or []
    if not isinstance(media, list):
        return None

    for item in media:
        if isinstance(item, dict) and item.get("isDefault"):
            url = item.get("url") or item.get("mediaUrl")
            if url:
                return str(url)

    for item in media:
        if isinstance(item, dict):
            url = item.get("url") or item.get("mediaUrl")
            if url:
                return str(url)
    return None


def format_product_image_caption(product: dict) -> str:
    """WhatsApp image caption for a single product."""
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
        lines.append(f"🏷 {discount}")

    seos = product.get("seos") or {}
    slug = seos.get("slug") or ""
    lines.append("")
    if slug:
        lines.append(f"🔗 https://kisna.com/{slug}")
    else:
        lines.append("🔗 https://kisna.com")

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
