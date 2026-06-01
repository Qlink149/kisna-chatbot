from fastapi import APIRouter, HTTPException, Query
from typing import Literal

from kisna_chatbot.database.db_utils import (
    get_dashboard_stats,
    get_rating_stats,
    get_user_growth,
    get_store_visit_growth,
)
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/dashboard", tags=["System - Dashboard"])

Period = Literal["year", "month", "week"]


@router.get("/stats")
def dashboard_stats(client_id: str = Query("kisna", description="Tenant client id")):
    """Return high-level dashboard statistics."""
    try:
        return get_dashboard_stats(client_id=client_id)
    except Exception:
        logger.exception("Failed to fetch dashboard stats")
        raise HTTPException(status_code=500, detail="Failed to fetch dashboard stats")


@router.get("/ratings")
def rating_stats(client_id: str = Query("kisna", description="Tenant client id")):
    """Return experience rating breakdown and average score."""
    try:
        return get_rating_stats(client_id=client_id)
    except Exception:
        logger.exception("Failed to fetch rating stats")
        raise HTTPException(status_code=500, detail="Failed to fetch rating stats")


@router.get("/users/growth")
def users_growth(
    period: Period = Query("month", description="Grouping granularity: year | month | week"),
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Return new user counts grouped by period."""
    try:
        data = get_user_growth(period=period, client_id=client_id)
        return {"period": period, "data": data}
    except Exception:
        logger.exception("Failed to fetch user growth", extra={"period": period})
        raise HTTPException(status_code=500, detail="Failed to fetch user growth")


@router.get("/store-visits/growth")
def store_visits_growth(
    period: Period = Query("month", description="Grouping granularity: year | month | week"),
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Return store visit counts grouped by period."""
    try:
        data = get_store_visit_growth(period=period, client_id=client_id)
        return {"period": period, "data": data}
    except Exception:
        logger.exception("Failed to fetch store visit growth", extra={"period": period})
        raise HTTPException(status_code=500, detail="Failed to fetch store visit growth")
