from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from kisna_chatbot.database.db_utils import (
    get_all_callback_requests,
    update_callback_status,
)
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/callbacks", tags=["System - Callbacks"])


class CallbackStatusUpdate(BaseModel):
    status: str


@router.get("")
def list_callbacks(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    client_id: str = Query("kisna", description="Tenant client id"),
    status: str | None = Query(None, description="Filter by status"),
    request_type: str | None = Query(None, description="callback or video_call"),
):
    """List callback / video-call requests — sorted by created_at desc."""
    try:
        return get_all_callback_requests(
            page=page,
            limit=limit,
            client_id=client_id,
            status=status,
            request_type=request_type,
        )
    except Exception:
        logger.exception("Failed to list callback requests")
        raise HTTPException(status_code=500, detail="Failed to fetch callbacks")


@router.patch("/{request_id}")
def patch_callback_status(
    request_id: str,
    body: CallbackStatusUpdate,
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Update callback request status."""
    if body.status not in ("pending", "completed"):
        raise HTTPException(status_code=400, detail="Invalid status")
    try:
        updated = update_callback_status(request_id, body.status, client_id=client_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Request not found")
        return updated
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to patch callback status",
            extra={"request_id": request_id},
        )
        raise HTTPException(status_code=500, detail="Failed to update callback")
