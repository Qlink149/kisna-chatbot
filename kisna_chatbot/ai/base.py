"""Base chat provider with shared retry logic."""

import asyncio
import json
import re
import time
from abc import ABC, abstractmethod

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)

from kisna_chatbot.ai.types import CompletionRequest, CompletionResult, ProviderName
from kisna_chatbot.utils.logger_config import logger

DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1.0


# Newer OpenAI models reject "max_tokens" and require "max_completion_tokens".
# Two mechanisms, deliberately: the pattern below avoids a cold-start round
# trip for the families we know, and this set learns at runtime so a model
# released after this code was written still works without a code change.
_MAX_COMPLETION_TOKENS_MODELS: set[str] = set()
# Pre-seeded so the very first call of a process does not have to spend a
# round trip discovering this. Without it, several concurrent cold-start calls
# each burn an attempt on the same 400 and one of them can exhaust its retries.
# The runtime learning above still covers anything this pattern misses.
_LIKELY_NEEDS_MAX_COMPLETION_TOKENS = re.compile(r"^(?:gpt-[5-9]|o[1-9])", re.I)


def _is_token_param_error(exc: BadRequestError) -> bool:
    message = str(exc).lower()
    return "max_tokens" in message and (
        "max_completion_tokens" in message
        or "not supported" in message
        or "unsupported" in message
    )


def _is_invalid_model_error(exc: BadRequestError) -> bool:
    # Must be checked AFTER _is_token_param_error: OpenAI reports the token
    # parameter problem as an invalid_request_error mentioning the model, which
    # matched "invalid" + "model" here and surfaced as a bogus
    # "Invalid model 'gpt-5.6-luna'" instead of a fixable parameter mismatch.
    message = str(exc).lower()
    return "model" in message and (
        "not found" in message
        or "does not exist" in message
        or "invalid" in message
    )


def _extract_usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    if not usage:
        return 0, 0
    return (
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
    )


class ChatProvider(ABC):
    """Abstract async chat completion provider."""

    provider_name: ProviderName

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self._client = client
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @abstractmethod
    def _api_key_missing_message(self) -> str:
        pass

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        start = time.perf_counter()
        api_messages = [
            {"role": "system", "content": request.instruction},
            *request.messages,
        ]

        logger.info(
            "Chat completion request",
            extra={
                "agent": request.agent.value,
                "provider": self.provider_name.value,
                "model": self._model,
            },
        )

        token_param = (
            "max_completion_tokens"
            if (
                self._model in _MAX_COMPLETION_TOKENS_MODELS
                or _LIKELY_NEEDS_MAX_COMPLETION_TOKENS.match(self._model or "")
            )
            else "max_tokens"
        )
        request_kwargs: dict = {
            "model": self._model,
            "messages": api_messages,
            token_param: request.max_output_tokens,
        }
        if request.tools:
            request_kwargs["tools"] = request.tools

        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = await self._client.chat.completions.create(
                    **request_kwargs
                )
                text = (response.choices[0].message.content or "").strip()
                prompt_tokens, completion_tokens = _extract_usage(response)
                latency_ms = int((time.perf_counter() - start) * 1000)

                logger.info(
                    "Chat completion success",
                    extra={
                        "agent": request.agent.value,
                        "provider": self.provider_name.value,
                        "model": self._model,
                        "latency_ms": latency_ms,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                    },
                )

                return CompletionResult(
                    text=text,
                    provider=self.provider_name,
                    model=self._model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                )
            except (RateLimitError, APITimeoutError, APIConnectionError) as e:
                last_error = e
                logger.warning(
                    "Transient chat API error, retrying",
                    extra={
                        "provider": self.provider_name.value,
                        "attempt": attempt,
                        "error": str(e),
                    },
                )
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except BadRequestError as e:
                if _is_token_param_error(e) and "max_tokens" in request_kwargs:
                    _MAX_COMPLETION_TOKENS_MODELS.add(self._model)
                    request_kwargs["max_completion_tokens"] = request_kwargs.pop(
                        "max_tokens"
                    )
                    logger.info(
                        "Model requires max_completion_tokens — retrying",
                        extra={"model": self._model},
                    )
                    continue
                if _is_invalid_model_error(e):
                    raise ValueError(
                        f"Invalid model '{self._model}' for {request.agent.value}"
                    ) from e
                raise
            except Exception as e:
                logger.error(
                    "Chat completion error",
                    extra={
                        "provider": self.provider_name.value,
                        "error": str(e),
                    },
                )
                raise

        raise last_error or RuntimeError("Chat completion failed after retries")


class OpenAICompatibleChatProvider(ChatProvider):
    """Chat provider using OpenAI SDK client."""

    def __init__(
        self,
        *,
        provider_name: ProviderName,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        if not api_key:
            raise ValueError(f"{provider_name.value} API key is not configured")
        kwargs: dict = {"api_key": api_key, "timeout": DEFAULT_TIMEOUT}
        if base_url:
            kwargs["base_url"] = base_url
        client = AsyncOpenAI(**kwargs)
        super().__init__(client, model)
        self.provider_name = provider_name

    def _api_key_missing_message(self) -> str:
        return f"{self.provider_name.value} API key is not configured"
