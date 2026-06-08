"""
Format Clara API product objects for WhatsApp messages.

Prices and MRP come only from Clara API fields via utils.price_calculator.
Promo labels use embedded promotions[]; no estimated or computed rupee amounts.
"""

import os
import re
from typing import Any, Optional

from kisna_chatbot.processors.entity_extractor import build_search_context
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.price_calculator import resolve_product_prices

_PRODUCT_LIST_MSGID = "product_select$results"
BROWSE_PRODUCTS_GLOBAL_TITLE = "Browse Products"
_KARAT_RE = re.compile(
    r"(\d{1,2})\s*(?:kt|karat|carat|k\b)",
    re.I,
)
_SIZE_RE = re.compile(r"\b(?:size\s*)?(\d{1,2}(?:\.\d)?)\b")
_COLOR_WORDS = ("yellow", "white", "rose", "pink", "silver")


def _truncate(text: str, max_len: int, ellipsis: str = "…") -> str:
    if len(text) <= max_len:
        return text
    if max_len <= len(ellipsis):
        return text[:max_len]
    return text[: max_len - len(ellipsis)] + ellipsis


def _int_price(val: Any) -> int | None:
    if val is None:
        return None
    try:
        parsed = int(float(val))
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _parse_variant_attributes(variant_title: str) -> dict[str, str]:
    """Parse karat, metal color, and ring size from Clara variant.title."""
    attrs: dict[str, str] = {}
    if not variant_title:
        return attrs

    m = _KARAT_RE.search(variant_title)
    if m:
        attrs["karat"] = f"{m.group(1)}KT"

    lower = variant_title.lower()
    for color in _COLOR_WORDS:
        if color in lower:
            attrs["color"] = color.title()
            break

    size_m = _SIZE_RE.search(variant_title)
    if size_m:
        attrs["size"] = size_m.group(1)

    return attrs


def _extract_karat(variant_title: str) -> str:
    return _parse_variant_attributes(variant_title).get("karat", "")


def _variant_attributes_line(product: dict) -> str:
    """Material + karat/color/size for captions and list rows."""
    variant = product.get("variant") or {}
    variant_title = variant.get("title") or ""
    attrs = _parse_variant_attributes(variant_title)
    material = _material_label(product)

    parts = [material]
    if attrs.get("karat"):
        parts.append(attrs["karat"])
    if attrs.get("color"):
        parts.append(attrs["color"])
    if attrs.get("size"):
        parts.append(f"Size {attrs['size']}")

    if len(parts) == 1 and variant_title:
        karat = _extract_karat(variant_title)
        return f"{material} · {karat}" if karat else material
    return " · ".join(parts)


def _material_label(product: dict) -> str:
    material = product.get("materialType") or product.get("material") or ""
    if isinstance(material, list):
        return " + ".join(m.title() for m in material if m) or "Jewellery"
    if isinstance(material, dict):
        material = material.get("name") or material.get("title") or ""
    return str(material).strip() or "Jewellery"


def _product_sku(product: dict) -> str | None:
    inventory = product.get("inventory") or {}
    if isinstance(inventory, dict):
        sku = inventory.get("skuId") or inventory.get("sku")
        if sku:
            return str(sku).strip()
    return None


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


def get_product_mrp_price(product: dict) -> int | None:
    """Compare-at MRP from API only when strictly above display price."""
    return get_product_price_bundle(product).get("mrp_price")


def get_product_display_price(product: dict) -> int:
    """Return customer-facing listing price from current Clara API fields."""
    return get_product_price_bundle(product)["display_price"]


def get_product_price_bundle(product: dict) -> dict[str, Any]:
    """Structured price info for captions and dashboard snapshots (API-only)."""
    resolved = resolve_product_prices(product)
    return {
        "display_price": resolved["display_price"],
        "mrp_price": resolved["mrp_price"],
        "promo_label": resolved["promo_label"],
        "has_dynamic_pricing": resolved["has_dynamic_pricing"],
        "sku": _product_sku(product),
    }


def format_price_line(product: dict) -> str:
    """Single price line; strikethrough MRP only when API sends mrp > display."""
    bundle = get_product_price_bundle(product)
    display = bundle["display_price"]
    mrp = bundle["mrp_price"]
    if mrp and display and mrp > display:
        return f"₹{display:,}  ~₹{mrp:,}~"
    return f"₹{display:,}"


def _product_caption_lines(product: dict, *, include_sku: bool = False) -> list[str]:
    """Shared caption body for product image messages."""
    title = product.get("title") or "Product"
    bundle = get_product_price_bundle(product)
    material_line = _variant_attributes_line(product)

    shipping = product.get("shipping") or {}
    edd = shipping.get("edd", "?")

    lines = [
        f"*{title}*",
        format_price_line(product),
        material_line,
        f"🚚 Delivery in {edd} days",
    ]

    if include_sku and bundle.get("sku"):
        lines.append(f"SKU: {bundle['sku']}")

    if product.get("withChain") == "noChain":
        lines.append("⚠️ Chain not included")

    promo = bundle.get("promo_label")
    if promo:
        lines.append(f"🏷 {promo.replace(' %', '%')}")

    if bundle.get("has_dynamic_pricing"):
        lines.append("_Confirm exact total on kisna.com (gold rate may update)._")

    return lines


