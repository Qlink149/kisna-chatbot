"""Read-only visibility into the outbound Clara event outbox.

Answers "did this complaint / callback actually reach Salesforce?" without a
Mongo shell.
"""

from fastapi import APIRouter, HTTPException, Query

from kisna_chatbot.database.collections import clara_events
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/clara-events", tags=["System - Clara Events"])

_VALID_STATUSES = ("pending", "sent", "failed", "failed_permanent")


def _serialize(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


@router.get("")
def list_clara_events(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    client_id: str = Query("kisna", description="Tenant client id"),
    status: str | None = Query(
        None, description="pending | sent | failed | failed_permanent"
    ),
    event_type: str | None = Query(
        None,
        description="complaint_submitted | callback_requested | video_call_requested",
    ),
    event_id: str | None = Query(None, description="Exact event id lookup"),
):
    """List outbound events, newest first."""
    if status and status not in _VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    query: dict = {"client_id": client_id}
    if status:
        query["status"] = status
    if event_type:
        query["event_type"] = event_type
    if event_id:
        query["event_id"] = event_id

    try:
        total = clara_events.count_documents(query)
        cursor = (
            clara_events.find(query)
            .sort("created_at", -1)
            .skip((page - 1) * limit)
            .limit(limit)
        )
        return {
            "total": total,
            "page": page,
            "limit": limit,
            "items": [_serialize(doc) for doc in cursor],
        }
    except Exception:
        logger.exception("Failed to list Clara events")
        raise HTTPException(status_code=500, detail="Failed to fetch Clara events")


@router.get("/stats")
def clara_event_stats(
    client_id: str = Query("kisna", description="Tenant client id"),
):
    """Counts per delivery status — the at-a-glance health of the push."""
    try:
        counts = {status: 0 for status in _VALID_STATUSES}
        pipeline = [
            {"$match": {"client_id": client_id}},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        ]
        for row in clara_events.aggregate(pipeline):
            counts[row["_id"]] = row["count"]
        return {"client_id": client_id, "counts": counts}
    except Exception:
        logger.exception("Failed to aggregate Clara event stats")
        raise HTTPException(status_code=500, detail="Failed to fetch Clara event stats")
