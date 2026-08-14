import json
import re
import time
from datetime import datetime, timedelta, timezone

from kisna_chatbot.config.gupshup import get_callback_flow_id, get_videocall_flow_id
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.database.collections import callback_requests
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.request_ids import generate_request_id
from kisna_chatbot.utils.support_slots import (
    SLOT_LABELS,
    available_slots_for_date,
    format_slots_for_prompt,
    normalize_slot_id,
    resolve_booking_slot,
    today_ist_iso,
)
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)

_IST = timezone(timedelta(hours=5, minutes=30))

_REASON_LABELS = {
    "product_enquiry": "Product Enquiry",
    "order_support": "Order Support",
    "store_assistance": "Store Assistance",
    "exchange_return": "Exchange/Return",
    "other": "Other",
}

_TIME_LABELS = {
    **SLOT_LABELS,
    # Legacy values from older flows
    "morning": "Morning — 10 AM–1 PM",
    "afternoon": "Afternoon — 1 PM–3 PM",
    "10-11": "Morning — 10 AM–1 PM",
    "11-12": "Morning — 10 AM–1 PM",
    "12-13": "Morning — 10 AM–1 PM",
    "13-14": "Afternoon — 1 PM–3 PM",
    "14-15": "Afternoon — 1 PM–3 PM",
    "15-16": "Evening — 3 PM–6 PM",
    "16-17": "Evening — 3 PM–6 PM",
}

_SLOT_ORDER = {
    "10-13": 0,
    "13-15": 1,
    "15-18": 2,
    "10-16": 0,
    # Legacy
    "10-11": 0,
    "11-12": 0,
    "12-13": 0,
    "13-14": 1,
    "14-15": 1,
    "15-16": 2,
    "16-17": 2,
    "morning": 0,
    "afternoon": 1,
}

_GENERIC_ERROR = (
    "Sorry, we couldn't register your request right now. "
    "Please try again or contact our support team."
)

_MOBILE_DIGITS_HINT = (
    "Please enter digits only, or reply skip to use this WhatsApp number."
)

_SKIP_MOBILE_RE = re.compile(
    r"^(?:skip|same|none|na|n/?a|no|-)?$",
    re.I,
)


def _digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def resolve_callback_mobile(entered: str | None, default_phone: str) -> str:
    """Use the typed number when it has digits; otherwise the WhatsApp number."""
    return _digits_only(entered) or _digits_only(default_phone)


def parse_text_mobile(
    text: str, default_phone: str
) -> tuple[str | None, str | None]:
    """Return (mobile, error). error is set when the reply is not digits or skip."""
    raw = (text or "").strip()
    if _SKIP_MOBILE_RE.match(raw):
        return resolve_callback_mobile("", default_phone), None
    if re.search(r"[A-Za-z]", raw):
        return None, _MOBILE_DIGITS_HINT
    digits = _digits_only(raw)
    if not digits:
        return None, _MOBILE_DIGITS_HINT
    return digits, None

_REJECT_FULLY_BOOKED = (
    "We're fully booked for the next several weeks. "
    "Please try again later or contact our support team."
)

_REJECT_INVALID = (
    "We couldn't use that date/time. Please request again and choose a "
    "valid future slot."
)


def _today_ist_iso() -> str:
    return datetime.now(_IST).date().isoformat()


def _is_past_date(iso_date: str) -> bool:
    try:
        preferred = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return preferred < datetime.now(_IST).date()


def _callback_flow_ids() -> frozenset[str]:
    ids = {get_callback_flow_id(), get_videocall_flow_id()}
    return frozenset(f for f in ids if f)


def _parse_support_request_flow(messages: dict) -> dict | None:
    interactive = messages.get("interactive")
    if not interactive or "nfm_reply" not in interactive:
        return None

    nfm_reply = interactive["nfm_reply"]
    if "response_json" not in nfm_reply:
        return None

    try:
        flow_data = json.loads(nfm_reply["response_json"])
    except (json.JSONDecodeError, TypeError, KeyError) as e:
        logger.warning(
            "Failed to parse support request flow response_json",
            extra={"error": str(e)},
        )
        return None

    if not isinstance(flow_data, dict):
        return None

    flow_token = flow_data.get("flow_token")
    if flow_token not in _callback_flow_ids():
        return None

    return flow_data


