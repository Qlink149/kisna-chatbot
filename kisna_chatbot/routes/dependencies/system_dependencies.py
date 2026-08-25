from datetime import datetime

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from kisna_chatbot.database.collections import admin_sessions
from kisna_chatbot.utils.env_load import system_api_key
from kisna_chatbot.utils.logger_config import log_event

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SESSION_COOKIE_NAME = "kisna_session"

# Reason codes returned in the 401 body's `detail.reason` so the frontend can
# tell "you were never logged in" apart from "you were signed out because
# someone else logged into this account" without parsing message text.
REASON_MISSING = "missing_session"
REASON_REPLACED = "session_replaced"
REASON_EXPIRED = "session_expired"
REASON_INVALID = "session_invalid"

_REASON_MESSAGES = {
    REASON_MISSING: "Not authenticated",
    REASON_REPLACED: "Signed out - this account was logged in elsewhere",
    REASON_EXPIRED: "Session expired",
    REASON_INVALID: "Invalid session",
}


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


def _unauthorized(reason: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"message": _REASON_MESSAGES[reason], "reason": reason},
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


def _load_session(session_id: str) -> tuple[dict | None, str]:
    """Look up a session by id.

    Returns (session, reason) — reason is only meaningful when session is
    None. pymongo returns naive UTC datetimes by default (no tz_aware=True
    on the client), so expiry is compared against naive utcnow() to match —
    mixing a naive expires_at with an aware now() raises TypeError.
    """
    session = admin_sessions.find_one({"session_id": session_id})
    if not session:
        return None, REASON_INVALID
    if session.get("revoked"):
        reason = (
            REASON_REPLACED
            if session.get("revoked_reason") == "replaced_by_new_login"
            else REASON_INVALID
        )
        return None, reason
    expires_at = session.get("expires_at")
    if not expires_at or expires_at <= datetime.utcnow():
        return None, REASON_EXPIRED
    return session, ""


def verify_session(request: Request) -> dict:
    """FastAPI dependency — validates the dashboard session cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id:
        _auth_failed(request, reason=REASON_MISSING)
        raise _unauthorized(REASON_MISSING)
    session, reason = _load_session(session_id)
    if not session:
        _auth_failed(request, reason=reason)
        raise _unauthorized(reason)
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
        session, reason = _load_session(session_id)
        if session:
            return session
        _auth_failed(request, reason=reason)
        raise _unauthorized(reason)
    _auth_failed(request, reason=REASON_MISSING)
    raise _unauthorized(REASON_MISSING)
