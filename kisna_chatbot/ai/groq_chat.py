"""Groq chat completions provider with multi-key rate-limit rotation."""

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    BadRequestError,
    RateLimitError,
)

from kisna_chatbot.ai.base import (
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    RETRY_BACKOFF_SECONDS,
    ChatProvider,
    _extract_usage,
    _is_invalid_model_error,
)
from kisna_chatbot.ai.config import get_ai_settings
from kisna_chatbot.ai.groq_keys import GroqKeyPool, parse_groq_api_keys
from kisna_chatbot.ai.types import CompletionRequest, CompletionResult, ProviderName
from kisna_chatbot.utils.logger_config import log_event, logger

import asyncio
import time


class GroqChatProvider(ChatProvider):
    """Groq chat provider with optional multi-key rotation on 429/rate limits."""

    provider_name = ProviderName.GROQ

    def __init__(
        self,
        *,
        model: str,
        keys: list[str],
        base_url: str,
        rotate_on_rate_limit: bool = True,
    ) -> None:
        if not keys:
            raise ValueError("Groq API key is not configured")
        self._model = model
        self._base_url = base_url
        self._key_pool = GroqKeyPool(keys)
        self._rotate_on_rate_limit = rotate_on_rate_limit
        self._clients = {
            i: AsyncOpenAI(
                api_key=key,
                base_url=base_url,
                timeout=DEFAULT_TIMEOUT,
            )
            for i, key in enumerate(keys)
        }
        self._client = self._clients[self._key_pool.current_index]

    @property
    def model(self) -> str:
        return self._model

    def _api_key_missing_message(self) -> str:
        return "Groq API key is not configured"

    def _switch_to_pool_index(self, index: int) -> None:
        self._client = self._clients[index]

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
                "groq_key_count": self._key_pool.size,
            },
        )

        request_kwargs: dict = {
            "model": self._model,
            "messages": api_messages,
            "max_tokens": request.max_output_tokens,
        }
        if request.tools:
            request_kwargs["tools"] = request.tools

        last_error: Exception | None = None
        keys_tried_this_attempt = 0

        for attempt in range(1, MAX_RETRIES + 1):
            keys_tried_this_attempt = 0
            while keys_tried_this_attempt < self._key_pool.size:
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
                            "groq_key_index": self._key_pool.current_index,
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
                except RateLimitError as e:
                    last_error = e
                    keys_tried_this_attempt += 1
                    if (
                        self._rotate_on_rate_limit
                        and self._key_pool.size > 1
                        and keys_tried_this_attempt < self._key_pool.size
                    ):
                        new_index, total = self._key_pool.rotate()
                        self._switch_to_pool_index(new_index)
                        log_event(
                            "groq_key_rotate",
                            "Rotating Groq API key after rate limit",
                            level="warning",
                            groq_key_index=new_index,
                            groq_key_count=total,
                            agent=request.agent.value,
                        )
                        continue
                    logger.warning(
                        "Groq rate limit",
                        extra={
                            "provider": self.provider_name.value,
                            "attempt": attempt,
                            "error": str(e),
                        },
                    )
                    break
                except (APITimeoutError, APIConnectionError) as e:
                    last_error = e
                    logger.warning(
                        "Transient Groq API error, retrying",
                        extra={
                            "provider": self.provider_name.value,
                            "attempt": attempt,
                            "error": str(e),
                        },
                    )
                    break
                except BadRequestError as e:
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

            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)

        raise last_error or RuntimeError("Groq chat completion failed after retries")


def create_groq_chat_provider(model: str | None = None) -> GroqChatProvider:
    settings = get_ai_settings()
    keys = settings["groq_api_keys"]
    if not keys:
        raise ValueError("Groq API key is not configured")
    return GroqChatProvider(
        model=model or settings["groq_chat_model"],
        keys=keys,
        base_url=settings["groq_base_url"],
        rotate_on_rate_limit=settings["groq_rate_limit_retry_keys"],
    )
