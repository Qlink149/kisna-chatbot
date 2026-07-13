"""Format live gold rates from Clara API for WhatsApp replies."""

from __future__ import annotations

import re
from typing import Any

from kisna_chatbot.integrations.clara_api import ClaraAPIError
from kisna_chatbot.utils.clara_cache import get_cached_gold_rates
from kisna_chatbot.utils.kisna_url_tracking import append_kisna_utm, kisna_home_url
from kisna_chatbot.utils.logger_config import logger

_FALLBACK = (
    "I couldn't fetch today's gold rate right now. "
    "Please check the latest rates on kisna.com 🙏"
)

# Preferred display order (highest purity first).
_KT_ORDER = ("24kt", "22kt", "18kt", "14kt", "9kt")


def _extract_rate_entries(body: Any) -> list[dict]:
    if isinstance(body, list):
        return [x for x in body if isinstance(x, dict)]
    if not isinstance(body, dict):
        return []

    data = body.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("rates", "data", "items"):
            nested = data.get(key)
            if isinstance(nested, list):
                return [x for x in nested if isinstance(x, dict)]
        if any(
            k in data for k in ("rate", "goldRate", "price", "kt", "karat", "22k", "24k")
        ):
            return [data]
    return []


def _is_active(entry: dict) -> bool:
    """Treat missing `active` as active (older payloads); explicit false is excluded."""
    if "active" not in entry:
        return True
    return entry.get("active") is True


def _karat_label(entry: dict) -> str | None:
    raw = (
        entry.get("kt")
        or entry.get("karat")
        or entry.get("label")
        or entry.get("name")
        or entry.get("type")
        or entry.get("metal")
    )
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    # Normalize "24kt" / "24K" / "24 kt" → "24KT"
    m = re.match(r"^(\d+)\s*k(?:t)?$", text, flags=re.IGNORECASE)
    if m:
        return f"{m.group(1)}KT"
    return text.upper() if text.lower().endswith("kt") else text


def _karat_sort_key(entry: dict) -> tuple[int, int]:
    label = (_karat_label(entry) or "").lower()
    for idx, preferred in enumerate(_KT_ORDER):
        if preferred.replace("kt", "") in label.replace("kt", "").replace("k", ""):
            # prefer exact purity match
            purity = re.match(r"^(\d+)", preferred)
            entry_purity = re.match(r"^(\d+)", label)
            if purity and entry_purity and purity.group(1) == entry_purity.group(1):
                return (0, idx)
    # Unknown karat → after known ones, higher number first
    m = re.match(r"^(\d+)", label)
    purity = int(m.group(1)) if m else -1
    return (1, -purity)


def _format_price(value: Any) -> str | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    # Whole rupees when clean; otherwise 2 decimal places.
    if abs(amount - round(amount)) < 1e-9:
        return f"₹{int(round(amount)):,}/g"
    return f"₹{amount:,.2f}/g"


def _format_rate_line(entry: dict) -> str | None:
    if not _is_active(entry):
        return None

    value = (
        entry.get("rate")
        or entry.get("goldRate")
        or entry.get("price")
        or entry.get("value")
        or entry.get("amount")
    )
    price = _format_price(value)
    if price is None:
        return None

    karat = _karat_label(entry)
    if karat:
        return f"• *{karat}* — {price}"
    return f"• {price}"


def format_gold_rates_reply(body: Any) -> str:
    entries = [e for e in _extract_rate_entries(body) if _is_active(e)]
    entries.sort(key=_karat_sort_key)

    lines = ["*Today's KISNA Gold Rates* ✨", ""]
    for entry in entries:
        line = _format_rate_line(entry)
        if line:
            lines.append(line)

    # Fallback for flat dict payloads without kt/price objects
    if len([ln for ln in lines if ln.startswith("•")]) == 0:
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, dict):
                for key, val in data.items():
                    if key.lower() in {"rate", "goldrate", "price", "22k", "24k", "18k"}:
                        price = _format_price(val)
                        if price:
                            lines.append(f"• *{key.upper()}* — {price}")
        if len([ln for ln in lines if ln.startswith("•")]) == 0 and isinstance(
            body, dict
        ):
            for key, val in body.items():
                if isinstance(val, (int, float)) and "rate" in key.lower():
                    price = _format_price(val)
                    if price:
                        lines.append(f"• *{key}* — {price}")

    if len([ln for ln in lines if ln.startswith("•")]) == 0:
        return _FALLBACK

    home = append_kisna_utm(kisna_home_url())
    lines.append("")
    lines.append("_Per gram · rates change through the day._")
    lines.append(f"Browse jewellery: {home}")
    return "\n".join(lines)


async def build_gold_rate_bot_response(app_state=None) -> list[dict]:
    try:
        rates = await get_cached_gold_rates(app_state)
        text = format_gold_rates_reply(rates)
    except ClaraAPIError as e:
        logger.warning("Gold rate fetch failed", extra={"error": str(e)})
        text = _FALLBACK
    except Exception:
        logger.exception("Unexpected gold rate error")
        text = _FALLBACK

    return [{"type": "text", "text": text}]
