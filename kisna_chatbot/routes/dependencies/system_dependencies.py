from datetime import datetime, timezone

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from kisna_chatbot.database.collections import admin_sessions
from kisna_chatbot.utils.env_load import system_api_key
from kisna_chatbot.utils.logger_config import log_event

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SESSION_COOKIE_NAME = "kisna_session"


def _auth_failed(request: Request, *, reason: str, username: str | None = None) -> None:
    log_event(
        "auth_failed",
        reason,
        level="warning",
        path=request.url.path,
        method=request.method,
        reason=reason,
        username=username,
    )


def verify_api_key(
    request: Request,
    api_key: str = Security(_api_key_header),
) -> None:
    """FastAPI dependency - validates API key from X-API-Key header."""
    if not api_key or api_key != system_api_key:
        _auth_failed(request, reason="invalid_or_missing_api_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def _load_session(session_id: str) -> dict | None:
    """Look up a session by id, returning it only if still valid."""
    session = admin_sessions.find_one({"session_id": session_id})
    if not session or session.get("revoked"):
        return None
    expires_at = session.get("expires_at")
    if not expires_at or expires_at <= datetime.now(timezone.utc):
        return None
    return session


def verify_session(request: Request) -> dict:
    """FastAPI dependency — validates the dashboard session cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        _auth_failed(request, reason="missing_session_cookie")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    session = _load_session(session_id)
    if not session:
        _auth_failed(request, reason="invalid_or_expired_session")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    return session


def verify_session_or_api_key(
    request: Request,
    api_key: str | None = Security(_api_key_header),
) -> dict:
    """FastAPI dependency — accepts either X-API-Key or a valid session cookie."""
    if api_key and api_key == system_api_key:
        return {"auth": "api_key"}
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        session = _load_session(session_id)
        if session:
            return session
    _auth_failed(request, reason="invalid_or_missing_credentials")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
    )
