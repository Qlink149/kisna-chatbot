from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from kisna_chatbot.utils.env_load import jwt_secret_key, system_api_key
from kisna_chatbot.utils.logger_config import log_event

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


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


_JWT_EXPIRE_MINUTES = 60 * 24  # 24 hours

ALGORITHM = "HS256"
_bearer_optional = HTTPBearer(auto_error=False)


def create_access_token(data: dict) -> str:
    """Create a JWT access token with a 24-hour expiration."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=_JWT_EXPIRE_MINUTES)
    return jwt.encode(payload, jwt_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT access token."""
    try:
        return jwt.decode(token, jwt_secret_key, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
) -> dict:
    """FastAPI dependency — validates JWT from Authorization: Bearer header."""
    if not credentials or not credentials.credentials:
        _auth_failed(request, reason="missing_bearer_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        return decode_access_token(credentials.credentials)
    except HTTPException:
        _auth_failed(request, reason="invalid_or_expired_token")
        raise


def verify_token_query(
    request: Request,
    token: str = Query(..., description="JWT for SSE"),
) -> dict:
    """FastAPI dependency — validates JWT passed as ?token= query param (for SSE/EventSource)."""
    if not token:
        _auth_failed(request, reason="missing_query_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )
    try:
        return decode_access_token(token)
    except HTTPException:
        _auth_failed(request, reason="invalid_or_expired_query_token")
        raise


def verify_token_or_api_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
    api_key: str | None = Security(_api_key_header),
) -> dict:
    """FastAPI dependency — accepts either X-API-Key or Authorization Bearer JWT."""
    if api_key and api_key == system_api_key:
        return {"auth": "api_key"}
    if credentials and credentials.credentials:
        try:
            return decode_access_token(credentials.credentials)
        except HTTPException:
            _auth_failed(request, reason="invalid_or_expired_token")
            raise
    _auth_failed(request, reason="invalid_or_missing_credentials")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
    )
