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
_VARIANT_KARAT_RE = re.compile(r"\b(9|14|18|22|24)KT\b", re.I)
_VARIANT_COLOUR_RE = re.compile(r"\b(Yellow|White|Rose)\b", re.I)
_VARIANT_SIZE_RE = re.compile(r"\b([7-9]|1[0-9]|2[0-2])\b")


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


def parse_variant_details(product: dict) -> dict[str, Any]:
    """
    Parse metal colour, karat, and size from variant.title.
    Format: "{Material} {KT} {Colour} {Size} {Quality}"
    """
    cached = product.get("_parsed")
    if isinstance(cached, dict):
        return cached

    variant_title = (product.get("variant") or {}).get("title") or ""
    result: dict[str, Any] = {"karat": None, "metal_colour": None, "size": None}

    karat_match = _VARIANT_KARAT_RE.search(variant_title)
    if karat_match:
        result["karat"] = karat_match.group(0).upper()

    colour_match = _VARIANT_COLOUR_RE.search(variant_title)
    if colour_match:
        result["metal_colour"] = colour_match.group(0).lower()
    else:
        for media in product.get("mediaUrl") or []:
            if not isinstance(media, dict):
                continue
            colour = (media.get("color") or "").strip().lower()
            if colour in ("yellow", "white", "rose"):
                result["metal_colour"] = colour
                break

    size_matches = _VARIANT_SIZE_RE.findall(variant_title)
    if size_matches:
        result["size"] = int(size_matches[-1])

    product["_parsed"] = result
    return result


def _parse_variant_attributes(variant_title: str) -> dict[str, str]:
    """Parse karat, metal color, and ring size from Clara variant.title."""
    parsed = parse_variant_details({"variant": {"title": variant_title}})
    attrs: dict[str, str] = {}
    if parsed.get("karat"):
        attrs["karat"] = str(parsed["karat"])
    if parsed.get("metal_colour"):
        attrs["color"] = str(parsed["metal_colour"]).title()
    if parsed.get("size") is not None:
        attrs["size"] = str(parsed["size"])
    return attrs


def _extract_karat(variant_title: str) -> str:
    return _parse_variant_attributes(variant_title).get("karat", "")


def _variant_attributes_line(product: dict) -> str:
    """Material + karat/color/size for captions and list rows."""
    variant = product.get("variant") or {}
    variant_title = variant.get("title") or ""
    parsed = parse_variant_details(product)
    material = _material_label(product)

    parts = [material]
    if parsed.get("karat"):
        parts.append(str(parsed["karat"]))
    if parsed.get("metal_colour"):
        parts.append(str(parsed["metal_colour"]).title())
    if parsed.get("size") is not None:
        parts.append(f"Size {parsed['size']}")

    if len(parts) == 1 and variant_title:
        karat = parsed.get("karat") or ""
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


_CATALOGUE_BASE = "https://www.kisna.com/jewellery"

_CATEGORY_PLURALS = {
    "ring": "rings",
    "earring": "earrings",
    "necklace": "necklaces",
    "pendant": "pendants",
    "bracelet": "bracelets",
    "bangle": "bangles",
    "mangalsutra": "mangalsutra",
    "chain": "chains",
    "nosewear": "nose-wear",
    "watchwear": "watch-wear",
    "maang_tikka": "maang-tikka",
    "anklet": "anklets",
}


def _slugify_segment(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower().strip())
    return slug.strip("-")


def _category_catalogue_segment(category: str | None) -> str | None:
    if not category:
        return None
    cat = category.strip().lower()
    if cat in _CATEGORY_PLURALS:
        return _CATEGORY_PLURALS[cat]
    if cat.endswith("s"):
        return cat.replace("_", "-")
    return f"{cat.replace('_', '-')}s"


def _price_band_segment(min_price: Any, max_price: Any) -> str | None:
    min_p = _int_price(min_price)
    max_p = _int_price(max_price)
    if min_p is None and max_p is None:
        return None
    if min_p is not None and max_p is not None:
        low_k = int(min_p) // 1000
        high_k = int(max_p) // 1000
        return f"{low_k}k-to-{high_k}k"
    if max_p is not None:
        low = max(0, int(max_p) - 10000)
        return f"{low // 1000}k-to-{int(max_p) // 1000}k"
    if min_p is not None:
        high = int(min_p) + 10000
        return f"{int(min_p) // 1000}k-to-{high // 1000}k"
    return None


