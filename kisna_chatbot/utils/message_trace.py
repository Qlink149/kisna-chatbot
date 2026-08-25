"""Plain-language per-message traces for the dashboard chat view."""

from __future__ import annotations

import time
import traceback
from typing import Any

# Trimmed so a trace doc stays small — the TTL keeps 30 days of these.
_MAX_TRACEBACK_CHARS = 4000
_MAX_PAYLOAD_STR = 600


def _log_warning(msg: str, **kwargs) -> None:
    try:
        from kisna_chatbot.utils.logger_config import logger

        logger.warning(msg, **kwargs)
    except Exception:
        pass


_OUTCOMES = {
    "products_sent",
    "no_products",
    "fallback_used",
    "menu_sent",
    "handoff",
    "error",
    "info_sent",
}

_PRODUCTS_PATH = "/api/v1/clara/products"

_FALLBACK_DROP_LABELS = {
    "drop_fulfillment": "ready-to-ship / made-to-order filter",
    "drop_meta": "karat/colour/collection filter",
    "drop_price": "price filter",
    "drop_price_fulfillment": "price and availability filters",
    "drop_title": "title filter",
    "drop_material": "material filter",
    "title_only": "category/material filters",
    "category_only": "all filters except category",
}


def _sanitize_payload(value: Any, _depth: int = 0) -> Any:
    """Make a step payload safe and small enough to store.

    Truncates long strings, caps list length, and stringifies anything Mongo
    would refuse. Never raises — a bad payload must not cost us the trace.
    """
    try:
        if _depth > 4:
            return "…"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value if len(value) <= _MAX_PAYLOAD_STR else value[:_MAX_PAYLOAD_STR] + "…"
        if isinstance(value, dict):
            return {
                str(k): _sanitize_payload(v, _depth + 1)
                for k, v in list(value.items())[:40]
            }
        if isinstance(value, (list, tuple, set)):
            items = list(value)
            out = [_sanitize_payload(v, _depth + 1) for v in items[:25]]
            if len(items) > 25:
                out.append(f"… +{len(items) - 25} more")
            return out
        return _sanitize_payload(str(value), _depth + 1)
    except Exception:
        return "<unserializable>"


def _elapsed_ms(data: dict) -> int | None:
    """Milliseconds since the turn started, if the turn clock was started."""
    t0 = data.get("_trace_t0")
    if not isinstance(t0, (int, float)):
        return None
    return round((time.time() - t0) * 1000)


def trace_step(
    data: dict,
    label: str,
    detail: str,
    status: str = "ok",
    *,
    payload: dict | None = None,
) -> None:
    """Append a step onto data['_trace_steps'] (never raises).

    ``detail`` stays the one-line human summary shown in the timeline; ``payload``
    carries the structured version of the same thing (raw query params, counts,
    exception info) that the dashboard renders as expandable JSON.
    """
    try:
        steps = data.setdefault("_trace_steps", [])
        step = {
            "order": len(steps) + 1,
            "label": label,
            "detail": detail or "",
            "status": status if status in ("ok", "warn", "error") else "ok",
        }
        t_ms = _elapsed_ms(data)
        if t_ms is not None:
            step["t_ms"] = t_ms
        if payload:
            step["payload"] = _sanitize_payload(payload)
        steps.append(step)
    except Exception:
        _log_warning("trace_step failed", exc_info=True)


def trace_error(data: dict | None, exc: BaseException, *, label: str = "Error") -> None:
    """Record an exception as a trace step and force the turn's outcome to error.

    Called from the webhook's top-level handler so a crashed turn still produces
    a trace — that is the case the dashboard panel exists for.
    """
    if not isinstance(data, dict):
        return
    try:
        payload = {
            "type": type(exc).__name__,
            "message": str(exc)[:_MAX_PAYLOAD_STR],
            "traceback": traceback.format_exc()[-_MAX_TRACEBACK_CHARS:],
        }
        trace_step(data, label, f"{type(exc).__name__}: {exc}", "error", payload=payload)
        data["_trace_outcome"] = "error"
        data["_trace_error"] = payload
    except Exception:
        _log_warning("trace_error failed", exc_info=True)


def format_query_params(params: dict[str, Any] | None) -> str:
    """Compact query params for dashboard (no base URL)."""
    if not params:
        return "(none)"
    parts: list[str] = []
    for key, value in params.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "(none)"


