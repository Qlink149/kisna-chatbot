from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from kisna_chatbot.utils.env_load import jwt_secret_key, system_api_key

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str = Security(_api_key_header)) -> None:
    """FastAPI dependency - validates API key from X-API-Key header."""
    if not api_key or api_key != system_api_key:
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
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
) -> dict:
    """FastAPI dependency — validates JWT from Authorization: Bearer header."""
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return decode_access_token(credentials.credentials)


def verify_token_query(token: str = Query(..., description="JWT for SSE")) -> dict:
    """FastAPI dependency — validates JWT passed as ?token= query param (for SSE/EventSource)."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
        )
    return decode_access_token(token)


def verify_token_or_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
    api_key: str | None = Security(_api_key_header),
) -> dict:
    """FastAPI dependency — accepts either X-API-Key or Authorization Bearer JWT."""
    if api_key and api_key == system_api_key:
        return {"auth": "api_key"}
    if credentials and credentials.credentials:
        return decode_access_token(credentials.credentials)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials",
    )
