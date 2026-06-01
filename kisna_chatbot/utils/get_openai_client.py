"""
OpenAI async client for Responses API (GeneralAgent on OpenAI only).

Deprecated for new code: use kisna_chatbot.ai.openai_responses or run_general_agent.
"""

from openai import AsyncOpenAI

from kisna_chatbot.utils.env_load import openai_api_key

_client: AsyncOpenAI | None = None


def get_openai_client() -> AsyncOpenAI:
    """Return shared AsyncOpenAI client; requires OPENAI_API_KEY when called."""
    global _client
    if _client is None:
        if not openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required for OpenAI GeneralAgent "
                "(set AI_PROVIDER_GENERAL=groq to use Groq only)."
            )
        _client = AsyncOpenAI(api_key=openai_api_key)
    return _client


# Backward-compatible name for legacy imports (may be None until first use).
openai_client: AsyncOpenAI | None = (
    AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None
)
