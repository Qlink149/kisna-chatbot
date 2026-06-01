import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.config.gupshup import build_phone_number_id_map
from kisna_chatbot.constants import DEFAULT_CLIENT_ID
from kisna_chatbot.database.db_utils import (
    get_takeover_status,
    save_response_time,
    save_to_mongo,
    save_user_message_silent,
)
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.pipelines.inference_pipeline import (
    AdFlowPipeline,
    ComplaintPipeline,
    GeneralPipeline,
    InitialPipeline,
    OffersPipeline,
    OrderTrackingPipeline,
    PreOrderPipeline,
    ProductCheckoutPipeline,
    ProductSearchPipeline,
)
from kisna_chatbot.processors.response_manager import ResponseManager
from kisna_chatbot.routes import system as system_router
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.pubsub import pubsub

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://kisna-dashboard.example.com",
]

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate Gupshup configuration on application startup."""
    from kisna_chatbot.utils.env_load import validate_ai_config, validate_gupshup_config

    validate_gupshup_config()
    validate_ai_config()
    yield


app = FastAPI(
    title="Kisna Chatbot Server",
    version="0.1.0",
    redoc_url=None,
    docs_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system_router.router)


def detect_client_id(request_data: dict) -> str:
    """Map Gupshup phone_number_id metadata to client_id slug."""
    try:
        metadata = (
            request_data["entry"][0]["changes"][0]["value"].get("metadata", {})
        )
        phone_number_id = metadata.get("phone_number_id", "")
        return build_phone_number_id_map().get(phone_number_id, DEFAULT_CLIENT_ID)
    except (KeyError, IndexError, TypeError):
        return DEFAULT_CLIENT_ID


def verify_gupshup_signature(
    body: bytes, signature: str | None, secret: str
) -> bool:
    """Verify Gupshup webhook HMAC-SHA256 body signature."""
    if signature and signature.startswith("sha256="):
        signature = signature.removeprefix("sha256=")
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature or "", expected)


def verify_webhook_request(body: bytes, signature: str | None) -> bool:
    """
    Verify webhook when GUPSHUP_WEBHOOK_SECRET is set.

    In dev without secret, skips verification (warning logged once at startup).
    """
    secret = os.getenv("GUPSHUP_WEBHOOK_SECRET", "").strip()
    if not secret:
        return True
    if not signature:
        return False
    return verify_gupshup_signature(body, signature, secret)


def _pipeline_for_service(service_selected: str):
    """Return pipeline instance for service_selected value."""
    mapping = {
        SL.GENERAL.value: GeneralPipeline,
        SL.RETURNS_REFUND.value: GeneralPipeline,
        SL.PRODUCT_SEARCH.value: ProductSearchPipeline,
        SL.OFFERS.value: OffersPipeline,
        SL.PRE_ORDER.value: PreOrderPipeline,
        SL.PRODUCT_CHECKOUT.value: ProductCheckoutPipeline,
        SL.ORDER_TRACKING.value: OrderTrackingPipeline,
        SL.COMPLAINT.value: ComplaintPipeline,
        SL.AD_FLOW.value: AdFlowPipeline,
    }
    pipeline_cls = mapping.get(service_selected)
    return pipeline_cls() if pipeline_cls else None


async def _save_and_send(data: dict, phone_number: str, pipeline_start: float) -> None:
    client_id = data.get("client_id", DEFAULT_CLIENT_ID)
    save_to_mongo(data=data)
    save_response_time(
        phone_number,
        round((time.time() - pipeline_start) * 1000),
        client_id=client_id,
    )
    ResponseManager().handle_responses(data=data)


async def process_message(request_data: dict) -> None:
    """Process incoming WhatsApp message in the background."""
    phone_number = None
    data: dict = {}

    try:
        whatsapp_event = request_data["entry"][0]["changes"][0]["value"]
        messages = whatsapp_event["messages"][0]
        phone_number = messages["from"]
        contacts = whatsapp_event.get("contacts", [])
        whatsapp_username = (
            contacts[0]["profile"]["name"] if contacts else ""
        )

        client_id = detect_client_id(request_data)
        try:
            phone_number_id = (
                request_data["entry"][0]["changes"][0]["value"]
                .get("metadata", {})
                .get("phone_number_id", "")
            )
            if phone_number_id and phone_number_id not in build_phone_number_id_map():
                logger.info(
                    "Webhook phone_number_id not in env map; using default client "
                    "(optional: set KISNA_PHONE_NUMBER_ID for explicit routing)",
                    extra={
                        "phone_number_id": phone_number_id,
                        "client_id": client_id,
                    },
                )
        except (KeyError, IndexError, TypeError):
            pass

        client_config = get_client_config(client_id)

        data = {
            "phone_number": phone_number,
            "messages": messages,
            "whatsapp_username": whatsapp_username,
            "client_id": client_id,
            "client_config": client_config,
        }
        logger.info(
            "Data object to pipeline",
            extra={"phone_number": phone_number, "client_id": client_id},
        )

        takeover = get_takeover_status(phone_number, client_id)
        if takeover and takeover.get("active"):
            logger.info(
                "Human takeover active — saving message silently",
                extra={"phone_number": phone_number},
            )
            text_body = messages.get("text", {}).get("body", "")
            if text_body:
                save_user_message_silent(phone_number, text_body, client_id)
                await pubsub.publish(
                    phone_number,
                    {"type": "user_message", "content": text_body},
                )
            return

        pipeline_start = time.time()
        data = await InitialPipeline().run(data=data)

        if "bot_response" in data:
            logger.info(
                "Bot response from initial pipeline",
                extra={"phone_number": phone_number},
            )
            await _save_and_send(data, phone_number, pipeline_start)
            return

        service_selected = data.get("user_profile", {}).get("service_selected", "")
        logger.info(
            "Routing to service pipeline",
            extra={
                "phone_number": phone_number,
                "service_selected": service_selected,
            },
        )

        pipeline = _pipeline_for_service(service_selected)
        if pipeline:
            data = await pipeline.run(data=data)
            if "bot_response" in data:
                await _save_and_send(data, phone_number, pipeline_start)

    except Exception as e:
        logger.exception(
            "Exception occurred while processing message",
            extra={"exception": e, "phone_number": phone_number},
        )
        if data and phone_number:
            data["bot_response"] = [
                {"type": "text", "text": "Unexpected error occurred."}
            ]
            try:
                save_to_mongo(data=data)
                ResponseManager().handle_responses(data=data)
            except Exception as save_err:
                logger.exception(
                    "Failed to save error response",
                    extra={"exception": save_err},
                )


@app.get("/ping")
def ping():
    """Public health check."""
    return {"status": "ok"}


@app.post("/gupshup/message/kisna")
async def messages_kisna(
    request: Request, background_tasks: BackgroundTasks
):
    """Gupshup WhatsApp webhook for Kisna."""
    body = await request.body()
    signature = request.headers.get("X-Gupshup-Signature") or request.headers.get(
        "x-hub-signature-256"
    )
    if not verify_webhook_request(body, signature):
        logger.warning("Webhook signature verification failed")
        return JSONResponse(content={"success": False}, status_code=401)

    request_data = json.loads(body)
    logger.info("Webhook received", extra={"keys": list(request_data.keys())})

    if "payload" in request_data:
        logger.info("Payload wrapper found, ignoring")
        return JSONResponse(content={"success": True}, status_code=200)

    try:
        whatsapp_event = request_data["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        return JSONResponse(content={"success": True}, status_code=200)

    if "statuses" in whatsapp_event:
        status_item = whatsapp_event["statuses"][0]
        status = status_item.get("type") or status_item.get("status", "unknown")
        logger.info("Ignoring status update", extra={"status": status})
        return JSONResponse(content={"success": True}, status_code=200)

    if "messages" not in whatsapp_event:
        return JSONResponse(content={"success": True}, status_code=200)

    if os.getenv("VERCEL"):
        await process_message(request_data)
    else:
        background_tasks.add_task(process_message, request_data)
    return JSONResponse(content={"success": True}, status_code=200)
