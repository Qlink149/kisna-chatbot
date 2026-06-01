from fastapi import APIRouter, HTTPException, Query
from kisna_chatbot.database.db_utils import get_user_by_phone
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/chat-history", tags=["System - Chat History"])


@router.get("/{phone_number}")
def get_chat_history(
    phone_number: str,
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Return chat history, created_at, and updated_at for a user by phone number."""
    try:
        user = get_user_by_phone(phone_number, client_id=client_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "phone_number": phone_number,
            "chat_history": user.get("chat_history", []),
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get chat history", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to fetch chat history")
