from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger


class ProductSearchAgent(Processor):
    """Stub product search agent until catalog search is implemented."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        user_profile = data.get("user_profile", {})
        return (
            data.get("classified_category") == "product_search"
            or user_profile.get("service_selected") == SL.PRODUCT_SEARCH.value
        )

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        if not self.should_run(data):
            return data

        logger.info(
            "Product search agent processing",
            extra={"phone_number": phone_number},
        )
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    "Tell me what you're looking for — e.g. *gold ring*, "
                    "*diamond necklace*, or *gold bangles* — and I'll find options for you."
                ),
            }
        ]
        return data
