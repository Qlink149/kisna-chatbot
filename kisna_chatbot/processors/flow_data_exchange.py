"""Business logic for WhatsApp Flow data_exchange (callback / video call,
and the Store Visit Flow via processors/store_visit_flow.py)."""

from __future__ import annotations

from kisna_chatbot.config.gupshup import get_callback_flow_id, get_videocall_flow_id
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.support_slots import screen_data_for_date, today_ist_iso

_CALLBACK_SCREEN = "CALLBACK_REQUEST"
_VIDEO_SCREEN = "VIDEO_CALL_REQUEST"


def _resolve_screen(decrypted: dict) -> str:
    screen = (decrypted.get("screen") or "").strip()
    if screen in (_CALLBACK_SCREEN, _VIDEO_SCREEN):
        return screen
    token = str(decrypted.get("flow_token") or "")
    if token and token == get_videocall_flow_id():
        return _VIDEO_SCREEN
    if token and token == get_callback_flow_id():
        return _CALLBACK_SCREEN
    # Default to callback screen for unknown tokens (preview / dry-run)
    return _CALLBACK_SCREEN


def _extract_preferred_date(data: dict) -> str | None:
    if not isinstance(data, dict):
        return None
    for key in (
        "preferred_date",
        "date",
        "selected_date",
    ):
        val = data.get(key)
        if val:
            return str(val).strip()
    return None


def build_flow_response(decrypted: dict) -> dict:
    """
    Map decrypted Meta Flow request → cleartext response object
    (before encryption).
    """
    action = (decrypted.get("action") or "").strip()
    data_in = decrypted.get("data") if isinstance(decrypted.get("data"), dict) else {}

    if action == "ping":
        return {"data": {"status": "active"}}

    # Store Visit has its own screens and a per-send flow_token; everything
    # below this line is the callback / video-call slot picker.
    from kisna_chatbot.processors.store_visit_flow import (
        build_store_visit_response,
        is_store_visit_request,
    )

    if is_store_visit_request(decrypted):
        return build_store_visit_response(decrypted)

    screen = _resolve_screen(decrypted)

    if action in ("INIT", "BACK"):
        payload = screen_data_for_date(today_ist_iso())
        logger.info(
            "Flow INIT/BACK",
            extra={"action": action, "screen": screen, "slots": len(payload["time_slots"])},
        )
        return {"screen": screen, "data": payload}

    if action == "data_exchange":
        preferred_date = _extract_preferred_date(data_in) or today_ist_iso()
        payload = screen_data_for_date(preferred_date)
        # Preserve other form fields Meta echoes when refreshing the screen
        # (mobile/reason may be re-sent via init-values on client; we only refresh slots).
        logger.info(
            "Flow data_exchange",
            extra={
                "screen": screen,
                "preferred_date": preferred_date,
                "slots": len(payload["time_slots"]),
                "trigger": data_in.get("trigger"),
            },
        )
        return {"screen": screen, "data": payload}

    logger.warning("Unknown Flow action", extra={"action": action})
    payload = screen_data_for_date(today_ist_iso())
    return {"screen": screen, "data": payload}
