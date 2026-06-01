"""AI usage logging to MongoDB."""

import time

from kisna_chatbot.ai.pricing import estimate_cost_usd
from kisna_chatbot.ai.types import UsageRecord
from kisna_chatbot.utils.logger_config import logger


def record_usage(record: UsageRecord) -> None:
    """
    Persist usage record (best-effort; never raises to caller).

    Skips insert if ai_usage_logs collection is unavailable.
    """
    try:
        from kisna_chatbot.database.collections import ai_usage_logs

        ai_usage_logs.insert_one(
            {
                "client_id": record.client_id,
                "agent": record.agent,
                "provider": record.provider,
                "model": record.model,
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": record.completion_tokens,
                "estimated_cost_usd": record.estimated_cost_usd,
                "latency_ms": record.latency_ms,
                "success": record.success,
                "phone_number": record.phone_number,
                "error": record.error,
                "fallback_used": record.fallback_used,
                "created_at": int(time.time()),
            }
        )
    except Exception as e:
        logger.warning(
            "Failed to record AI usage",
            extra={"agent": record.agent, "error": str(e)},
        )


def build_usage_record(
    *,
    client_id: str,
    agent: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    success: bool,
    phone_number: str | None = None,
    error: str | None = None,
    fallback_used: bool = False,
) -> UsageRecord:
    cost = estimate_cost_usd(model, prompt_tokens, completion_tokens)
    return UsageRecord(
        client_id=client_id or "kisna",
        agent=agent,
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        estimated_cost_usd=cost,
        latency_ms=latency_ms,
        success=success,
        phone_number=phone_number,
        error=error,
        fallback_used=fallback_used,
    )
