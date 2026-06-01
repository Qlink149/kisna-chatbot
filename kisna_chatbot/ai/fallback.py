"""Provider fallback on transient failures."""

from openai import APIConnectionError, APITimeoutError, RateLimitError

from kisna_chatbot.ai.base import ChatProvider
from kisna_chatbot.ai.types import CompletionRequest, CompletionResult


def is_transient_error(exc: Exception) -> bool:
    return isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError))


class FallbackChatProvider:
    """Try primary provider, then fallback on transient errors."""

    def __init__(self, primary: ChatProvider, fallback: ChatProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider_name = primary.provider_name
        self._model = primary.model

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        try:
            return await self._primary.complete(request)
        except Exception as primary_exc:
            if not is_transient_error(primary_exc):
                raise
            if self._primary.provider_name == self._fallback.provider_name:
                raise
            result = await self._fallback.complete(request)
            result.fallback_used = True
            return result
