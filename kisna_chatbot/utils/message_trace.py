"""Plain-language per-message traces for the dashboard chat view."""

from __future__ import annotations

import time
from typing import Any

from kisna_chatbot.utils.logger_config import logger

_OUTCOMES = {
    "products_sent",
    "no_products",
    "fallback_used",
    "menu_sent",
    "handoff",
    "error",
    "info_sent",
}


def trace_step(
    data: dict,
    label: str,
    detail: str,
    status: str = "ok",
) -> None:
    """Append a step onto data['_trace_steps'] (never raises)."""
    try:
        steps = data.setdefault("_trace_steps", [])
        steps.append(
            {
                "order": len(steps) + 1,
                "label": label,
                "detail": detail or "",
                "status": status if status in ("ok", "warn", "error") else "ok",
            }
        )
    except Exception:
        logger.warning("trace_step failed", exc_info=True)


def _summarize_reply(bot_response: Any) -> str:
    if not bot_response:
        return "No reply"
    if isinstance(bot_response, dict):
        bot_response = [bot_response]
    if not isinstance(bot_response, list):
        return "Reply sent"

    counts: dict[str, int] = {}
    for item in bot_response:
        if not isinstance(item, dict):
            continue
        t = item.get("type") or "text"
        counts[t] = counts.get(t, 0) + 1

    parts: list[str] = []
    if counts.get("product") or counts.get("image"):
        n = counts.get("product") or counts.get("image") or 0
        parts.append(f"{n} product card{'s' if n != 1 else ''}")
    if counts.get("list"):
        parts.append("menu list")
    if counts.get("button") or counts.get("quick_reply"):
        parts.append("buttons")
    if counts.get("cta_url"):
        parts.append("link button")
    if counts.get("text") and not parts:
        parts.append("text reply")
    elif counts.get("text") and parts:
        parts.append("text")
    if counts.get("flow"):
        parts.append("WhatsApp form")
    return " + ".join(parts) if parts else "Reply sent"


def _derive_outcome(steps: list[dict], bot_response: Any) -> str:
    labels = {s.get("label") for s in steps}
    statuses = {s.get("status") for s in steps}
    if "Error" in labels or "error" in statuses:
        return "error"
    details = " ".join((s.get("detail") or "").lower() for s in steps)
    if "handoff" in details or "live agent" in details or "human" in " ".join(labels).lower():
        if any("handoff" in (s.get("label") or "").lower() or "live" in (s.get("detail") or "").lower() for s in steps):
            return "handoff"
    if any(s.get("label") == "Closest-match search" for s in steps):
        return "fallback_used"
    if any(s.get("label") == "Searched catalogue" for s in steps):
        searched = [s for s in steps if s.get("label") == "Searched catalogue"]
        if searched and all(s.get("status") == "warn" for s in searched):
            # Check if products still went out via fallback
            if any(s.get("label") == "Closest-match search" for s in steps):
                return "fallback_used"
            reply = _summarize_reply(bot_response).lower()
            if "product" in reply:
                return "products_sent"
            return "no_products"
        reply = _summarize_reply(bot_response).lower()
        if "product" in reply:
            return "products_sent"
        if searched and searched[-1].get("status") == "warn":
            return "no_products"
        return "products_sent" if "product" in reply else "info_sent"
    reply = _summarize_reply(bot_response).lower()
    if "menu" in reply or "list" in reply:
        return "menu_sent"
    if "handoff" in details:
        return "handoff"
    return "info_sent"


def summarize_filters(entities: dict | None) -> str:
    """Human-readable filter summary (omit nulls)."""
    if not entities:
        return "No filters"
    parts: list[str] = []
    cat = entities.get("category") or entities.get("categories")
    if isinstance(cat, list):
        cat = ", ".join(str(c) for c in cat if c)
    if cat:
        parts.append(str(cat).replace("_", " ").title())
    mat = entities.get("material_type")
    if mat:
        parts.append(str(mat).replace("_", " ").title())
    title = entities.get("title")
    if title:
        parts.append(f'“{title}”')
    min_p = entities.get("min_price")
    max_p = entities.get("max_price")
    if min_p is not None and max_p is not None:
        parts.append(f"₹{int(min_p):,}–₹{int(max_p):,}")
    elif max_p is not None:
        parts.append(f"under ₹{int(max_p):,}")
    elif min_p is not None:
        parts.append(f"above ₹{int(min_p):,}")
    return " · ".join(parts) if parts else "No filters"