def format_product_buy_caption(product: dict) -> str:
    """Image caption for product detail / Buy Now (no URL — CTA carries link)."""
    return "\n".join(_product_caption_lines(product, include_sku=True))


def _assets_cdn_base() -> str:
    return (
        os.getenv("KISNA_ASSETS_CDN_BASE")
        or "https://kisna-assets.blr1.cdn.digitaloceanspaces.com"
    ).rstrip("/")


def _normalize_image_url(url: Any) -> Optional[str]:
    """Return a usable HTTPS image URL, or None."""
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None
    if text.startswith("//"):
        text = "https:" + text
    elif text.startswith("/"):
        text = _assets_cdn_base() + text
    elif text.startswith("compressed/"):
        text = f"{_assets_cdn_base()}/{text}"
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
    """Prefer plp sort, then isDefault, else first valid image in the list."""
    plp_url: Optional[str] = None
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
        sort_val = str(item.get("sort") or "").lower()
        if sort_val == "plp" and plp_url is None:
            plp_url = url
        if item.get("isDefault"):
            default_url = url
        elif fallback_url is None:
            fallback_url = url

    return plp_url or default_url or fallback_url


def get_product_image_url(product: dict) -> Optional[str]:
    """Return primary product image URL from Clara ``mediaUrl[].image`` or fallbacks."""
    candidates: list[Optional[str]] = []

    media = product.get("mediaUrl") or product.get("media")
    if isinstance(media, list) and media:
        candidates.append(_url_from_media_list(media))

    if isinstance(media, str):
        candidates.append(_normalize_image_url(media))

    for key in ("image", "image_url", "thumbnail", "previewImage"):
        candidates.append(_normalize_image_url(product.get(key)))

    images = product.get("images")
    if isinstance(images, list):
        candidates.append(_url_from_media_list(images))

    variant = product.get("variant")
    if isinstance(variant, dict):
        variant_media = variant.get("mediaUrl") or variant.get("media")
        if isinstance(variant_media, list):
            candidates.append(_url_from_media_list(variant_media))
        candidates.append(_normalize_image_url(variant.get("image")))

    product_type = product.get("productType")
    if isinstance(product_type, dict):
        type_media = product_type.get("mediaUrl") or product_type.get("media")
        if isinstance(type_media, list):
            candidates.append(_url_from_media_list(type_media))

    snapshot_url = product.get("image_url_snapshot")
    if snapshot_url:
        candidates.append(_normalize_image_url(snapshot_url))

    for url in candidates:
        if url:
            return url

    # Image conversion handled by get_whatsapp_safe_image_url()
    return None


def get_product_image_url_for_whatsapp(product: dict) -> Optional[str]:
    """Return raw product image URL (wrap with get_whatsapp_safe_image_url before send)."""
    return get_product_image_url(product)


def get_whatsapp_safe_image_url(raw_url: str) -> str | None:
    """
    Wraps a .webp URL with Cloudinary Fetch to return a
    WhatsApp-compatible JPEG URL.
    Returns the original URL unchanged if already JPEG.
    Returns None if raw_url is empty.
    Returns raw_url as fallback if CLOUDINARY_CLOUD_NAME not set.
    """
    # If Cloudinary free tier limits are hit (25k transforms/month)
    # or client requests self-hosted storage, replace this with
    # Cloudflare R2 (free 10GB, zero egress) or Vercel Blob.
    # The interface stays identical — only this function changes.
    if not raw_url:
        return None

    lower = raw_url.lower().split("?")[0]
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return raw_url

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    if not cloud_name:
        logger.warning(
            "CLOUDINARY_CLOUD_NAME not set — sending original webp URL"
        )
        return raw_url

    cloudinary_url = (
        f"https://res.cloudinary.com/{cloud_name}"
        f"/image/fetch/f_jpg,q_85,fl_progressive/{raw_url}"
    )
    logger.debug(
        "image: wrapping webp for WhatsApp delivery",
        extra={"original": raw_url, "whatsapp_url": cloudinary_url},
    )
    return cloudinary_url


def format_product_image_caption(product: dict) -> str:
    """WhatsApp image caption for search carousel (includes product link)."""
    lines = _product_caption_lines(product)
    lines.extend(["", f"🔗 {build_product_url(product)}"])
    return "\n".join(lines)


def format_product_list_row(product: dict) -> dict:
    """Single row for WhatsApp interactive list."""
    title = _truncate(product.get("title") or "Product", 24)
    material_line = _variant_attributes_line(product)
    shipping = product.get("shipping") or {}
    edd = shipping.get("edd", "?")
    price_line = format_price_line(product)
    description = _truncate(f"{price_line} · {material_line} · {edd}d delivery", 72)
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
    *,
    client_filtered: bool = False,
) -> dict:
    """WhatsApp interactive list message dict."""
    header = f"💎 {search_context}" if search_context else "💎 KISNA Jewellery"
    if client_filtered:
        n = len(products)
        body = (
            f"Showing {n} piece{'s' if n != 1 else ''} matching your search.\n"
            "Tap to view details."
        )
    else:
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
        "globalButtons": [{"type": "text", "title": BROWSE_PRODUCTS_GLOBAL_TITLE}],
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
