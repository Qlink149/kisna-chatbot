import json
import time

from kisna_chatbot.config.gupshup import get_callback_flow_id, get_videocall_flow_id
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.database.collections import callback_requests
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.request_ids import generate_request_id
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)

_REASON_LABELS = {
    "product_enquiry": "Product Enquiry",
    "order_support": "Order Support",
    "store_assistance": "Store Assistance",
    "exchange_return": "Exchange/Return",
    "other": "Other",
}

_TIME_LABELS = {
    "morning": "Morning (10 AM–1 PM)",
    "afternoon": "Afternoon (1 PM–5 PM)",
}

_GENERIC_ERROR = (
    "Sorry, we couldn't register your request right now. "
    "Please try again or contact our support team."
)


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


def _extract_request_fields(flow_data: dict) -> tuple[str, str, str, str]:
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

    if request_type == "video_call":
        reason = ""

    return request_type, mobile, reason, preferred_time


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


def _build_confirmation(request_id: str, request_type: str) -> list[dict]:
    label = "video call" if request_type == "video_call" else "callback"
    return [
        {
            "type": "text",
            "text": (
                f"Thank you! Your {label} request has been registered.\n"
                f"Request ID: {request_id}\n"
                "Our team will contact you soon."
            ),
        }
    ]


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
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})

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

            request_type, mobile, reason, preferred_time = _extract_request_fields(
                flow_data
            )

            request_id = generate_request_id(
                "VC" if request_type == "video_call" else "CB"
            )

            callback_requests.insert_one(
                {
                    "request_id": request_id,
                    "client_id": client_id,
                    "phone_number": phone_number,
                    "username": customer_name,
                    "mobile": mobile,
                    "reason": reason or None,
                    "preferred_time": preferred_time,
                    "request_type": request_type,
                    "status": "pending",
                    "created_at": int(time.time()),
                }
            )

            _notify_admins(
                customer_name,
                phone_number,
                request_id,
                request_type,
                mobile,
            )

            data["bot_response"] = _build_confirmation(request_id, request_type)
            user_profile["service_selected"] = ""
            user_profile.pop("callback_capture_step", None)
            user_profile.pop("callback_draft", None)

            logger.info(
                "Support request registered",
                extra={
                    "phone_number": phone_number,
                    "request_id": request_id,
                    "request_type": request_type,
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
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})
        text = (data.get("messages", {}).get("text", {}).get("body") or "").strip()

        if not text:
            return data

        step = int(user_profile.get("callback_capture_step") or 0)
        draft = dict(user_profile.get("callback_draft") or {})
        request_type = draft.get("request_type", "callback")

        if step == 1:
            draft["mobile"] = text
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
            request_id = generate_request_id(
                "VC" if request_type == "video_call" else "CB"
            )
            callback_requests.insert_one(
                {
                    "request_id": request_id,
                    "client_id": client_id,
                    "phone_number": phone_number,
                    "username": customer_name,
                    "mobile": draft.get("mobile", ""),
                    "reason": draft.get("reason") or None,
                    "preferred_time": draft.get("preferred_time", ""),
                    "request_type": request_type,
                    "status": "pending",
                    "created_at": int(time.time()),
                }
            )
            _notify_admins(
                customer_name,
                phone_number,
                request_id,
                request_type,
                draft.get("mobile", ""),
            )
            data["bot_response"] = _build_confirmation(request_id, request_type)
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


def build_callback_text_prompt(step: int) -> str:
    if step == 1:
        return "Please share the mobile number we should call you on."
    if step == 2:
        return (
            "What is this regarding?\n"
            "Reply with: Product Enquiry, Order Support, Store Assistance, "
            "Exchange/Return, or Other"
        )
    return (
        "When would you prefer a callback?\n"
        "Reply with: Morning (10 AM–1 PM) or Afternoon (1 PM–5 PM)"
    )


def build_video_call_text_prompt(step: int) -> str:
    if step == 1:
        return "Please share the mobile number for your video call."
    return (
        "When would you prefer the video call?\n"
        "Reply with: Morning (10 AM–1 PM) or Afternoon (1 PM–5 PM)"
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


def _normalize_time_text(text: str) -> str:
    normalized = (text or "").strip().lower()
    if "morning" in normalized:
        return "morning"
    if "afternoon" in normalized:
        return "afternoon"
    return normalized.replace(" ", "_")