def build_clara_query_params(
    api_params: dict[str, Any] | None,
    *,
    page_no: int = 1,
    page_size: int | None = None,
) -> dict[str, Any]:
    """Map search kwargs → Clara query-string keys shown on the dashboard."""
    raw = api_params or {}
    out: dict[str, Any] = {
        "pageNo": page_no,
    }
    if page_size is not None:
        out["pageSize"] = page_size
    if raw.get("category"):
        out["category"] = raw["category"]
    if raw.get("material_type"):
        out["materialType"] = raw["material_type"]
    if raw.get("min_price") is not None:
        out["minPrice"] = raw["min_price"]
    if raw.get("max_price") is not None:
        out["maxPrice"] = raw["max_price"]
    if raw.get("title"):
        out["title"] = raw["title"]
    if raw.get("tag_manager_id"):
        out["tagManagerId"] = raw["tag_manager_id"]
    if raw.get("collection_id"):
        out["collectionId"] = raw["collection_id"]
    if raw.get("meta_sub_attribute_value"):
        out["metaSubAttributeValue"] = raw["meta_sub_attribute_value"]
    if raw.get("ready_to_ship"):
        out["readyTOShip"] = "true"
    if raw.get("made_to_order"):
        out["madeToOrder"] = "true"
    out["searchUrl"] = "true"
    return out


def _product_trace_price(product: dict) -> int:
    """Best-effort listing price for dashboard traces (never raises)."""
    try:
        from kisna_chatbot.utils.price_calculator import base_listing_price

        return int(base_listing_price(product) or 0)
    except Exception:
        try:
            price_block = product.get("price") or {}
            raw = price_block.get("variantPrice") or price_block.get("finalPrice")
            return int(float(str(raw).replace(",", ""))) if raw is not None else 0
        except Exception:
            return 0


def summarize_top_products(
    products: list | None,
    *,
    limit: int = 2,
    max_title_len: int = 48,
) -> str:
    """
    Compact top-N products for What Happened, e.g.
    Nitara Diamond Ring ₹45,999 · Elegant Gold Band ₹52,000
    """
    if not products or limit <= 0:
        return ""
    parts: list[str] = []
    for item in products:
        if len(parts) >= limit:
            break
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "Product").strip() or "Product"
        if len(title) > max_title_len:
            title = title[: max_title_len - 1].rstrip() + "…"
        price = _product_trace_price(item)
        if price > 0:
            parts.append(f"{title} ₹{price:,}")
        else:
            parts.append(title)
    return " · ".join(parts)


def summarize_api_call(
    *,
    path: str = _PRODUCTS_PATH,
    query_params: dict[str, Any] | None = None,
    total_count: int | None = None,
    matched_count: int | None = None,
    empty: bool = False,
    products: list | None = None,
    top_n: int = 2,
) -> str:
    """
    Dashboard line for a catalogue call, e.g.
    GET /api/v1/clara/products | category=Rings minPrice=45000 … → 14 products
    · Nitara Diamond Ring ₹45,999 · Elegant Gold Band ₹52,000

    When Clara returns rows that fail client filters entirely, pass
    matched_count=0 so the panel stays honest, e.g.
    → 3 products · 0 matched · Gleaming… ₹48,233
    Do not pass a positive matched_count against catalogue totalCount — that
    confuses page keepers (e.g. 13 of pageSize=15) with "13 of 249".
    """
    param_str = format_query_params(query_params)
    base = f"GET {path} | {param_str}"
    if total_count is not None:
        n = int(total_count)
        base = f"{base} → {n} product{'s' if n != 1 else ''}"
        if matched_count is not None and int(matched_count) != n:
            m = int(matched_count)
            base = f"{base} · {m} matched"
    elif empty:
        base = f"{base} → 0 products"
    top = summarize_top_products(products, limit=top_n)
    if top:
        base = f"{base} · {top}"
    return base


