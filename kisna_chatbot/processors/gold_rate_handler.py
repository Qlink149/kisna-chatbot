"""Format live gold rates from Clara API for WhatsApp replies."""

from __future__ import annotations

from typing import Any

from kisna_chatbot.integrations.clara_api import ClaraAPIError
from kisna_chatbot.utils.clara_cache import get_cached_gold_rates
from kisna_chatbot.utils.kisna_url_tracking import append_kisna_utm
from kisna_chatbot.utils.logger_config import logger

_FALLBACK = (
    "I couldn't fetch today's gold rate right now. "
    "Please check the latest rates at kisna.com 🙏"
)


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
        if any(k in data for k in ("rate", "goldRate", "price", "22k", "24k")):
            return [data]
    return []


def _format_rate_line(entry: dict) -> str | None:
    label = (
        entry.get("label")
        or entry.get("name")
        or entry.get("karat")
        or entry.get("type")
        or entry.get("metal")
    )
    value = (
        entry.get("rate")
        or entry.get("goldRate")
        or entry.get("price")
        or entry.get("value")
        or entry.get("amount")
    )
    if value is None:
        return None
    if label:
        return f"• {label}: ₹{value}/g"
    return f"• ₹{value}/g"


def format_gold_rates_reply(body: Any) -> str:
    entries = _extract_rate_entries(body)
    lines = ["*Today's KISNA Gold Rates* ✨"]
    for entry in entries:
        line = _format_rate_line(entry)
        if line:
            lines.append(line)

    if len(lines) == 1:
        if isinstance(body, dict):
            data = body.get("data")
            if isinstance(data, dict):
                for key, val in data.items():
                    if key.lower() in {"rate", "goldrate", "price", "22k", "24k", "18k"}:
                        lines.append(f"• {key}: ₹{val}/g")
        if len(lines) == 1 and isinstance(body, dict):
            for key, val in body.items():
                if isinstance(val, (int, float)) and "rate" in key.lower():
                    lines.append(f"• {key}: ₹{val}/g")

    if len(lines) == 1:
        return _FALLBACK

    lines.append(
        "\n_Rates change through the day. For jewellery prices, browse kisna.com._"
    )
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

    if "kisna.com" in text.lower() and "http" not in text:
        url = append_kisna_utm("https://www.kisna.com")
        text = text.replace("kisna.com", url.replace("https://", ""))

    return [{"type": "text", "text": text}]
