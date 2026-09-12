"""Copy-on-receipt capture of customer-sent WhatsApp media into B2.

Gupshup puts a direct, publicly-fetchable HTTPS URL in the inbound webhook
payload (confirmed live: ``messages["image"]["url"]`` etc., no auth needed) --
but that URL is Gupshup's own, undocumented retention (~30 days). This module
downloads the bytes once and re-hosts them in our own private B2 bucket so the
dashboard has a durable reference instead of a link that eventually rots.

Runs for every inbound image/audio/video/document message, regardless of
whether a human has taken the conversation over -- an agent who takes over
later should still be able to scroll back and see what the customer sent
while the bot was handling the chat.

Every failure mode (fetch error, timeout, oversized, B2 unconfigured, upload
error) returns None and never raises: the caller falls through to exactly
today's behaviour. This can only add information, never break a turn.
"""

import asyncio
import mimetypes
import uuid

import httpx

from kisna_chatbot.utils import media_store
from kisna_chatbot.utils.logger_config import logger

_FETCH_TIMEOUT = 10.0
_MEDIA_TYPES = frozenset({"image", "audio", "video", "document"})

_EXT_FALLBACK = {
    "image": ".jpg",
    "audio": ".ogg",
    "video": ".mp4",
    "document": ".bin",
}


def _extension(mime_type: str, kind: str) -> str:
    ext = mimetypes.guess_extension((mime_type or "").split(";")[0].strip())
    return ext or _EXT_FALLBACK.get(kind, ".bin")


async def capture_inbound_media(messages: dict) -> dict | None:
    """Fetch, cap, and store one inbound media message. Returns the ``media``
    dict to persist on the chat_messages doc, or None if capture didn't
    happen (wrong type, not configured, or any failure)."""
    if not isinstance(messages, dict):
        return None
    kind = messages.get("type")
    if kind not in _MEDIA_TYPES:
        return None
    if not media_store.is_configured():
        return None

    payload = messages.get(kind) or {}
    url = payload.get("url")
    if not url:
        return None
    mime_type = payload.get("mime_type") or ""
    caption = (payload.get("caption") or "").strip() or None
    # WhatsApp documents carry a client-chosen filename; other types don't.
    filename = payload.get("filename") or None
    sha256 = payload.get("sha256") or None

    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                cap = media_store.max_bytes()
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > cap:
                        logger.warning(
                            "Inbound media exceeds cap, skipping capture",
                            extra={"kind": kind, "cap_bytes": cap},
                        )
                        return None
                    chunks.append(chunk)
                data = b"".join(chunks)
    except httpx.TimeoutException:
        logger.warning("Inbound media fetch timed out", extra={"kind": kind})
        return None
    except httpx.HTTPStatusError as e:
        logger.warning(
            "Inbound media fetch failed",
            extra={"kind": kind, "status_code": e.response.status_code},
        )
        return None
    except Exception:
        logger.exception("Inbound media fetch failed unexpectedly", extra={"kind": kind})
        return None

    if not data:
        return None

    key = f"kisna/inbound/{uuid.uuid4().hex}{_extension(mime_type, kind)}"
    uploaded = await asyncio.to_thread(media_store.put_bytes, data, key, mime_type)
    if not uploaded:
        return None

    return {
        "kind": kind,
        "b2_key": key,
        "mime": mime_type or None,
        "filename": filename,
        "caption": caption,
        "size": len(data),
        "sha256": sha256,
        "source": "inbound",
    }
