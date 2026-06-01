"""Groq chat completions provider (OpenAI-compatible endpoint)."""

from kisna_chatbot.ai.base import OpenAICompatibleChatProvider
from kisna_chatbot.ai.config import get_ai_settings
from kisna_chatbot.ai.types import ProviderName


def create_groq_chat_provider(model: str | None = None) -> OpenAICompatibleChatProvider:
    settings = get_ai_settings()
    return OpenAICompatibleChatProvider(
        provider_name=ProviderName.GROQ,
        api_key=settings["groq_api_key"],
        model=model or settings["groq_chat_model"],
        base_url=settings["groq_base_url"],
    )
