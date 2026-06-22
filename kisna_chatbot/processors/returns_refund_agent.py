from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_GENERIC_ERROR = (
    "Apologies — something went wrong on my end. Could you please try again, "
    "or contact our support team for assistance."
)


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

        try:
            from kisna_chatbot.processors.service_list import build_complaint_flow_bot_response
            
            data["bot_response"] = [build_complaint_flow_bot_response()]
            user_profile["service_selected"] = "complaint"
            
            logger.info(
                "Routing return/refund request to complaint form",
                extra={"phone_number": phone_number, "client_id": client_id},
            )
            return data
        except Exception as e:
            logger.exception(
                "Failed to route return/refund complaint to form",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
