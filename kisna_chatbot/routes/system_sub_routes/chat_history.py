from fastapi import APIRouter, HTTPException, Query

from kisna_chatbot.database.db_utils import get_paginated_chat_messages, get_user_by_phone
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/chat-history", tags=["System - Chat History"])


@router.get("/{phone_number}")
def get_chat_history(
    phone_number: str,
    client_id: str = Query("kisna", description="Tenant client id"),
    before: int | None = Query(
        None, description="Unix timestamp cursor — return messages before this ts"
    ),
    before_id: str | None = Query(
        None, description="Optional _id tiebreak for same-timestamp cursor"
    ),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Paginated chat history from chat_messages.

    Without `before`: latest `limit` messages (oldest→newest in response).
    With `before`: the `limit` messages immediately before that timestamp.
    """
    try:
        user = get_user_by_phone(phone_number, client_id=client_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        page = get_paginated_chat_messages(
            phone_number,
            client_id=client_id,
            before=before,
            before_id=before_id,
            limit=limit,
        )
        # Fallback: if chat_messages is empty (pre-migration), use embedded history
        if not page["messages"] and before is None:
            embedded = user.get("chat_history") or []
            page = {
                "phone_number": phone_number,
                "messages": embedded[-limit:],
                "has_more": len(embedded) > limit,
                "limit": limit,
            }

        return {
            "phone_number": phone_number,
            "chat_history": page["messages"],
            "messages": page["messages"],
            "has_more": page["has_more"],
            "limit": page["limit"],
            "created_at": user.get("created_at"),
            "updated_at": user.get("updated_at"),
        }
    except HTTPException:
        raise
    except Exception:
        logger.exception(
            "Failed to get chat history", extra={"phone_number": phone_number}
        )
        raise HTTPException(status_code=500, detail="Failed to fetch chat history")
