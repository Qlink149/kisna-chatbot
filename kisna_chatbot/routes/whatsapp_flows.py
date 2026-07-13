"""Public WhatsApp Flow data-exchange endpoint (Meta / Gupshup)."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from kisna_chatbot.processors.flow_data_exchange import build_flow_response
from kisna_chatbot.utils.flow_endpoint_crypto import (
    FlowEndpointCryptoError,
    decrypt_request,
    encrypt_response,
)
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(tags=["WhatsApp Flows"])


@router.post("/whatsapp/flows/data-exchange")
async def whatsapp_flow_data_exchange(request: Request):
    """
    Encrypted data_exchange endpoint for callback / video-call Flows.

    Meta sends:
      { encrypted_flow_data, encrypted_aes_key, initial_vector }

    Response must be encrypted base64 as text/plain.
    Decryption failures → HTTP 421 (client re-downloads public key).
    """
    try:
        body = await request.json()
    except Exception:
        logger.warning("Flow endpoint: invalid JSON body")
        return Response(status_code=400)

    try:
        decrypted, aes_key, iv = decrypt_request(
            body.get("encrypted_flow_data", ""),
            body.get("encrypted_aes_key", ""),
            body.get("initial_vector", ""),
        )
    except FlowEndpointCryptoError as e:
        logger.warning("Flow endpoint decrypt failed", extra={"error": str(e)})
        return Response(status_code=421)

    try:
        clear = build_flow_response(decrypted)
        encrypted = encrypt_response(clear, aes_key, iv)
        return PlainTextResponse(content=encrypted, media_type="text/plain")
    except Exception:
        logger.exception("Flow endpoint handler failed")
        return Response(status_code=500)
