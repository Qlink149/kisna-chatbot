import json
import time

from kisna_chatbot.config.gupshup import get_damage_complaint_flow_id
from kisna_chatbot.database.collections import complaints
from kisna_chatbot.integrations.clara_events import (
    build_complaint_event,
    enqueue_event as enqueue_clara_event,
)
from kisna_chatbot.integrations.crm_adapter import CRMAdapter, CRMError
from kisna_chatbot.models.enums import FLowId, FlowId
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.request_ids import generate_request_id


def _complaint_flow_ids() -> frozenset[str]:
    # FIX 8: guard against None when KISNA_DAMAGE_FLOW_ID env var is unset.
    # Without this, any nfm_reply with flow_token=None would match and falsely
    # trigger complaint handling.
    flow_id = get_damage_complaint_flow_id()
    ids = {
        FLowId.DAMAGE_COMPLAINT.value,
        FlowId.COMPLAINT_FLOW.value,
        flow_id,
    }
    return frozenset(f for f in ids if f)  # exclude None and empty strings

_GENERIC_ERROR = (
    "Sorry, we couldn't register your complaint right now. "
    "Please try again or contact our support team."
)


def _parse_complaint_flow(messages: dict) -> dict | None:
    """
    Parse WhatsApp flow reply from messages when flow_token matches complaint flow.

    Returns:
        Parsed flow_data dict, or None if not a complaint flow submission.
    """
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
            "Failed to parse complaint flow response_json",
            extra={"error": str(e)},
        )
        return None

    if not isinstance(flow_data, dict):
        return None

    flow_token = flow_data.get("flow_token")
    if flow_token not in _complaint_flow_ids():
        return None

    return flow_data


def _extract_complaint_fields(flow_data: dict) -> tuple[str, str, str]:
    """
    Extract order_id, issue_description, and complaint_type from flow payload.

    Supports semantic keys and NKL/Gupshup screen field names.
    """
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


def _extract_contact_fields(flow_data: dict) -> dict[str, str]:
    """Category-specific contact fields added in the v2 complaint form
    (registered mobile / email-or-contact / invoice number). Absent from the
    old form's payload -> all blank, and every downstream use is a no-op.
    """
    return {
        "registered_mobile": str(flow_data.get("registered_mobile") or "").strip(),
        "registered_contact": str(flow_data.get("registered_contact") or "").strip(),
        "invoice_number": str(flow_data.get("invoice_number") or "").strip(),
    }


def _augment_issue_with_contact(issue: str, contact: dict[str, str]) -> str:
    """Fold the contact fields into the issue text so they still reach CRM /
    Clara without changing those payload contracts. No-op when none were given
    (old-form submissions), so the byte-for-byte event tests are unaffected.
    """
    extras = []
    if contact.get("registered_mobile"):
        extras.append(f"Registered mobile: {contact['registered_mobile']}")
    if contact.get("registered_contact"):
        extras.append(f"Registered email / contact: {contact['registered_contact']}")
    if contact.get("invoice_number"):
        extras.append(f"Invoice no.: {contact['invoice_number']}")
    if not extras:
        return issue
    block = "Contact details provided:\n" + "\n".join(extras)
    return f"{issue}\n\n{block}" if issue else block


def _is_want_to_buy(complaint_type: str) -> bool:
    """A purchase enquiry is not a complaint (client request, C9). The v2 form
    no longer offers this option; this only catches a stale cached form."""
    return complaint_type.strip().lower().startswith(("0_want_to_buy", "want to buy", "want_to_buy"))


def _build_confirmation(case_id: str) -> list[dict]:
    """Build bot_response confirmation text after complaint registration."""
    lines = [
        "Thank you for reaching out. Your complaint has been registered.",
    ]
    if case_id:
        lines.append(f"Case ID: {case_id}")
    lines.append("Our team will contact you within 24 hours.")
    return [{"type": "text", "text": "\n".join(lines), "_compose": "complaint_registered"}]


