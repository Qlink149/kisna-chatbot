"""Admin routes for AI provider configuration and usage."""

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from kisna_chatbot.ai import complete_chat, get_public_config
from kisna_chatbot.ai.config import refresh_ai_settings, resolve_provider
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.database.collections import ai_usage_logs
from kisna_chatbot.routes.dependencies.system_dependencies import verify_token
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/ai", tags=["AI"])


class AITestRequest(BaseModel):
    agent: Literal["classifier", "general"] = "classifier"
    message: str = Field(default="Hello", max_length=500)


@router.get("/config")
def get_ai_config(_user=Depends(verify_token)):
    """Return effective AI provider and model configuration per agent."""
    refresh_ai_settings()
    return get_public_config()


@router.post("/test")
async def test_ai_completion(body: AITestRequest, _user=Depends(verify_token)):
    """Run a one-shot completion to verify provider connectivity."""
    refresh_ai_settings()
    agent = AgentName(body.agent)

    try:
        text = await complete_chat(
            agent=agent,
            agent_display_name=f"Test {body.agent}",
            instruction="You are a test assistant. Reply briefly.",
            messages=[{"role": "user", "content": body.message}],
            max_output_tokens=128,
            client_id="kisna",
        )
        effective = resolve_provider(agent)
        return {
            "success": True,
            "provider": effective.value,
            "response_preview": text[:500],
        }
    except Exception as e:
        logger.exception("AI test failed", extra={"agent": body.agent, "error": str(e)})
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/usage")
def get_ai_usage(
    days: int = Query(7, ge=1, le=90),
    client_id: str = Query("kisna"),
    _user=Depends(verify_token),
):
    """Aggregate AI usage logs for the given period."""
    since = int(time.time()) - days * 86400
    pipeline = [
        {"$match": {"client_id": client_id, "created_at": {"$gte": since}}},
        {
            "$group": {
                "_id": {"provider": "$provider", "agent": "$agent"},
                "requests": {"$sum": 1},
                "prompt_tokens": {"$sum": "$prompt_tokens"},
                "completion_tokens": {"$sum": "$completion_tokens"},
                "estimated_cost_usd": {"$sum": "$estimated_cost_usd"},
                "errors": {
                    "$sum": {"$cond": [{"$eq": ["$success", False]}, 1, 0]}
                },
            }
        },
        {"$sort": {"_id.provider": 1, "_id.agent": 1}},
    ]

    rows = list(ai_usage_logs.aggregate(pipeline))
    totals = {
        "requests": sum(r["requests"] for r in rows),
        "prompt_tokens": sum(r["prompt_tokens"] for r in rows),
        "completion_tokens": sum(r["completion_tokens"] for r in rows),
        "estimated_cost_usd": round(
            sum(r["estimated_cost_usd"] for r in rows), 6
        ),
        "errors": sum(r["errors"] for r in rows),
    }

    return {
        "client_id": client_id,
        "days": days,
        "since_timestamp": since,
        "totals": totals,
        "by_provider_agent": [
            {
                "provider": r["_id"]["provider"],
                "agent": r["_id"]["agent"],
                "requests": r["requests"],
                "prompt_tokens": r["prompt_tokens"],
                "completion_tokens": r["completion_tokens"],
                "estimated_cost_usd": round(r["estimated_cost_usd"], 6),
                "errors": r["errors"],
            }
            for r in rows
        ],
        "note": "estimated_cost_usd is approximate based on static pricing table",
    }
