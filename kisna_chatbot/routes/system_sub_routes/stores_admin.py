"""Dashboard: the bookable store list -- view, CSV upload, toggles, CSV download."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from kisna_chatbot.stores import repo
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/stores", tags=["System - Stores"])

_MAX_UPLOAD_BYTES = 2 * 1024 * 1024


class StoreFlagsUpdate(BaseModel):
    bookable: bool | None = None
    active: bool | None = None


@router.get("")
def list_stores():
    stores = repo.list_all()
    return {
        "data": stores,
        "total": len(stores),
        "bookable": sum(1 for s in stores if s.get("active") and s.get("bookable")),
    }


@router.post("/import")
async def import_stores(file: UploadFile = File(...)):
    """Upsert on store_id. Any row error rejects the WHOLE file (nothing is
    written) and every error is returned with its line number."""
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="CSV is larger than 2 MB")
    result = repo.import_csv(content)
    if not result["ok"]:
        return JSONResponse(result, status_code=422)
    return result


@router.patch("/{store_id}")
def patch_store(store_id: str, body: StoreFlagsUpdate):
    if body.bookable is None and body.active is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        doc = repo.set_flags(store_id, bookable=body.bookable, active=body.active)
    except Exception:
        logger.exception("Failed to update store", extra={"store_id": store_id})
        raise HTTPException(status_code=500, detail="Failed to update store")
    if not doc:
        raise HTTPException(status_code=404, detail="Store not found")
    return doc


@router.get("/export.csv")
def export_stores():
    return Response(
        content=repo.to_csv(repo.list_all()),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="stores.csv"'},
    )
