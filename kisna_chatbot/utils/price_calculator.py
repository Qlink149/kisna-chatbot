"""
Resolve customer-facing prices from Clara /products list API fields only.

No estimated MRP or hardcoded making-charge ratios — only values present in
the API response (variantPrice, salePrice, mrpPrice, finalPrice, promotions).
"""

from typing import Any, Optional


def product_promo_material(product: dict) -> str | None:
    """Primary material bucket for promo category matching (Gold/Diamond)."""
    material = product.get("materialType")
    if isinstance(material, list):
        for item in material:
            if isinstance(item, str) and item.lower() in ("gold", "diamond"):
                return item.lower()
        return material[0].lower() if material else None
    if isinstance(material, str):
        return material.lower()
    return None


def _int_price(val: Any) -> int | None:
    if val is None:
        return None
    try:
        parsed = int(float(val))
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _is_labour_promo(promo: dict) -> bool:
    disc_on = (promo.get("discOn") or "").strip().lower()
    if not disc_on:
        return True
    return disc_on in ("labour", "making charges", "making charge")


def find_matching_labour_promo(
    product: dict,
    price: float,
) -> Optional[dict]:
    """Return the embedded Labour promo whose amount tier contains price."""
    promotions = product.get("promotions") or []
    if not isinstance(promotions, list):
        return None

    product_material = product_promo_material(product)

    for promo in promotions:
        if not isinstance(promo, dict) or not _is_labour_promo(promo):
            continue
        promo_cat = (promo.get("category") or "").strip().lower()
        if promo_cat and product_material:
            if promo_cat == "gold" and product_material != "gold":
                continue
            if promo_cat == "diamond" and product_material not in (
                "diamond",
                "gemstone",
            ):
                continue
        try:
            from_amt = float(promo.get("fromAmt", 0))
            to_amt = float(promo.get("toAmt", float("inf")))
        except (TypeError, ValueError):
            continue
        if from_amt <= price <= to_amt:
            return promo
    return None


def promo_discount_percent(promo: dict) -> float:
    disc = promo.get("disc") or promo.get("discount")
    if disc is None:
        return 0.0
    try:
        return float(disc)
    except (TypeError, ValueError):
        return 0.0


def format_promo_label(promo: dict) -> str | None:
    """Human-readable promo line from API promo object (percentage only)."""
    disc_val = promo_discount_percent(promo)
    if disc_val <= 0:
        return None
    label = promo.get("discountLable") or promo.get("discountLabel") or ""
    label = str(label).replace(" %", "%").strip()
    if label:
        return label
    if disc_val == int(disc_val):
        return f"{int(disc_val)}% off making charges"
    return f"{disc_val}% off making charges"


def base_listing_price(product: dict) -> int:
    """Canonical catalogue price used for promo tier matching."""
    price_block = product.get("price") or {}
    if not isinstance(price_block, dict):
        price_block = {}
    return (
        _int_price(price_block.get("variantPrice"))
        or _int_price((product.get("variant") or {}).get("salePrice"))
        or 0
    )


def resolve_product_prices(product: dict) -> dict[str, Any]:
    """
    Resolve display and MRP strictly from API fields.

    MRP strikethrough is shown only when variant.mrpPrice (or price-level MRP)
    is strictly greater than the display price in the same payload.
    """
    price_block = product.get("price") or {}
    if not isinstance(price_block, dict):
        price_block = {}
    variant = product.get("variant") or {}
    if not isinstance(variant, dict):
        variant = {}

    listing_price = base_listing_price(product)

    display_price = 0
    for key in ("finalPrice", "totalPrice"):
        parsed = _int_price(price_block.get(key))
        if parsed:
            display_price = parsed
            break

    if not display_price:
        sale = _int_price(variant.get("salePrice"))
        block_sale = _int_price(price_block.get("salePrice"))
        variant_listing = _int_price(price_block.get("variantPrice"))
        candidates = [p for p in (sale, block_sale) if p]
        discounted = min(candidates) if candidates else None
        if discounted and variant_listing and discounted < variant_listing:
            display_price = discounted
        elif listing_price:
            display_price = listing_price
        elif discounted:
            display_price = discounted

    api_mrp = _int_price(variant.get("mrpPrice")) or _int_price(
        price_block.get("mrpPrice")
    )
    mrp_price: int | None = None
    if api_mrp and display_price and api_mrp > display_price:
        mrp_price = api_mrp

    promo_label: str | None = None
    if listing_price:
        promo = find_matching_labour_promo(product, float(listing_price))
        if promo:
            promo_label = format_promo_label(promo)

    return {
        "display_price": display_price,
        "mrp_price": mrp_price,
        "promo_label": promo_label,
        "listing_price": listing_price,
        "has_dynamic_pricing": bool(price_block.get("dynamicPricing")),
    }
