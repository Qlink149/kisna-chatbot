import time
from datetime import datetime

from kisna_chatbot.database.collections import users
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger


class UserRegistration(Processor):
    """Processor class for getting or creating user profile."""

    def should_run(self, data: dict) -> bool:
        """Determine whether the processor should run based on the input data."""
        return True

    def check_user_profile(
        self,
        phone_number: str,
        whatsapp_username: str = "",
        client_id: str = "kisna",
    ) -> dict:
        """Get or create user profile based on phone number and client."""
        try:
            profile = users.find_one(
                {"phone_number": phone_number, "client_id": client_id}
            )
            if profile:
                return profile
            return {
                "username": whatsapp_username,
                "phone_number": phone_number,
                "client_id": client_id,
                "service_selected": "",
                "chat_history": [],
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
                "pre_orders": [],
                "shown_product_ids": [],
            }
        except Exception as e:
            logger.exception(
                "Failed to check user profile",
                extra={
                    "phone_number": phone_number,
                    "client_id": client_id,
                    "error": str(e),
                },
            )
            raise

    async def process(self, data: dict) -> dict:
        """Process input data for user registration."""
        phone_number = data["phone_number"]
        whatsapp_username = data.get("whatsapp_username", "")
        client_id = data.get("client_id", "kisna")

        logger.info(
            "Request received to register user",
            extra={"phone_number": phone_number, "client_id": client_id},
        )

        response = self.check_user_profile(
            phone_number=phone_number,
            whatsapp_username=whatsapp_username,
            client_id=client_id,
        )
        data["user_profile"] = response

        return data