class ComplaintAgent(Processor):
    """Processor for WhatsApp complaint flow submissions (CRM + Mongo)."""

    def should_run(self, data: dict) -> bool:
        """
        Run when the inbound message is a complaint flow nfm_reply with matching flow_token.
        """
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        return _parse_complaint_flow(messages) is not None

    async def process(self, data: dict) -> dict:
        """
        Register complaint: VTiger case (best-effort), Mongo persistence, user confirmation.
        """
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})

        if not self.should_run(data):
            logger.info(
                "Skipping ComplaintAgent",
                extra={"phone_number": phone_number},
            )
            return data

        try:
            client_config = data["client_config"]
            messages = data["messages"]
            client_id = data.get("client_id") or client_config.client_id
            customer_name = user_profile.get("username") or data.get(
                "whatsapp_username", ""
            )

            flow_data = _parse_complaint_flow(messages)
            if not flow_data:
                return data

            order_id, issue_description, complaint_type = _extract_complaint_fields(
                flow_data
            )
            contact = _extract_contact_fields(flow_data)

            # C9: "Want to Buy" is a purchase enquiry, not a complaint. The v2
            # form drops the option; this handles a stale cached form by
            # routing to the sales journey instead of logging a junk case.
            if _is_want_to_buy(complaint_type):
                logger.info(
                    "Complaint form submitted with Want-to-Buy — routing to sales",
                    extra={"phone_number": phone_number, "client_id": client_id},
                )
                user_profile["service_selected"] = ""
                data["bot_response"] = [
                    {
                        "type": "text",
                        "text": (
                            "Looks like you'd like to buy something rather than raise a "
                            "complaint. 😊 Just tell me what you're after — e.g. "
                            "\"gold earrings under 30k\" — and I'll show you options."
                        ),
                        "_compose": "complaint_want_to_buy_redirect",
                    }
                ]
                return data

            issue_description = _augment_issue_with_contact(issue_description, contact)

            logger.info(
                "Complaint received",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "complaint_type": complaint_type,
                    "has_contact_fields": any(contact.values()),
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

            # Complaints have no id of their own; VTiger's case_id is often
            # empty. Mint a stable one so the outbound event is idempotent and
            # support has something to search on.
            request_id = generate_request_id("CMP")
            created_at = int(time.time())

            mongo_saved = False
            try:
                complaints.insert_one(
                    {
                        "client_id": client_id,
                        "request_id": request_id,
                        "phone_number": phone_number,
                        "order_id": order_id,
                        "issue": issue_description,
                        "type": complaint_type,
                        "case_id": case_id,
                        "customer_name": customer_name,
                        "created_at": created_at,
                        "status": "registered" if case_id else "crm_pending",
                        # v2 form category-specific contact fields (blank for
                        # old-form submissions).
                        "registered_mobile": contact["registered_mobile"],
                        "registered_contact": contact["registered_contact"],
                        "invoice_number": contact["invoice_number"],
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

            if mongo_saved:
                await enqueue_clara_event(
                    build_complaint_event(
                        event_id=request_id,
                        client_id=client_id,
                        phone_number=phone_number,
                        customer_name=customer_name,
                        order_id=order_id,
                        complaint_type=complaint_type,
                        issue_description=issue_description,
                        occurred_at_epoch=created_at,
                    )
                )

            if mongo_saved or issue_description or order_id:
                data["bot_response"] = _build_confirmation(case_id)
            else:
                data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR, "_compose": "system_error"}]

            user_profile["service_selected"] = ""

            logger.info(
                "Complaint registered successfully",
                extra={
                    "phone_number": phone_number,
                    "order_id": order_id,
                    "case_id": case_id,
                    "request_id": request_id,
                    "mongo_saved": mongo_saved,
                },
            )
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in ComplaintAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR, "_compose": "system_error"}]
            return data
