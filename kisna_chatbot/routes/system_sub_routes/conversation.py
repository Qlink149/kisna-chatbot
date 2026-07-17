import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from kisna_chatbot.database.db_utils import (
    get_takeover_status,
    get_user_by_phone,
    resolve_live_agent,
    save_agent_message,
    set_takeover,
)
from kisna_chatbot.routes.dependencies.system_dependencies import verify_token_query
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.pubsub import pubsub
from kisna_chatbot.whatsapp_functions.send_text_message import send_text_message
from kisna_chatbot.database.collections import users
from kisna_chatbot.processors.service_list import build_rating_prompt_response

# stream_router: no router-level auth — stream validates via ?token= query param itself
stream_router = APIRouter(prefix="/conversation", tags=["System - Conversation"])
router = APIRouter(prefix="/conversation", tags=["System - Conversation"])

TAKEOVER_MESSAGE = "You are now connected to a live support agent. Please hold on."
RELEASE_MESSAGE = "You have been reconnected to our AI assistant. How can I help you?"


class SendMessageRequest(BaseModel):
    message: str


# ── SSE Stream ────────────────────────────────────────────────────────────────

@stream_router.get("/{phone_number}/stream")
async def stream(phone_number: str, _: dict = Depends(verify_token_query)):
    """Open an SSE connection for a conversation. Auth via ?token= query param."""
    queue = pubsub.subscribe(phone_number)

    async def generator():
        try:
            yield f"data: {json.dumps({'type': 'connected', 'phone_number': phone_number})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"  # keep-alive for nginx 60s idle limit
        finally:
            pubsub.unsubscribe(phone_number, queue)

    return StreamingResponse(generator(), media_type="text/event-stream")


# ── Takeover ──────────────────────────────────────────────────────────────────

@router.post("/{phone_number}/takeover")
async def takeover(phone_number: str):
    """Hand the conversation to a human agent."""
    try:
        user = get_user_by_phone(phone_number)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        set_takeover(phone_number, active=True)

        send_text_message(
            phone_number=phone_number,
            bot_response={"type": "text", "text": TAKEOVER_MESSAGE},
        )
        save_agent_message(phone_number, TAKEOVER_MESSAGE)

        await pubsub.publish(phone_number, {"type": "takeover", "phone_number": phone_number})
        await pubsub.publish(phone_number, {"type": "agent_message", "content": TAKEOVER_MESSAGE})

        logger.info("Takeover initiated", extra={"phone_number": phone_number})
        return {"success": True, "message": "Takeover active"}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to initiate takeover", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to initiate takeover")


# ── Send ──────────────────────────────────────────────────────────────────────

@router.post("/{phone_number}/send")
async def send_message(phone_number: str, body: SendMessageRequest):
    """Send a message from the human agent to the user."""
    try:
        user = get_user_by_phone(phone_number)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        takeover_status = get_takeover_status(phone_number)
        if not takeover_status or not takeover_status.get("active"):
            raise HTTPException(status_code=400, detail="No active takeover for this user")

        # Enforce WhatsApp 24-hour conversation window
        updated_at = user.get("updated_at", 0)
        if time.time() - updated_at > 86400:
            raise HTTPException(
                status_code=400,
                detail="WhatsApp 24-hour conversation window has expired",
            )

        send_text_message(
            phone_number=phone_number,
            bot_response={"type": "text", "text": body.message},
        )
        save_agent_message(phone_number, body.message)

        await pubsub.publish(
            phone_number,
            {"type": "agent_message", "content": body.message},
        )

        logger.info("Agent message sent", extra={"phone_number": phone_number})
        return {"success": True}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to send agent message", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to send message")


# ── Release ───────────────────────────────────────────────────────────────────

@router.post("/{phone_number}/release")
async def release(phone_number: str):
    """Release the conversation back to the AI bot."""
    try:
        user = get_user_by_phone(phone_number)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        set_takeover(phone_number, active=False)

        send_text_message(
            phone_number=phone_number,
            bot_response={"type": "text", "text": RELEASE_MESSAGE},
        )
        save_agent_message(phone_number, RELEASE_MESSAGE)

        rating_prompt = build_rating_prompt_response()
        send_text_message(
            phone_number=phone_number,
            bot_response=rating_prompt,
        )
        save_agent_message(phone_number, rating_prompt["text"])
        users.update_one(
            {"phone_number": phone_number},
            {"$set": {"awaiting_rating": True, "updated_at": int(time.time())}},
        )

        await pubsub.publish(phone_number, {"type": "release", "phone_number": phone_number})

        logger.info("Takeover released", extra={"phone_number": phone_number})
        return {"success": True, "message": "Bot resumed"}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to release takeover", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to release takeover")


# ── Resolve Live Agent Request ────────────────────────────────────────────────

@router.post("/{phone_number}/resolve-agent")
async def resolve_agent(phone_number: str):
    """Mark a live agent request as resolved."""
    try:
        user = get_user_by_phone(phone_number)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        resolve_live_agent(phone_number)

        logger.info("Live agent request resolved", extra={"phone_number": phone_number})
        return {"success": True, "message": "Live agent request resolved"}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to resolve live agent request", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to resolve live agent request")
