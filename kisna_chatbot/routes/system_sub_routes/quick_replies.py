"""Dashboard: quick replies -- saved messages an agent inserts into the chat
composer. Any signed-in dashboard user may manage them; every change records
the session's username (kisna_chatbot/quick_replies.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from kisna_chatbot import quick_replies as qr
from kisna_chatbot.routes.dependencies.system_dependencies import verify_session
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/quick-replies", tags=["System - Quick replies"])


class QuickReplyCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    body: str | None = None


class QuickReplyUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    body: str | None = None


class QuickReplyOrder(BaseModel):
    model_config = {"extra": "forbid"}

    ids: list[str]


def _by(session: dict) -> str:
    return session.get("username") or "dashboard"


def _fail(e: qr.QuickReplyError):
    raise HTTPException(status_code=e.status, detail=e.message)


@router.get("")
def list_quick_replies(client_id: str = Query(qr.DEFAULT_CLIENT_ID)):
    rows = qr.list_active(client_id)
    return {"data": rows, "total": len(rows), "max": qr.MAX_ACTIVE}


@router.post("", status_code=201)
def create_quick_reply(
    body: QuickReplyCreate,
    client_id: str = Query(qr.DEFAULT_CLIENT_ID),
    session: dict = Depends(verify_session),
):
    try:
        item = qr.create(body.title, body.body, by=_by(session), client_id=client_id)
    except qr.QuickReplyError as e:
        _fail(e)
    logger.info("Quick reply created", extra={"quick_reply_id": item["id"], "by": _by(session)})
    return item


# Declared before /{reply_id} so "order" is never read as an id.
@router.put("/order")
def reorder_quick_replies(
    body: QuickReplyOrder,
    client_id: str = Query(qr.DEFAULT_CLIENT_ID),
    session: dict = Depends(verify_session),
):
    try:
        rows = qr.reorder(body.ids, by=_by(session), client_id=client_id)
    except qr.QuickReplyError as e:
        _fail(e)
    logger.info("Quick replies reordered", extra={"by": _by(session)})
    return {"data": rows, "total": len(rows), "max": qr.MAX_ACTIVE}


@router.patch("/{reply_id}")
def update_quick_reply(
    reply_id: str,
    body: QuickReplyUpdate,
    client_id: str = Query(qr.DEFAULT_CLIENT_ID),
    session: dict = Depends(verify_session),
):
    try:
        item = qr.update(reply_id, title=body.title, body=body.body, by=_by(session), client_id=client_id)
    except qr.QuickReplyError as e:
        _fail(e)
    logger.info("Quick reply updated", extra={"quick_reply_id": reply_id, "by": _by(session)})
    return item


@router.delete("/{reply_id}", status_code=204)
def delete_quick_reply(
    reply_id: str,
    client_id: str = Query(qr.DEFAULT_CLIENT_ID),
    session: dict = Depends(verify_session),
):
    try:
        qr.delete(reply_id, by=_by(session), client_id=client_id)
    except qr.QuickReplyError as e:
        _fail(e)
    logger.info("Quick reply deleted", extra={"quick_reply_id": reply_id, "by": _by(session)})
    return Response(status_code=204)
