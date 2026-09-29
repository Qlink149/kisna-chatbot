"""Dashboard: Store Visit bookings -- list, filter, search, status, CSV export."""

from __future__ import annotations

import csv
import io
import re
import time

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from kisna_chatbot.database.collections import clara_events, store_visits
from kisna_chatbot.processors.store_visit_agent import SOURCE, STATUSES
from kisna_chatbot.routes.dependencies.system_dependencies import verify_session
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/store-visits", tags=["System - Store Visits"])

_MAX_EXPORT = 10_000


class StoreVisitStatusUpdate(BaseModel):
    status: str


def _query(
    client_id: str,
    status: str | None,
    store_id: str | None,
    state: str | None,
    city: str | None,
    date_from: str | None,
    date_to: str | None,
    q: str | None,
) -> dict:
    # Only bookings from this Flow; legacy store_visits rows have another shape.
    query: dict = {"client_id": client_id, "source": SOURCE}
    if status:
        query["status"] = status
    if store_id:
        query["store.store_id"] = store_id
    if state:
        query["store.state"] = state
    if city:
        query["store.city"] = city
    if date_from or date_to:
        rng: dict = {}
        if date_from:
            rng["$gte"] = date_from
        if date_to:
            rng["$lte"] = date_to
        query["preferred_date"] = rng
    text = (q or "").strip()
    if text:
        pattern = {"$regex": re.escape(text), "$options": "i"}
        query["$or"] = [
            {"request_id": pattern},
            {"first_name": pattern},
            {"last_name": pattern},
            {"email": pattern},
            {"mobile": pattern},
            {"phone_number": pattern},
            {"store.name": pattern},
        ]
    return query


def _with_sync_status(rows: list[dict]) -> list[dict]:
    """sf_sync_status = the Clara outbox row's status for this request id
    (event_id == request_id): pending / sent / failed / failed_permanent,
    or "not_queued" when the push is off or never enqueued."""
    ids = [r["request_id"] for r in rows if r.get("request_id")]
    status_by_id = {
        e["event_id"]: e.get("status")
        for e in clara_events.find({"event_id": {"$in": ids}}, {"event_id": 1, "status": 1})
    } if ids else {}
    for r in rows:
        r["sf_sync_status"] = status_by_id.get(r.get("request_id"), "not_queued")
    return rows


@router.get("")
def list_store_visits(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    client_id: str = Query("kisna"),
    status: str | None = Query(None),
    store_id: str | None = Query(None),
    state: str | None = Query(None),
    city: str | None = Query(None),
    date_from: str | None = Query(None, description="preferred_date >= YYYY-MM-DD"),
    date_to: str | None = Query(None, description="preferred_date <= YYYY-MM-DD"),
    q: str | None = Query(None, description="request id, name, email, phone or store"),
):
    try:
        query = _query(client_id, status, store_id, state, city, date_from, date_to, q)
        total = store_visits.count_documents(query)
        rows = list(
            store_visits.find(query, {"_id": 0, "flow_token": 0})
            .sort("created_at", -1)
            .skip((page - 1) * limit)
            .limit(limit)
        )
        return {
            "data": _with_sync_status(rows),
            "total": total,
            "page": page,
            "limit": limit,
            "statuses": list(STATUSES),
        }
    except Exception:
        logger.exception("Failed to list store visits")
        raise HTTPException(status_code=500, detail="Failed to fetch store visits")


@router.patch("/{request_id}")
def patch_store_visit_status(
    request_id: str,
    body: StoreVisitStatusUpdate,
    client_id: str = Query("kisna"),
    session: dict = Depends(verify_session),
):
    if body.status not in STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    agent = session.get("username") or "dashboard"
    now = int(time.time())
    try:
        doc = store_visits.find_one_and_update(
            {"request_id": request_id, "client_id": client_id, "source": SOURCE},
            {
                "$set": {
                    "status": body.status,
                    "status_updated_by": agent,
                    "status_updated_at": now,
                },
                "$push": {"status_history": {"status": body.status, "by": agent, "at": now}},
            },
            projection={"_id": 0, "flow_token": 0},
            return_document=True,
        )
    except Exception:
        logger.exception("Failed to update store visit", extra={"request_id": request_id})
        raise HTTPException(status_code=500, detail="Failed to update store visit")
    if not doc:
        raise HTTPException(status_code=404, detail="Store visit not found")
    return doc


_EXPORT_FIELDS = (
    ("request_id", lambda r: r.get("request_id")),
    ("created_at", lambda r: time.strftime("%Y-%m-%d %H:%M", time.gmtime((r.get("created_at") or 0) + 19800))),
    ("status", lambda r: r.get("status")),
    ("first_name", lambda r: r.get("first_name")),
    ("last_name", lambda r: r.get("last_name")),
    ("email", lambda r: r.get("email")),
    ("mobile", lambda r: r.get("mobile")),
    ("whatsapp_number", lambda r: r.get("phone_number")),
    ("looking_for", lambda r: r.get("looking_for_label") or r.get("looking_for")),
    ("store_id", lambda r: (r.get("store") or {}).get("store_id")),
    ("store_name", lambda r: (r.get("store") or {}).get("name")),
    ("city", lambda r: (r.get("store") or {}).get("city")),
    ("state", lambda r: (r.get("store") or {}).get("state")),
    ("preferred_date", lambda r: r.get("preferred_date")),
    ("preferred_time", lambda r: r.get("preferred_time_label") or r.get("preferred_time")),
    ("language", lambda r: r.get("language")),
    ("sf_sync_status", lambda r: r.get("sf_sync_status")),
    ("status_updated_by", lambda r: r.get("status_updated_by")),
)


@router.get("/export.csv")
def export_store_visits(
    client_id: str = Query("kisna"),
    status: str | None = Query(None),
    store_id: str | None = Query(None),
    state: str | None = Query(None),
    city: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    q: str | None = Query(None),
):
    query = _query(client_id, status, store_id, state, city, date_from, date_to, q)
    rows = _with_sync_status(
        list(store_visits.find(query, {"_id": 0}).sort("created_at", -1).limit(_MAX_EXPORT))
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([name for name, _ in _EXPORT_FIELDS])
    for r in rows:
        writer.writerow([fn(r) or "" for _, fn in _EXPORT_FIELDS])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="store_visits.csv"'},
    )
