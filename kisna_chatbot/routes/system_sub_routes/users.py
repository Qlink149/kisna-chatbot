from fastapi import APIRouter, Depends, HTTPException, Query

from kisna_chatbot.database.db_utils import get_all_users, get_user_by_phone, search_users
from kisna_chatbot.routes.dependencies.system_dependencies import verify_token
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(
    prefix="/user",
    tags=["System - Users"],
    dependencies=[Depends(verify_token)],
)


@router.get("")
def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    agent_requested: bool | None = Query(
        None, description="Filter to only users who requested a live agent"
    ),
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """List all users — sorted by most recently updated, with pagination. Pass agent_requested=true to filter to live-agent requests only."""
    try:
        return get_all_users(
            page=page,
            limit=limit,
            client_id=client_id,
            agent_requested=agent_requested,
        )
    except Exception:
        logger.exception("Failed to list users")
        raise HTTPException(status_code=500, detail="Failed to fetch users")


@router.get("/search")
def search(
    q: str = Query(..., min_length=1, description="Search term — matches phone number or username"),
    limit: int = Query(20, ge=1, le=100),
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Search users by phone number or username (partial, case-insensitive)."""
    try:
        results = search_users(q=q, limit=limit, client_id=client_id)
        return {"results": results, "count": len(results)}
    except Exception:
        logger.exception("Failed to search users", extra={"q": q})
        raise HTTPException(status_code=500, detail="Failed to search users")


@router.get("/{phone_number}")
def get_user(
    phone_number: str,
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Get complete user document by phone number."""
    try:
        user = get_user_by_phone(phone_number, client_id=client_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to get user", extra={"phone_number": phone_number})
        raise HTTPException(status_code=500, detail="Failed to fetch user")