def _material_catalogue_segment(material_type: str | None) -> str | None:
    if not material_type:
        return None
    material = material_type.strip().lower()
    if material in ("white_gold", "rose_gold"):
        return "gold"
    if material in ("silver", "platinum", "pearl"):
        return None
    return material


def build_catalogue_url(entities: dict[str, Any]) -> str:
    """Build KISNA jewellery catalogue deep-link from extracted entities."""
    parts: list[str] = []

    category_part = _category_catalogue_segment(entities.get("category"))
    if category_part:
        parts.append(category_part)

    price_part = _price_band_segment(
        entities.get("min_price"), entities.get("max_price")
    )
    if price_part:
        parts.append(price_part)

    material_part = _material_catalogue_segment(entities.get("material_type"))
    if material_part:
        parts.append(material_part)

    karat = entities.get("karat")
    if karat:
        parts.append(str(karat).lower().replace(" ", ""))

    colour = entities.get("metal_colour")
    if colour:
        parts.append(str(colour).lower())

    collection = entities.get("collection") or entities.get("title")
    if collection and str(collection).lower() not in (
        "bridal",
        "traditional",
        "modern",
        "minimal",
        "heavy",
    ):
        coll_slug = _slugify_segment(
            str(collection).replace(" Collection", "").replace(" collection", "")
        )
        if coll_slug:
            parts.append(coll_slug)

    occasion = entities.get("occasion")
    if occasion:
        parts.append(_slugify_segment(str(occasion).replace("_", " ")))

    if not parts:
        return _CATALOGUE_BASE
    return f"{_CATALOGUE_BASE}/{'+'.join(parts)}"


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


_GOLD_RATE_DISCLAIMER = (
    "Price may vary as per current gold rate. For exact price click button below."
)


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
        _GOLD_RATE_DISCLAIMER,
        material_line,
        f"🚚 Shipping in {edd} days",
    ]

    if include_sku and bundle.get("sku"):
        lines.append(f"SKU: {bundle['sku']}")

    if product.get("withChain") == "noChain":
        lines.append("⚠️ Chain not included")

    promo = bundle.get("promo_label")
    if promo:
        lines.append(f"🏷 {promo.replace(' %', '%')}")

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
    Wrap image URLs with Cloudinary Fetch for consistent WhatsApp delivery.
    Returns None if raw_url is empty.
    Returns raw_url as fallback if CLOUDINARY_CLOUD_NAME not set.
    """
    # If Cloudinary free tier limits are hit (25k transforms/month)
    # or client requests self-hosted storage, replace this with
    # Cloudflare R2 (free 10GB, zero egress) or Vercel Blob.
    # The interface stays identical — only this function changes.
    if not raw_url:
        return None

    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
    if not cloud_name:
        logger.warning(
            "CLOUDINARY_CLOUD_NAME not set — sending original image URL"
        )
        return raw_url

    cloudinary_url = (
        f"https://res.cloudinary.com/{cloud_name}"
        f"/image/fetch/f_jpg,q_85,fl_progressive/{raw_url}"
    )
    logger.debug(
        "image: wrapping for WhatsApp delivery",
        extra={"original": raw_url, "whatsapp_url": cloudinary_url},
    )
    return cloudinary_url


def format_product_image_caption(product: dict) -> str:
    """WhatsApp image caption for search carousel (no URL — CTA carries link)."""
    return "\n".join(_product_caption_lines(product))


def format_product_list_row(product: dict) -> dict:
    """Single row for WhatsApp interactive list."""
    title = _truncate(product.get("title") or "Product", 24)
    material_line = _variant_attributes_line(product)
    shipping = product.get("shipping") or {}
    edd = shipping.get("edd", "?")
    price_line = format_price_line(product)
    description = _truncate(f"{price_line} · {material_line} · {edd}d shipping", 72)
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
    lines = [
        "I couldn't find an exact match for that. Let me show you some "
        "beautiful alternatives, or you can browse our full collection at kisna.com. 💎",
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

    lines.append("Browse full collection: https://www.kisna.com")
    return "\n".join(lines)
