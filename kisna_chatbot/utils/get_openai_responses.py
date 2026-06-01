"""
Deprecated: use kisna_chatbot.ai.complete_chat instead.

Thin shim for backward compatibility.
"""

import warnings

from kisna_chatbot.ai import complete_chat
from kisna_chatbot.ai.types import AgentName


async def get_openai_responses(
    agent_name: str,
    model: str,
    instruction: str,
    messages: list,
    tools: list | None = None,
    max_output_tokens: int = 1024,
) -> str:
    """
    Send a Chat Completions request via the configured AI provider.

    Deprecated: prefer ``kisna_chatbot.ai.complete_chat``.
    """
    warnings.warn(
        "get_openai_responses is deprecated; use kisna_chatbot.ai.complete_chat",
        DeprecationWarning,
        stacklevel=2,
    )
    agent = AgentName.CLASSIFIER
    if "general" in agent_name.lower():
        agent = AgentName.GENERAL

    return await complete_chat(
        agent=agent,
        agent_display_name=agent_name,
        instruction=instruction,
        messages=messages,
        tools=tools,
        max_output_tokens=max_output_tokens,
    )
