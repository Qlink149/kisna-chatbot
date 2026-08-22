"""AI layer (OpenAI)."""

from kisna_chatbot.ai.config import get_public_config, resolve_provider
from kisna_chatbot.ai.types import AgentName, ProviderName

__all__ = [
    "AgentName",
    "ProviderName",
    "complete_chat",
    "get_chat_provider",
    "get_public_config",
    "resolve_provider",
    "run_openai_general_agent",
    "run_general_agent",
]


def __getattr__(name: str):
    if name == "complete_chat":
        from kisna_chatbot.ai.factory import complete_chat

        return complete_chat
    if name == "get_chat_provider":
        from kisna_chatbot.ai.factory import get_chat_provider

        return get_chat_provider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def run_openai_general_agent(*args, **kwargs):
    from kisna_chatbot.ai.openai_responses import run_openai_general_agent as _run

    return await _run(*args, **kwargs)


async def run_general_agent(
    *,
    phone_number: str,
    client_id: str,
    username: str,
    user_query: str,
    chat_history_str: str,
    language: str | None = None,
):
    """Run GeneralAgent on OpenAI Responses."""
    return await run_openai_general_agent(
        phone_number=phone_number,
        client_id=client_id,
        username=username,
        user_query=user_query,
        chat_history_str=chat_history_str,
        language=language,
    )
