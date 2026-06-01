from kisna_chatbot.ai import run_general_agent
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_HANDOFF_MESSAGE = "Connecting you to our design consultant..."
_GENERIC_ERROR = (
    "Sorry, I couldn't process your question right now. Please try again in a moment."
)


class GeneralAgent(Processor):
    """Handles brand questions, design advice, and policy/FAQ queries for Kisna."""

    def should_run(self, data: dict) -> bool:
        return "bot_response" not in data

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        user_profile = data["user_profile"]
        client_id = data.get("client_id", "kisna")
        username = user_profile.get("username") or user_profile.get(
            "whatsapp_username", "Customer"
        )

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
            if "text" not in data.get("messages", {}):
                return data

            user_query = data["messages"]["text"]["body"]

            chat_history = user_profile.get("chat_history", [])[-10:]
            chat_history_str = "\n".join(
                f"{c.get('role', '').capitalize()}: {c.get('content', '')}"
                for c in chat_history
            )

            result = await run_general_agent(
                phone_number=phone_number,
                client_id=client_id,
                username=username,
                user_query=user_query,
                chat_history_str=chat_history_str,
            )

            logger.info(
                "GeneralAgent completed",
                extra={
                    "phone_number": phone_number,
                    "provider": result.provider.value,
                    "model": result.model,
                    "latency_ms": result.latency_ms,
                    "fallback_used": getattr(result, "fallback_used", False),
                },
            )

            if result.live_agent_requested:
                data["bot_response"] = [{"type": "text", "text": _HANDOFF_MESSAGE}]
            elif result.message_text:
                data["bot_response"] = [
                    {"type": "text", "text": result.message_text}
                ]
            else:
                data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]

            user_profile["service_selected"] = ""
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in GeneralAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