def _summarize_reply(bot_response: Any) -> str:
    if not bot_response:
        return "No reply"
    if isinstance(bot_response, dict):
        bot_response = [bot_response]
    if not isinstance(bot_response, list):
        return "Reply sent"

    counts: dict[str, int] = {}
    text_preview = ""
    for item in bot_response:
        if not isinstance(item, dict):
            continue
        t = (item.get("type") or "text").lower().replace("_", "")
        # Normalize quick_reply / quickreply / QuickReply
        if t in ("quickreply", "quick_reply"):
            t = "quickreply"
        counts[t] = counts.get(t, 0) + 1
        if not text_preview and t == "text":
            raw = (item.get("text") or "").strip()
            if raw:
                # First meaningful line without markdown stars
                first = next(
                    (
                        ln.strip().strip("*").strip()
                        for ln in raw.splitlines()
                        if ln.strip()
                    ),
                    "",
                )
                text_preview = first[:80]

    parts: list[str] = []
    if counts.get("product") or counts.get("image") or counts.get("imagewithcta"):
        n = (
            counts.get("product")
            or counts.get("image")
            or counts.get("imagewithcta")
            or 0
        )
        parts.append(f"{n} product card{'s' if n != 1 else ''}")
    if counts.get("list"):
        parts.append("menu list")
    if counts.get("button") or counts.get("quickreply"):
        parts.append("buttons")
    if counts.get("ctaurl"):
        parts.append("link button")
    if counts.get("flow"):
        parts.append("WhatsApp form")
    if counts.get("text"):
        if text_preview and not parts:
            parts.append(f"text — {text_preview}")
        elif text_preview and parts:
            parts.insert(0, f"text — {text_preview}")
        elif not parts:
            parts.append("text reply")
        else:
            parts.append("text")
    return " + ".join(parts) if parts else "Reply sent"


def try_trace(
    data: dict | None,
    label: str,
    detail: str,
    status: str = "ok",
    *,
    payload: dict | None = None,
) -> None:
    """Safe wrapper used by agents (no-op if data is missing)."""
    if not isinstance(data, dict):
        return
    trace_step(data, label, detail, status=status, payload=payload)



def _derive_outcome(steps: list[dict], bot_response: Any) -> str:
    labels = {s.get("label") for s in steps}
    statuses = {s.get("status") for s in steps}
    if "Error" in labels or "error" in statuses:
        return "error"
    details = " ".join((s.get("detail") or "").lower() for s in steps)
    if "handoff" in details or "live agent" in details or "human" in " ".join(labels).lower():
        if any(
            "handoff" in (s.get("label") or "").lower()
            or "live" in (s.get("detail") or "").lower()
            for s in steps
        ):
            return "handoff"
    if any(s.get("label") == "Closest-match search" for s in steps) or any(
        s.get("label") == "Search fallback" for s in steps
    ):
        return "fallback_used"
    if any(s.get("label") == "API call" for s in steps) or any(
        s.get("label") == "Searched catalogue" for s in steps
    ):
        searched = [
            s
            for s in steps
            if s.get("label") in ("API call", "Searched catalogue")
        ]
        if searched and all(s.get("status") == "warn" for s in searched):
            if any(
                s.get("label") in ("Closest-match search", "Search fallback")
                for s in steps
            ):
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
    gender = entities.get("gender")
    if gender:
        parts.append(str(gender).replace("_", " ").title())
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
    """Legacy helper — prefer summarize_api_call for new traces."""
    query = build_clara_query_params(api_params or {})
    return summarize_api_call(query_params=query, total_count=total_count)


def fallback_drop_label(log_label: str) -> str:
    return _FALLBACK_DROP_LABELS.get(log_label, log_label.replace("_", " "))


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
        _log_warning("ensure_reply_step failed", exc_info=True)


# Outcomes worth keeping a full log for. A happy turn's DEBUG chatter is noise;
# a failed or degraded one is exactly what you open the panel to read.
_INTERESTING_OUTCOMES = {"error", "no_products", "fallback_used", "handoff"}
_LOW_CONFIDENCE = 0.55

# Records carrying a timing measurement are kept even on happy turns — they are
# few (one per LLM/HTTP call) and they are what answers "why was this slow".
_TIMING_KEYS = ("latency_ms", "elapsed_ms", "duration_ms")
_KEEP_LEVELS = {"WARNING", "ERROR", "CRITICAL"}


def _is_interesting(outcome: str, confidence: Any) -> bool:
    if outcome in _INTERESTING_OUTCOMES:
        return True
    return isinstance(confidence, (int, float)) and confidence < _LOW_CONFIDENCE