def _extract_request_fields(flow_data: dict) -> tuple[str, str, str, str, str]:
    request_type = str(
        flow_data.get("request_type")
        or (
            "video_call"
            if flow_data.get("flow_token") == get_videocall_flow_id()
            else "callback"
        )
    ).strip()

    mobile = str(
        flow_data.get("mobile")
        or flow_data.get("screen_0_mobile_0")
        or ""
    ).strip()
    reason = str(flow_data.get("reason") or "").strip()
    preferred_time = str(
        flow_data.get("preferred_time")
        or flow_data.get("screen_0_preferred_time_1")
        or ""
    ).strip()
    preferred_date = str(
        flow_data.get("preferred_date")
        or flow_data.get("screen_0_preferred_date_0")
        or ""
    ).strip()

    if request_type == "video_call":
        reason = ""

    return request_type, mobile, reason, preferred_time, preferred_date


def _display_reason(reason_key: str) -> str:
    return _REASON_LABELS.get(reason_key, reason_key.replace("_", " ").title())


def _display_time(time_key: str) -> str:
    return _TIME_LABELS.get(time_key, time_key.replace("_", " ").title())


def _notify_admins(
    customer_name: str,
    customer_phone: str,
    request_id: str,
    request_type: str,
    mobile: str,
) -> None:
    label = "Video Call" if request_type == "video_call" else "Callback"
    for admin in ADMINS:
        send_customer_support_template(
            phone_number=admin,
            customer_name=f"{customer_name} ({label} {request_id})",
            customer_phone=mobile or customer_phone,
        )


def _build_confirmation(
    request_id: str,
    request_type: str,
    *,
    preferred_date: str = "",
    preferred_time: str = "",
    was_rescheduled: bool = False,
) -> list[dict]:
    label = "video call" if request_type == "video_call" else "callback"
    slot_label = _display_time(preferred_time) if preferred_time else preferred_time
    lines = [
        f"Thank you! Your {label} request has been registered.",
        f"Request ID: {request_id}",
    ]
    if preferred_date and preferred_time:
        lines.append(f"Scheduled for: {preferred_date} · {slot_label}")
    if was_rescheduled:
        lines.append(
            "Your preferred slot was full, so we booked the next available "
            "time for you."
        )
    lines.append("Our team will contact you soon.")
    return [{"type": "text", "text": "\n".join(lines)}]


def _resolve_or_reject(
    preferred_date: str, preferred_time: str
) -> tuple[str, str, bool] | str:
    """
    Return (date, slot, was_rescheduled) or an error message string.
    """
    resolved = resolve_booking_slot(preferred_date, preferred_time)
    if resolved is None:
        if preferred_date or preferred_time:
            return _REJECT_FULLY_BOOKED
        return _REJECT_INVALID
    return resolved



def _build_request_doc(
    *,
    request_id: str,
    client_id: str,
    phone_number: str,
    customer_name: str,
    mobile: str,
    reason: str | None,
    preferred_time: str,
    preferred_date: str,
    request_type: str,
) -> dict:
    preferred_time_label = _display_time(preferred_time) if preferred_time else ""
    doc = {
        "request_id": request_id,
        "client_id": client_id,
        "phone_number": phone_number,
        "username": customer_name,
        "mobile": mobile,
        "reason": reason or None,
        "preferred_date": preferred_date or None,
        "preferred_time": preferred_time,
        "preferred_time_label": preferred_time_label,
        "preferred_time_order": _SLOT_ORDER.get(preferred_time, 99),
        "request_type": request_type,
        "status": "pending",
        "created_at": int(time.time()),
    }
    if preferred_date:
        doc["preferred_date_past"] = _is_past_date(preferred_date)
    else:
        doc["preferred_date_past"] = False
    return doc


