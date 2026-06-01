"""OpenAI chat completions provider."""

from kisna_chatbot.ai.base import OpenAICompatibleChatProvider
from kisna_chatbot.ai.config import get_ai_settings
from kisna_chatbot.ai.types import ProviderName


def create_openai_chat_provider(model: str | None = None) -> OpenAICompatibleChatProvider:
    settings = get_ai_settings()
    return OpenAICompatibleChatProvider(
        provider_name=ProviderName.OPENAI,
        api_key=settings["openai_api_key"],
        model=model or settings["openai_chat_model"],
    )