def _select_logs(
    logs: list[dict],
    *,
    outcome: str,
    confidence: Any,
    steps: list[dict],
    t0: float | None,
) -> list[dict]:
    """Trim and annotate captured log records for storage.

    Full detail on turns that went wrong, warnings-and-timings only on turns that
    went fine. Each surviving record is stamped with its offset into the turn and
    the timeline step it happened under, so the panel can group them.
    """
    if not logs:
        return []

    keep_all = _is_interesting(outcome, confidence)
    selected = [
        entry
        for entry in logs
        if keep_all
        or entry.get("level") in _KEEP_LEVELS
        or any(k in (entry.get("extra") or {}) for k in _TIMING_KEYS)
    ]

    # Offsets let the UI show "+412ms" and order logs against the step timeline.
    step_bounds = [(s.get("t_ms") or 0, s.get("order")) for s in steps]
    for entry in selected:
        created = entry.pop("created", None)
        if t0 and isinstance(created, (int, float)):
            t_ms = round((created - t0) * 1000)
            entry["t_ms"] = t_ms
            step = None
            for bound, order in step_bounds:
                if bound <= t_ms:
                    step = order
                else:
                    break
            if step is not None:
                entry["step"] = step

    return selected


def _session_state_snapshot(user_profile: dict) -> dict:
    """Whitelisted session flags that explain *why* the bot routed as it did.

    Bulky product arrays are reduced to counts/ids — the useful signal is which
    filters and pending flags were live, not the catalogue rows themselves.
    """
    try:
        from kisna_chatbot.utils.session_state import (
            _SEARCH_CONTEXT_KEYS,
            _TRANSIENT_KEYS,
        )

        bulky = {"last_search_products", "last_search_buffer"}
        snapshot: dict[str, Any] = {}
        for key in (*_TRANSIENT_KEYS, *_SEARCH_CONTEXT_KEYS):
            if key not in user_profile:
                continue
            value = user_profile.get(key)
            if key in bulky:
                if isinstance(value, list):
                    snapshot[f"{key}_count"] = len(value)
                continue
            snapshot[key] = value
        return _sanitize_payload(snapshot)
    except Exception:
        _log_warning("session state snapshot failed", exc_info=True)
        return {}


def persist_message_trace(data: dict) -> None:
    """Fire-and-forget write of the message_traces document."""
    try:
        request_id = data.get("request_id")
        if not request_id:
            return
        ensure_reply_step(data)
        steps = list(data.get("_trace_steps") or [])
        if not steps and not data.get("_trace_error"):
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

        user_profile = data.get("user_profile") or {}
        reply_preview = ""
        for item in data.get("bot_response") or []:
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                reply_preview = str(item["text"])[:160]
                break

        messages_block = data.get("messages") or {}
        bot_response = data.get("bot_response") or []

        doc = {
            "request_id": request_id,
            "client_id": data.get("client_id") or "kisna",
            "phone_number": data.get("phone_number"),
            "ts": int(time.time()),
            "user_message": user_message,
            "steps": steps,
            "outcome": outcome,
            # Structured fields for the daily log review
            "intent": data.get("classified_category"),
            "confidence": data.get("classifier_confidence"),
            "language": user_profile.get("language"),
            "reply_preview": reply_preview,
            # Diagnostics for the dashboard "What happened" panel
            "latency_ms": _elapsed_ms(data),
            "error": data.get("_trace_error"),
            "service_selected": user_profile.get("service_selected"),
            "message_type": (
                messages_block.get("type") if isinstance(messages_block, dict) else None
            ),
            "bot_response_types": [
                (item.get("type") or "text")
                for item in bot_response
                if isinstance(item, dict)
            ],
            "session_state": _session_state_snapshot(user_profile),
        }

        try:
            from kisna_chatbot.utils.logger_config import get_trace_logs

            doc["logs"] = _select_logs(
                get_trace_logs(),
                outcome=outcome,
                confidence=doc.get("confidence"),
                steps=steps,
                t0=data.get("_trace_t0"),
            )
        except Exception:
            _log_warning("trace log capture failed", exc_info=True)
            doc["logs"] = []
        message_traces.update_one(
            {"request_id": request_id, "client_id": doc["client_id"]},
            {"$set": doc},
            upsert=True,
        )
    except Exception:
        _log_warning("persist_message_trace failed", exc_info=True)


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
        _log_warning("Failed to ensure message_traces TTL index", exc_info=True)


def get_message_trace(request_id: str, client_id: str = "kisna") -> dict | None:
    try:
        from kisna_chatbot.database.collections import message_traces

        doc = message_traces.find_one(
            {"request_id": request_id, "client_id": client_id},
            {"_id": 0},
        )
        return doc
    except Exception:
        _log_warning("get_message_trace failed", exc_info=True)
        return None
