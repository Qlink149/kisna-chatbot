"""Dashboard: the store list -- view, override edits, CSV upload/download,
and the kisna.com sync (last run + "Sync now").

name / address / city / state / pincode / phone and presence come from the
kisna.com sync. The dashboard edits only bookable / open_time / close_time /
weekly_off.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from kisna_chatbot.routes.dependencies.system_dependencies import verify_session
from kisna_chatbot.stores import repo
from kisna_chatbot.stores.model import OVERRIDE_FIELDS, SYNCED_FIELDS
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/stores", tags=["System - Stores"])

_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ADMIN_ROLES = frozenset({"super_admin", "admin"})


class StoreOverridesUpdate(BaseModel):
    """Only the dashboard-owned fields; anything else in the body is refused."""

    model_config = {"extra": "forbid"}

    bookable: bool | None = None
    open_time: str | None = None
    close_time: str | None = None
    weekly_off: list[str] | None = None


def _require_admin(session: dict) -> None:
    if session.get("role", "super_admin") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("")
def list_stores():
    from kisna_chatbot.stores.sync import last_run

    stores = repo.list_all()
    return {
        "data": stores,
        "total": len(stores),
        "bookable": sum(1 for s in stores if s.get("active") and s.get("bookable")),
        "synced_fields": list(SYNCED_FIELDS),
        "override_fields": list(OVERRIDE_FIELDS),
        "last_sync": last_run(),
    }


@router.get("/sync")
def last_sync():
    from kisna_chatbot.stores.sync import last_run

    return {"last_run": last_run(), "last_ok": last_run("ok")}


@router.post("/sync")
async def sync_now(session: dict = Depends(verify_session)):
    """Run the kisna.com sync now -- the same job as the 02:00 IST run."""
    _require_admin(session)
    from kisna_chatbot.stores.sync import run_sync

    return await run_sync(trigger=f"manual:{session.get('username', 'dashboard')}")


@router.post("/import")
async def import_stores(file: UploadFile = File(...)):
    """Overrides only: store_id + bookable / open_time / close_time /
    weekly_off. Synced columns may be present but must match kisna.com. Any
    row error rejects the WHOLE file; every error is returned with its line."""
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV is larger than 2 MB")
    result = repo.import_csv(content)
    if not result["ok"]:
        return JSONResponse(result, status_code=422)
    return result


@router.patch("/{store_id}")
def patch_store(store_id: str, body: StoreOverridesUpdate, session: dict = Depends(verify_session)):
    values = body.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        doc, errors = repo.set_overrides(store_id, values, by=session.get("username", ""))
    except Exception:
        logger.exception("Failed to update store", extra={"store_id": store_id})
        raise HTTPException(status_code=500, detail="Failed to update store")
    if doc is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))
    return doc


@router.get("/export.csv")
def export_stores():
    return Response(
        content=repo.to_csv(repo.list_all()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="stores.csv"'},
    )
