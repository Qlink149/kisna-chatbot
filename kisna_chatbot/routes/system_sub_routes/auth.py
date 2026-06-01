from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from kisna_chatbot.routes.dependencies.system_dependencies import create_access_token
from kisna_chatbot.utils.env_load import super_admin_password, super_admin_username
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/auth", tags=["System - Auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(body: LoginRequest):
    """Super admin login — validates against env credentials and returns JWT token."""
    if body.username != super_admin_username or body.password != super_admin_password:
        logger.warning("Failed login attempt", extra={"username": body.username})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token({"sub": body.username, "role": "super_admin"})

    logger.info("Super admin logged in", extra={"username": body.username})
    return {"success": True, "token": token}


@router.post("/logout")
def logout():
    """Logout — token is stateless; client should discard it."""
    return {"success": True, "message": "Logged out"}
