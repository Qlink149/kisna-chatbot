from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger


class AdFlowAgent(Processor):
    """Stub store locator / visit flow until Gupshup flows are wired."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        user_profile = data.get("user_profile", {})
        return user_profile.get("service_selected") == SL.AD_FLOW.value

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        if not self.should_run(data):
            return data

        logger.info(
            "Ad flow agent processing",
            extra={"phone_number": phone_number},
        )
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    "Share your pincode or city and I'll help you find the "
                    "nearest Kisna showroom."
                ),
            }
        ]
        return data
