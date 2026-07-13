from fastapi import APIRouter, HTTPException, Query

from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.message_trace import get_message_trace

router = APIRouter(prefix="/message-trace", tags=["System - Message Trace"])


@router.get("/{request_id}")
def fetch_message_trace(
    request_id: str,
    client_id: str = Query("kisna", description="Tenant client id"),
):
    try:
        doc = get_message_trace(request_id, client_id=client_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Trace not found")
        return doc
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to fetch message trace",
            extra={"request_id": request_id, "client_id": client_id},
        )
        raise HTTPException(status_code=500, detail="Failed to fetch message trace")
