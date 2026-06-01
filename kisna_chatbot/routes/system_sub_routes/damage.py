from fastapi import APIRouter, HTTPException, Query

from kisna_chatbot.database.db_utils import get_all_complaints, get_complaints_by_phone
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/damage", tags=["System - Damage"])


@router.get("")
def list_complaints(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """List all damage complaints — sorted by most recently created, with pagination."""
    try:
        return get_all_complaints(page=page, limit=limit, client_id=client_id)
    except Exception:
        logger.exception("Failed to list damage complaints")
        raise HTTPException(status_code=500, detail="Failed to fetch complaints")


@router.get("/{phone_number}")
def get_complaints(
    phone_number: str,
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Get all damage complaints filed by a phone number."""
    try:
        results = get_complaints_by_phone(phone_number, client_id=client_id)
        if not results:
            raise HTTPException(status_code=404, detail="No complaints found for this number")
        return {"phone_number": phone_number, "complaints": results}
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get complaints", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to fetch complaints")
