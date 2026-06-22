import json
import time

from kisna_chatbot.config.gupshup import get_damage_complaint_flow_id
from kisna_chatbot.database.collections import complaints
from kisna_chatbot.integrations.crm_adapter import CRMAdapter, CRMError
from kisna_chatbot.models.enums import FLowId, FlowId
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger


def _complaint_flow_ids() -> frozenset[str]:
    ids = {
        FLowId.DAMAGE_COMPLAINT.value,
        FlowId.COMPLAINT_FLOW.value,
        get_damage_complaint_flow_id(),
    }
    return frozenset(ids)


_GENERIC_ERROR = (
    "Sorry, we couldn't register your complaint right now. "
    "Please try again or contact our support team."
)

_COMPLAINT_FLOW_RESPONSE = {
    "type": "flow",
    "flow": "damage_complaint",
    "text": "Please provide your order details and describe the issue.",
}


def build_complaint_flow_bot_response() -> dict:
    """WhatsApp Flow payload for damage / quality complaints."""
    return dict(_COMPLAINT_FLOW_RESPONSE)


def _parse_complaint_flow(messages: dict) -> dict | None:
    """
    Parse WhatsApp flow reply from messages when flow_token matches complaint flow.

    Only nfm_reply messages represent a completed form submission.
    """
    interactive = messages.get("interactive") or {}

    nfm_payload = interactive.get("nfm_reply") or messages.get("nfm_reply")
    if not nfm_payload:
        return None

    if nfm_payload.get("name") not in (None, "flow"):
        return None

    if "response_json" in nfm_payload:
        try:
            flow_data = json.loads(nfm_payload["response_json"])
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            logger.warning(
                "Failed to parse complaint flow response_json",
                extra={"error": str(e)},
            )
            return None
    else:
        flow_data = nfm_payload

    if not isinstance(flow_data, dict):
        return None

    flow_token = flow_data.get("flow_token")
    if (
        flow_token not in _complaint_flow_ids()
        and "screen_0_Order_ID_0" not in flow_data
        and "order_id" not in flow_data
    ):
        logger.warning(
            "Complaint flow reply not recognised — ignoring",
            extra={"flow_token": flow_token, "known_ids": list(_complaint_flow_ids())},
        )
        return None

    return flow_data


def _extract_complaint_fields(flow_data: dict) -> tuple[str, str, str]:
    """Extract order_id, issue_description, and complaint_type from flow payload."""
    order_id = (
        flow_data.get("order_id")
        or flow_data.get("reference_number")
        or flow_data.get("screen_0_Order_ID_0")
        or ""
    )
    issue_description = (
        flow_data.get("issue_description")
        or flow_data.get("screen_0_Issue_Description_1")
        or ""
    )
    complaint_type = (
        flow_data.get("complaint_type")
        or flow_data.get("type")
        or flow_data.get("screen_0_complaint_type_2")
        or ""
    )
    return (
        str(order_id).strip(),
        str(issue_description).strip(),
        str(complaint_type).strip(),
    )


def _build_confirmation(case_id: str) -> list[dict]:
    """Build bot_response confirmation text after complaint registration."""
    lines = [
        "Thank you for reaching out. Your complaint has been registered.",
    ]
    if case_id:
        lines.append(f"Case ID: {case_id}")
    lines.append("Our team will contact you within 24 hours.")
    return [{"type": "text", "text": "\n".join(lines)}]


class ComplaintAgent(Processor):
    """
    Unified complaint flow processor (NKL DamageDetails pattern).

    Sends the WhatsApp Flow on first entry and processes nfm_reply submissions.
    """

    def should_run(self, data: dict) -> bool:
        """Run when no outbound response has been queued yet."""
        return "bot_response" not in data

    async def _register_complaint(self, data: dict, flow_data: dict) -> dict:
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})
        client_config = data["client_config"]
        client_id = data.get("client_id") or client_config.client_id
        customer_name = user_profile.get("username") or data.get("whatsapp_username", "")

        order_id, issue_description, complaint_type = _extract_complaint_fields(flow_data)

        logger.info(
            "Complaint received",
            extra={
                "phone_number": phone_number,
                "order_id": order_id,
                "complaint_type": complaint_type,
                "client_id": client_id,
            },
        )

        case_id = ""
        crm = CRMAdapter(client_config)
        try:
            result = await crm.create_case(
                title=f"Complaint - {order_id or 'N/A'}",
                description=issue_description,
                case_type=complaint_type,
                phone=phone_number,
                customer_name=customer_name,
            )
            case_id = str(result.get("id", "") or "")
        except (CRMError, ValueError) as e:
            logger.exception(
                "VTiger case creation failed; saving complaint locally",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "error": str(e),
                },
            )
        finally:
            await crm.aclose()

        mongo_saved = False
        try:
            complaints.insert_one(
                {
                    "client_id": client_id,
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "issue": issue_description,
                    "type": complaint_type,
                    "case_id": case_id,
                    "customer_name": customer_name,
                    "created_at": int(time.time()),
                    "status": "registered" if case_id else "crm_pending",
                }
            )
            mongo_saved = True
        except Exception as e:
            logger.exception(
                "Failed to save complaint to MongoDB",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "error": str(e),
                },
            )

        if mongo_saved or issue_description or order_id:
            data["bot_response"] = _build_confirmation(case_id)
        else:
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]

        user_profile["service_selected"] = ""

        logger.info(
            "Complaint registered successfully",
            extra={
                "phone_number": phone_number,
                "order_id": order_id,
                "case_id": case_id,
                "mongo_saved": mongo_saved,
            },
        )
        return data

    async def process(self, data: dict) -> dict:
        """Send complaint flow or register a completed nfm_reply submission."""
        phone_number = data.get("phone_number", "")

        if not self.should_run(data):
            logger.info(
                "Skipping ComplaintAgent",
                extra={"phone_number": phone_number},
            )
            return data

        try:
            messages = data.get("messages", {})
            flow_data = _parse_complaint_flow(messages)
            if flow_data:
                return await self._register_complaint(data, flow_data)

            logger.info(
                "Sending damage complaint flow",
                extra={"phone_number": phone_number},
            )
            data["bot_response"] = [build_complaint_flow_bot_response()]
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in ComplaintAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
