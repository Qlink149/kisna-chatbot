from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.utils.logger_config import logger

_GENERIC_ERROR = (
    "Apologies — something went wrong on my end. Could you please try again, "
    "or contact our support team for assistance."
)


class ReturnsRefundAgent(Processor):
    """Route return/refund requests into the complaint flow."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        user_profile = data.get("user_profile", {})
        if data.get("classified_category") == "returns_refund":
            return True
        return user_profile.get("service_selected") == SL.RETURNS_REFUND.value

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
            user_profile["service_selected"] = SL.COMPLAINT.value
            data["classified_category"] = "complaint"

            logger.info(
                "Routing return/refund request to complaint flow",
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
