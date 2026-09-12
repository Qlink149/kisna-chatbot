import asyncio
import json
import mimetypes
import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from kisna_chatbot.database.db_utils import (
    get_takeover_status,
    get_user_by_phone,
    resolve_live_agent,
    save_agent_message,
    set_takeover,
)
from kisna_chatbot.routes.dependencies.system_dependencies import verify_session
from kisna_chatbot.utils import media_store
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.pubsub import pubsub
from kisna_chatbot.whatsapp_functions.media.send_audio_message import send_audio_message
from kisna_chatbot.whatsapp_functions.media.send_document_message import send_file_message
from kisna_chatbot.whatsapp_functions.media.send_image_message import send_image_message
from kisna_chatbot.whatsapp_functions.media.send_video_message import send_video_message
from kisna_chatbot.whatsapp_functions.send_text_message import send_text_message
from kisna_chatbot.database.collections import users
from kisna_chatbot.processors.service_list import build_rating_prompt_response

# stream_router: no router-level auth — stream validates via the session cookie itself
stream_router = APIRouter(prefix="/conversation", tags=["System - Conversation"])
router = APIRouter(prefix="/conversation", tags=["System - Conversation"])

TAKEOVER_MESSAGE = "You are now connected to a live support agent. Please hold on."
RELEASE_MESSAGE = "You have been reconnected to our AI assistant. How can I help you?"

# Mime allowlist per WhatsApp media kind an agent can send from the dashboard.
_MIME_TO_KIND = {
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "audio/ogg": "audio",
    "audio/mpeg": "audio",
    "audio/aac": "audio",
    "audio/mp4": "audio",
    "video/mp4": "video",
    "video/3gpp": "video",
    "application/pdf": "document",
    "application/msword": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "application/vnd.ms-excel": "document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "document",
    "application/vnd.ms-powerpoint": "document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "document",
    "text/plain": "document",
    "text/csv": "document",
}
_MEDIA_LABEL = {"image": "Image", "audio": "Voice note", "video": "Video", "document": "Document"}


def _kind_for_mime(mime: str) -> str | None:
    return _MIME_TO_KIND.get((mime or "").split(";")[0].strip().lower())


def _agent_media_label(kind: str, caption: str | None, filename: str) -> str:
    if kind == "document":
        return f"[Document] {filename}".strip()
    label = f"[{_MEDIA_LABEL[kind]}]"
    return f"{label} {caption}" if caption else label


class SendMessageRequest(BaseModel):
    message: str


# ── SSE Stream ────────────────────────────────────────────────────────────────

@stream_router.get("/{phone_number}/stream")
async def stream(phone_number: str, _: dict = Depends(verify_session)):
    """Open an SSE connection for a conversation. Auth via the session cookie."""
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

        # Only "takeover" — the dashboard refetches history on it, which already
        # picks up the message save_agent_message just persisted. Publishing
        # "agent_message" here too made the banner appear twice in the chat.
        await pubsub.publish(phone_number, {"type": "takeover", "phone_number": phone_number})

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
        saved_ts = save_agent_message(phone_number, body.message)

        await pubsub.publish(
            phone_number,
            {
                "type": "agent_message",
                "content": body.message,
                "timestamp": saved_ts,
            },
        )

        logger.info("Agent message sent", extra={"phone_number": phone_number})
        return {"success": True}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to send agent message", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to send message")


# ── Send media ────────────────────────────────────────────────────────────────

@router.post("/{phone_number}/send-media")
async def send_media(
    phone_number: str,
    file: UploadFile = File(...),
    caption: str | None = Form(None),
):
    """Send an image/audio/video/document from a live agent to the user.

    Same auth (dashboard session or system API key, mounted on `router`), same
    takeover + 24h-window guards as `send_message` — a live agent can send
    media under exactly the rules they can send text.
    """
    try:
        user = get_user_by_phone(phone_number)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        takeover_status = get_takeover_status(phone_number)
        if not takeover_status or not takeover_status.get("active"):
            raise HTTPException(status_code=400, detail="No active takeover for this user")

        updated_at = user.get("updated_at", 0)
        if time.time() - updated_at > 86400:
            raise HTTPException(
                status_code=400,
                detail="WhatsApp 24-hour conversation window has expired",
            )

        if not media_store.is_configured():
            raise HTTPException(status_code=503, detail="Media storage is not configured")

        mime = (file.content_type or "").split(";")[0].strip().lower()
        kind = _kind_for_mime(mime)
        if not kind:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {mime or 'unknown'}")

        # UploadFile.size (when the client sends Content-Length) rejects an
        # oversized upload before it's read into memory; the length check
        # below is the authoritative guard either way.
        if file.size is not None and file.size > media_store.max_bytes():
            raise HTTPException(status_code=400, detail="File exceeds the 20 MB limit")

        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Empty file")
        if len(data) > media_store.max_bytes():
            raise HTTPException(status_code=400, detail="File exceeds the 20 MB limit")

        ext = mimetypes.guess_extension(mime) or ""
        key = f"kisna/outbound/{uuid.uuid4().hex}{ext}"
        uploaded = await asyncio.to_thread(media_store.put_bytes, data, key, mime)
        if not uploaded:
            raise HTTPException(status_code=502, detail="Failed to store the file")

        signed = media_store.presign_get(key, 900)
        if not signed:
            raise HTTPException(status_code=502, detail="Failed to prepare the file for sending")

        filename = file.filename or "file"
        send_kwargs: dict = {"url": signed}
        if kind == "image":
            send_kwargs["caption"] = caption or ""
            result = await asyncio.to_thread(send_image_message, phone_number, send_kwargs)
        elif kind == "document":
            send_kwargs["filename"] = filename
            send_kwargs["caption"] = caption or ""
            result = await asyncio.to_thread(send_file_message, phone_number, send_kwargs)
        elif kind == "video":
            send_kwargs["caption"] = caption or ""
            result = await asyncio.to_thread(send_video_message, phone_number, send_kwargs)
        else:  # audio -- no caption field on Gupshup's audio type
            result = await asyncio.to_thread(send_audio_message, phone_number, send_kwargs)

        if isinstance(result, dict) and str(result.get("status", "")).lower() in (
            "error",
            "failed",
            "failure",
        ):
            raise HTTPException(status_code=502, detail="WhatsApp rejected the media")

        media = {
            "kind": kind,
            "b2_key": key,
            "mime": mime,
            "filename": filename if kind == "document" else None,
            "caption": caption or None,
            "size": len(data),
            "sha256": None,
            "source": "agent",
        }
        content = _agent_media_label(kind, caption, filename)
        saved_ts = save_agent_message(phone_number, content, media=media)

        await pubsub.publish(
            phone_number,
            {
                "type": "agent_message",
                "content": content,
                "timestamp": saved_ts,
                "media": {**media, "url": signed},
            },
        )

        logger.info("Agent media sent", extra={"phone_number": phone_number, "kind": kind})
        return {"success": True, "media": {**media, "url": signed}}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to send agent media", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to send media")


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