class CallbackAgent(Processor):
    """Processor for callback and video-call WhatsApp flow submissions."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        messages = data.get("messages", {})
        if _parse_support_request_flow(messages) is not None:
            return True
        user_profile = data.get("user_profile", {})
        return (
            user_profile.get("service_selected") == SL.CALLBACK.value
            and user_profile.get("callback_capture_step")
        )

    async def process(self, data: dict) -> dict:
        if not self.should_run(data):
            return data

        messages = data.get("messages", {})
        flow_data = _parse_support_request_flow(messages)
        if flow_data:
            return await self._process_flow_submission(data, flow_data)

        return await self._process_text_capture(data)

    async def _process_flow_submission(self, data: dict, flow_data: dict) -> dict:
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})

        try:
            client_config = data["client_config"]
            client_id = data.get("client_id") or client_config.client_id
            customer_name = user_profile.get("username") or data.get(
                "whatsapp_username", ""
            )

            (
                request_type,
                mobile,
                reason,
                preferred_time,
                preferred_date,
            ) = _extract_request_fields(flow_data)

            resolved = _resolve_or_reject(preferred_date, preferred_time)
            if isinstance(resolved, str):
                data["bot_response"] = [{"type": "text", "text": resolved}]
                user_profile["service_selected"] = ""
                user_profile.pop("callback_capture_step", None)
                user_profile.pop("callback_draft", None)
                logger.info(
                    "Support request rejected (no available slot)",
                    extra={
                        "phone_number": phone_number,
                        "preferred_date": preferred_date,
                        "preferred_time": preferred_time,
                    },
                )
                return data

            preferred_date, preferred_time, was_rescheduled = resolved

            mobile = resolve_callback_mobile(mobile, phone_number)

            request_id = generate_request_id(
                "VC" if request_type == "video_call" else "CB"
            )

            callback_requests.insert_one(
                _build_request_doc(
                    request_id=request_id,
                    client_id=client_id,
                    phone_number=phone_number,
                    customer_name=customer_name,
                    mobile=mobile,
                    reason=reason,
                    preferred_time=preferred_time,
                    preferred_date=preferred_date,
                    request_type=request_type,
                )
            )

            _notify_admins(
                customer_name,
                phone_number,
                request_id,
                request_type,
                mobile,
            )

            data["bot_response"] = _build_confirmation(
                request_id,
                request_type,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                was_rescheduled=was_rescheduled,
            )
            user_profile["service_selected"] = ""
            user_profile.pop("callback_capture_step", None)
            user_profile.pop("callback_draft", None)

            logger.info(
                "Support request registered",
                extra={
                    "phone_number": phone_number,
                    "request_id": request_id,
                    "request_type": request_type,
                    "preferred_date": preferred_date,
                    "preferred_time": preferred_time,
                    "was_rescheduled": was_rescheduled,
                },
            )
            return data

        except Exception as e:
            logger.exception(
                "Exception in CallbackAgent flow submission",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data

    async def _process_text_capture(self, data: dict) -> dict:
        user_profile = data.get("user_profile", {})
        text = (data.get("messages", {}).get("text", {}).get("body") or "").strip()

        if not text:
            return data

        step = int(user_profile.get("callback_capture_step") or 0)
        draft = dict(user_profile.get("callback_draft") or {})
        request_type = draft.get("request_type", "callback")

        if step == 1:
            mobile, error = parse_text_mobile(text, data.get("phone_number", ""))
            if error:
                data["bot_response"] = [{"type": "text", "text": error}]
                return data
            draft["mobile"] = mobile
            user_profile["callback_draft"] = draft
            if request_type == "video_call":
                user_profile["callback_capture_step"] = 2
                data["bot_response"] = [
                    {"type": "text", "text": build_video_call_text_prompt(2)}
                ]
            else:
                user_profile["callback_capture_step"] = 2
                data["bot_response"] = [
                    {"type": "text", "text": build_callback_text_prompt(2)}
                ]
            return data

        if step == 2 and request_type == "callback":
            draft["reason"] = _normalize_reason_text(text)
            user_profile["callback_draft"] = draft
            user_profile["callback_capture_step"] = 3
            data["bot_response"] = [
                {"type": "text", "text": build_callback_text_prompt(3)}
            ]
            return data

        if (step == 2 and request_type == "video_call") or (
            step == 3 and request_type == "callback"
        ):
            draft["preferred_date"] = _normalize_date_text(text)
            user_profile["callback_draft"] = draft
            next_step = 3 if request_type == "video_call" else 4
            user_profile["callback_capture_step"] = next_step
            prompt = (
                build_video_call_text_prompt(
                    3, preferred_date=draft["preferred_date"]
                )
                if request_type == "video_call"
                else build_callback_text_prompt(
                    4, preferred_date=draft["preferred_date"]
                )
            )
            data["bot_response"] = [{"type": "text", "text": prompt}]
            return data

        if (step == 3 and request_type == "video_call") or (
            step == 4 and request_type == "callback"
        ):
            draft["preferred_time"] = _normalize_time_text(text)
            user_profile["callback_draft"] = draft
            return await self._save_text_request(data, draft)

        data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
        return data

    async def _save_text_request(self, data: dict, draft: dict) -> dict:
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})
        try:
            client_config = data["client_config"]
            client_id = data.get("client_id") or client_config.client_id
            customer_name = user_profile.get("username") or data.get(
                "whatsapp_username", ""
            )
            request_type = draft.get("request_type", "callback")
            preferred_date = draft.get("preferred_date", "")
            preferred_time = draft.get("preferred_time", "")
            resolved = _resolve_or_reject(preferred_date, preferred_time)
            if isinstance(resolved, str):
                data["bot_response"] = [{"type": "text", "text": resolved}]
                user_profile["service_selected"] = ""
                user_profile.pop("callback_capture_step", None)
                user_profile.pop("callback_draft", None)
                return data

            preferred_date, preferred_time, was_rescheduled = resolved

            mobile = resolve_callback_mobile(
                draft.get("mobile", ""), phone_number
            )

            request_id = generate_request_id(
                "VC" if request_type == "video_call" else "CB"
            )
            callback_requests.insert_one(
                _build_request_doc(
                    request_id=request_id,
                    client_id=client_id,
                    phone_number=phone_number,
                    customer_name=customer_name,
                    mobile=mobile,
                    reason=draft.get("reason"),
                    preferred_time=preferred_time,
                    preferred_date=preferred_date,
                    request_type=request_type,
                )
            )
            _notify_admins(
                customer_name,
                phone_number,
                request_id,
                request_type,
                mobile,
            )
            data["bot_response"] = _build_confirmation(
                request_id,
                request_type,
                preferred_date=preferred_date,
                preferred_time=preferred_time,
                was_rescheduled=was_rescheduled,
            )
            user_profile["service_selected"] = ""
            user_profile.pop("callback_capture_step", None)
            user_profile.pop("callback_draft", None)
            return data
        except Exception as e:
            logger.exception(
                "Exception saving text callback request",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data


def build_callback_text_prompt(
    step: int, preferred_date: str | None = None
) -> str:
    if step == 1:
        return (
            "Mobile number is optional — reply skip to use this WhatsApp number, "
            "or send the digits we should call."
        )
    if step == 2:
        return (
            "What is this regarding?\n"
            "Reply with: Product Enquiry, Order Support, Store Assistance, "
            "Exchange/Return, or Other"
        )
    if step == 3:
        return (
            "Which date works for you?\n"
            "Reply with a date like 15-07-2026 or 2026-07-15."
        )
    date_key = preferred_date or today_ist_iso()
    slots = available_slots_for_date(date_key)
    return (
        "Which time slot works best?\n"
        f"Reply with one of: {format_slots_for_prompt(slots)}"
    )


def build_video_call_text_prompt(
    step: int, preferred_date: str | None = None
) -> str:
    if step == 1:
        return (
            "Mobile number is optional — reply skip to use this WhatsApp number, "
            "or send the digits for the video call."
        )
    if step == 2:
        return (
            "Which date works for you?\n"
            "Reply with a date like 15-07-2026 or 2026-07-15."
        )
    date_key = preferred_date or today_ist_iso()
    slots = available_slots_for_date(date_key)
    return (
        "Which time slot works best?\n"
        f"Reply with one of: {format_slots_for_prompt(slots)}"
    )


def _normalize_reason_text(text: str) -> str:
    normalized = (text or "").strip().lower()
    mapping = {
        "product enquiry": "product_enquiry",
        "order support": "order_support",
        "store assistance": "store_assistance",
        "exchange/return": "exchange_return",
        "exchange": "exchange_return",
        "return": "exchange_return",
        "other": "other",
    }
    return mapping.get(normalized, normalized.replace(" ", "_"))


def _normalize_date_text(text: str) -> str:
    raw = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return raw


def _normalize_time_text(text: str) -> str:
    normalized = (text or "").strip().lower().replace(" ", "")
    if normalized in _TIME_LABELS or normalized in SLOT_LABELS:
        return normalize_slot_id(normalized)
    # Map free-text mentions to new blocks
    hour_map = {
        "10-13": "10-13",
        "13-15": "13-15",
        "15-18": "15-18",
        "10-16": "10-16",
        "10-11": "10-13",
        "11-12": "10-13",
        "12-13": "10-13",
        "13-14": "13-15",
        "14-15": "13-15",
        "15-16": "15-18",
        "16-17": "15-18",
    }
    for key, slot in hour_map.items():
        if key in normalized:
            return slot
    if "morning" in normalized or "10am" in normalized or "10a" in normalized:
        return "10-13"
    if "evening" in normalized or "3pm" in normalized or "3p" in normalized:
        return "15-18"
    if "afternoon" in normalized or "1pm" in normalized or "1p" in normalized:
        return "13-15"
    return normalize_slot_id(normalized.replace(" ", "_"))