def summarize_search_params(api_params: dict | None, total_count: int | None = None) -> str:
    if not api_params:
        base = "Catalogue search"
    else:
        bits: list[str] = []
        if api_params.get("category"):
            bits.append(f"Category: {api_params['category']}")
        if api_params.get("material_type") or api_params.get("materialType"):
            bits.append(
                f"Material: {api_params.get('material_type') or api_params.get('materialType')}"
            )
        min_p = api_params.get("min_price") or api_params.get("minPrice")
        max_p = api_params.get("max_price") or api_params.get("maxPrice")
        if min_p is not None or max_p is not None:
            lo = int(min_p or 0)
            hi = int(max_p) if max_p is not None else None
            if hi is not None:
                bits.append(f"Price: ₹{lo:,}–₹{hi:,}")
            else:
                bits.append(f"Price: from ₹{lo:,}")
        if api_params.get("title"):
            bits.append(f"Title: {api_params['title']}")
        base = ", ".join(bits) if bits else "Catalogue search"
    if total_count is not None:
        base = f"{base} → {int(total_count)} product{'s' if total_count != 1 else ''} found"
    return base


def ensure_reply_step(data: dict) -> None:
    """Add a Reply sent step from bot_response if not already present."""
    try:
        steps = data.get("_trace_steps") or []
        if any(s.get("label") == "Reply sent" for s in steps):
            return
        if "bot_response" not in data:
            return
        trace_step(data, "Reply sent", _summarize_reply(data.get("bot_response")))
    except Exception:
        logger.warning("ensure_reply_step failed", exc_info=True)


def persist_message_trace(data: dict) -> None:
    """Fire-and-forget write of the message_traces document."""
    try:
        request_id = data.get("request_id")
        if not request_id:
            return
        ensure_reply_step(data)
        steps = list(data.get("_trace_steps") or [])
        if not steps:
            return

        from kisna_chatbot.database.collections import message_traces

        outcome = data.get("_trace_outcome") or _derive_outcome(
            steps, data.get("bot_response")
        )
        if outcome not in _OUTCOMES:
            outcome = "info_sent"

        user_message = ""
        messages = data.get("messages") or {}
        if isinstance(messages, dict):
            if messages.get("type") == "text":
                user_message = (messages.get("text") or {}).get("body") or ""
            elif messages.get("type") == "interactive":
                interactive = messages.get("interactive") or {}
                user_message = (
                    (interactive.get("button_reply") or {}).get("title")
                    or (interactive.get("list_reply") or {}).get("title")
                    or (interactive.get("nfm_reply") or {}).get("name")
                    or "Button / form"
                )
            else:
                user_message = messages.get("type") or ""

        doc = {
            "request_id": request_id,
            "client_id": data.get("client_id") or "kisna",
            "phone_number": data.get("phone_number"),
            "ts": int(time.time()),
            "user_message": user_message,
            "steps": steps,
            "outcome": outcome,
        }
        message_traces.update_one(
            {"request_id": request_id, "client_id": doc["client_id"]},
            {"$set": doc},
            upsert=True,
        )
    except Exception:
        logger.warning("persist_message_trace failed", exc_info=True)


def ensure_message_traces_ttl_index() -> None:
    """Create 30-day TTL index on message_traces.ts (safe to call at startup)."""
    try:
        from kisna_chatbot.database.collections import message_traces

        message_traces.create_index(
            "ts",
            expireAfterSeconds=30 * 24 * 60 * 60,
            name="message_traces_ttl_30d",
        )
    except Exception:
        logger.warning("Failed to ensure message_traces TTL index", exc_info=True)


def get_message_trace(request_id: str, client_id: str = "kisna") -> dict | None:
    try:
        from kisna_chatbot.database.collections import message_traces

        doc = message_traces.find_one(
            {"request_id": request_id, "client_id": client_id},
            {"_id": 0},
        )
        return doc
    except Exception:
        logger.warning("get_message_trace failed", exc_info=True)
        return None
