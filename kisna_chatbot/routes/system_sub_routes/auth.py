import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from kisna_chatbot.database.collections import admin_sessions, admin_users
from kisna_chatbot.routes.dependencies.system_dependencies import (
    SESSION_COOKIE_NAME,
    verify_session,
)
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/auth", tags=["System - Auth"])

_SESSION_TTL = timedelta(hours=24)


class LoginRequest(BaseModel):
    username: str
    password: str


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=int(_SESSION_TTL.total_seconds()),
        path="/",
    )


@router.post("/login")
def login(body: LoginRequest, response: Response):
    """Admin login — validates against admin_users and starts a DB-backed session."""
    user = admin_users.find_one({"username": body.username})
    if not user or not bcrypt.checkpw(
        body.password.encode("utf-8"), user["password_hash"].encode("utf-8")
    ):
        logger.warning("Failed login attempt", extra={"username": body.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Single active session per account — a new login evicts any others.
    admin_sessions.delete_many({"username": user["username"]})

    session_id = secrets.token_urlsafe(32)
    # Naive UTC to match what pymongo hands back on read (no tz_aware=True
    # on the client) — mixing naive/aware datetimes raises TypeError.
    now = datetime.utcnow()
    admin_sessions.insert_one(
        {
            "session_id": session_id,
            "username": user["username"],
            "role": user.get("role", "super_admin"),
            "created_at": now,
            "expires_at": now + _SESSION_TTL,
            "revoked": False,
        }
    )
    _set_session_cookie(response, session_id)

    logger.info("Admin logged in", extra={"username": user["username"]})
    return {"success": True, "user": {"username": user["username"]}}


@router.post("/logout")
def logout(response: Response, session: dict = Depends(verify_session)):
    """Logout — revokes the session server-side and clears the cookie."""
    admin_sessions.delete_one({"session_id": session["session_id"]})
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"success": True, "message": "Logged out"}


@router.get("/me")
def me(session: dict = Depends(verify_session)):
    """Returns the currently authenticated admin user."""
    return {"username": session["username"], "role": session.get("role", "super_admin")}
