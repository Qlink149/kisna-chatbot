from kisna_chatbot.database.db_utils import save_complaint
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_COMPLAINT_TYPE = "5_Return_Refund_Request"
_GENERIC_ERROR = (
    "Sorry, we couldn't register your return/refund request right now. "
    "Please try again or contact our support team."
)


def _extract_issue_summary(data: dict) -> str:
    messages = data.get("messages", {})
    text_body = messages.get("text", {}).get("body")
    if text_body and str(text_body).strip():
        return str(text_body).strip()[:500]
    return "Return or refund request via WhatsApp"


class ReturnsRefundAgent(Processor):
    """Register return/refund requests as complaints in MongoDB."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        user_profile = data.get("user_profile", {})
        if data.get("classified_category") == "returns_refund":
            return True
        return user_profile.get("service_selected") == "returns_refund"

    async def process(self, data: dict) -> dict:
        phone_number = data.get("phone_number", "")
        user_profile = data.get("user_profile", {})
        client_id = data.get("client_id", "kisna")

        if not self.should_run(data):
            logger.info(
                "Skipping processor",
                extra={
                    "processor": self.__class__.__name__,
                    "phone_number": phone_number,
                },
            )
            return data

        issue = _extract_issue_summary(data)
        customer_name = user_profile.get("username") or data.get("whatsapp_username", "")

        try:
            save_complaint(
                phone_number=phone_number,
                issue=issue,
                complaint_type=_COMPLAINT_TYPE,
                case_id="",
                client_id=client_id,
                order_id="",
                customer_name=customer_name,
            )
            data["bot_response"] = [
                {
                    "type": "text",
                    "text": (
                        "Thank you for reaching out. Your return/refund request "
                        "has been registered.\n\nOur team will contact you within 24 hours."
                    ),
                }
            ]
            user_profile["service_selected"] = ""
            logger.info(
                "Return/refund complaint registered",
                extra={"phone_number": phone_number, "client_id": client_id},
            )
            return data
        except Exception as e:
            logger.exception(
                "Failed to register return/refund complaint",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
