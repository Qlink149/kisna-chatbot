"""Provider factory and high-level completion API."""

import time

from kisna_chatbot.ai.config import (
    get_ai_settings,
    resolve_max_tokens,
    resolve_model,
    resolve_provider,
)
from kisna_chatbot.ai.fallback import FallbackChatProvider
from kisna_chatbot.ai.groq_chat import create_groq_chat_provider
from kisna_chatbot.ai.openai_chat import create_openai_chat_provider
from kisna_chatbot.ai.types import (
    AgentName,
    CompletionRequest,
    CompletionResult,
    ProviderName,
)
from kisna_chatbot.ai.usage import build_usage_record, record_usage
from kisna_chatbot.utils.logger_config import logger


def _create_provider(provider: ProviderName, model: str | None = None):
    if provider == ProviderName.GROQ:
        return create_groq_chat_provider(model)
    return create_openai_chat_provider(model)


def get_chat_provider(agent: AgentName):
    """Return chat provider for agent, with optional fallback wrapper."""
    settings = get_ai_settings()
    primary_name = resolve_provider(agent)
    model = resolve_model(primary_name)
    primary = _create_provider(primary_name, model)

    if not settings["fallback_enabled"]:
        return primary

    fallback_name = settings["fallback_provider"]
    if fallback_name == primary_name:
        return primary

    fallback = _create_provider(fallback_name, resolve_model(fallback_name))
    return FallbackChatProvider(primary, fallback)


async def complete_chat(
    *,
    agent: AgentName,
    instruction: str,
    messages: list,
    agent_display_name: str | None = None,
    tools: list | None = None,
    max_output_tokens: int | None = None,
    phone_number: str | None = None,
    client_id: str | None = None,
) -> str:
    """
    Run a chat completion for the given agent using configured provider(s).

    Returns assistant message text.
    """
    provider = get_chat_provider(agent)
    request = CompletionRequest(
        agent=agent,
        agent_display_name=agent_display_name or agent.value,
        instruction=instruction,
        messages=messages,
        tools=tools,
        max_output_tokens=max_output_tokens or resolve_max_tokens(agent),
        phone_number=phone_number,
        client_id=client_id,
    )

    success = True
    error_msg: str | None = None
    result: CompletionResult | None = None

    try:
        result = await provider.complete(request)
        return result.text
    except Exception as e:
        success = False
        error_msg = str(e)
        logger.exception(
            "complete_chat failed",
            extra={"agent": agent.value, "error": error_msg},
        )
        raise
    finally:
        if result is not None:
            record_usage(
                build_usage_record(
                    client_id=client_id or "kisna",
                    agent=agent.value,
                    provider=result.provider.value,
                    model=result.model,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    latency_ms=result.latency_ms,
                    success=success,
                    phone_number=phone_number,
                    error=error_msg,
                    fallback_used=result.fallback_used,
                )
            )
