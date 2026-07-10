from fastapi import APIRouter, Depends

from kisna_chatbot.routes.dependencies.system_dependencies import (
    verify_api_key,
    verify_token,
    verify_token_or_api_key,
)
from kisna_chatbot.routes.system_sub_routes import ai as ai_router
from kisna_chatbot.routes.system_sub_routes import auth as auth_router
from kisna_chatbot.routes.system_sub_routes import chat_history as chat_history_router
from kisna_chatbot.routes.system_sub_routes import conversation as conversation_module
from kisna_chatbot.routes.system_sub_routes import callbacks as callbacks_router
from kisna_chatbot.routes.system_sub_routes import damage as damage_router
from kisna_chatbot.routes.system_sub_routes import dashboard as dashboard_router
from kisna_chatbot.routes.system_sub_routes import kb as kb_router
from kisna_chatbot.routes.system_sub_routes import users as users_router
from kisna_chatbot.routes.system_sub_routes import whatsapp as whatsapp_router
from kisna_chatbot.utils.logger_config import logger

router = APIRouter(prefix="/system", tags=["System"])

router.include_router(auth_router.router)

router.include_router(users_router.router)

router.include_router(conversation_module.stream_router)

router.include_router(
    conversation_module.router,
    dependencies=[Depends(verify_token_or_api_key)],
)

router.include_router(damage_router.router, dependencies=[Depends(verify_token)])

router.include_router(callbacks_router.router, dependencies=[Depends(verify_token)])

router.include_router(kb_router.router, dependencies=[Depends(verify_api_key)])

router.include_router(dashboard_router.router, dependencies=[Depends(verify_token)])

router.include_router(ai_router.router, dependencies=[Depends(verify_token)])

router.include_router(
    chat_history_router.router,
    dependencies=[Depends(verify_api_key)],
)

router.include_router(
    whatsapp_router.router,
    dependencies=[Depends(verify_api_key)],
)


@router.get("/ping", dependencies=[Depends(verify_token)])
def ping():
    """Health check — confirms the server is running."""
    logger.info("Ping endpoint called")
    return {"message": "Kisna Chatbot Server is running"}
