import asyncio
import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.config.gupshup import build_phone_number_id_map
from kisna_chatbot.constants import DEFAULT_CLIENT_ID
from kisna_chatbot.database.collections import processed_inbound_messages
from kisna_chatbot.database.db_utils import (
    get_takeover_status,
    save_response_time,
    save_to_mongo,
    save_user_message_silent,
    touch_last_message_at,
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
    ReturnsRefundPipeline,
)
from kisna_chatbot.middleware.logging_middleware import LoggingMiddleware
from kisna_chatbot.processors.response_manager import ResponseManager
from kisna_chatbot.processors.non_text_handler import handle_non_text_message
from kisna_chatbot.processors.service_list import build_main_menu_bot_response
from kisna_chatbot.processors.user_registration import UserRegistration
from kisna_chatbot.utils.format_chathistory import format_user
from kisna_chatbot.routes import system as system_router
from kisna_chatbot.whatsapp_functions.typing_indicator import typing_indicator_loop
from kisna_chatbot.utils.logger_config import (
    clear_request_context,
    log_event,
    log_http_bodies_enabled,
    logger,
    sanitize_for_log,
    set_request_context,
)
from kisna_chatbot.utils.pubsub import pubsub
from kisna_chatbot.utils.rate_limiter import INBOUND_RATE_LIMIT, is_rate_limited

# TODO: Upgrade to Redis distributed lock for multi-instance safety.
_USER_LOCKS: dict[str, asyncio.Lock] = {}


async def _get_user_lock(phone: str) -> asyncio.Lock:
    if phone not in _USER_LOCKS:
        _USER_LOCKS[phone] = asyncio.Lock()
    return _USER_LOCKS[phone]

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://kisna-dashboard.example.com",
    "https://kisna-dashboard.vercel.app",
    "https://kisna-chatbot-dashboard.vercel.app",
    "https://kisna-wa.claraai.tech",
]

def _log_webhook_payload_enabled() -> bool:
    return log_http_bodies_enabled()


def mark_inbound_processed(
    *,
    client_id: str,
    phone_number: str,
    message_id: str,
) -> bool:
    """
    Best-effort idempotency gate for inbound WhatsApp messages.

    Returns True if we marked this message_id as newly processed; False if it was
    already processed (duplicate delivery).
    """
    if not message_id:
        return True
    try:
        processed_inbound_messages.insert_one(
            {
                "client_id": client_id,
                "phone_number": phone_number,
                "message_id": message_id,
                "created_at": datetime.now(timezone.utc),
            }
        )
        return True
    except DuplicateKeyError:
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate Gupshup configuration on application startup."""
    from kisna_chatbot.utils.env_load import validate_ai_config, validate_gupshup_config

    # On Vercel, missing optional keys should warn (not crash) unless ENV_MODE=prod.
    try:
        validate_gupshup_config()
        validate_ai_config()
    except RuntimeError:
        if os.getenv("VERCEL") and os.getenv("ENV_MODE", "dev").lower() != "prod":
            logger.warning(
                "Startup validation failed on Vercel; continuing because ENV_MODE is not prod"
            )
        else:
            raise

    # Ensure idempotency indexes exist (safe to call repeatedly).
    try:
        processed_inbound_messages.create_index(
            [("client_id", ASCENDING), ("message_id", ASCENDING)],
            unique=True,
            name="uniq_client_message_id",
        )
    except Exception:
        logger.exception("Failed to create processed_inbound_messages indexes")

    from kisna_chatbot.database.database import ping_database

    try:
        ping_database()
    except Exception:
        logger.exception("MongoDB connectivity check failed on startup")

    from kisna_chatbot.utils.clara_cache import warm_clara_caches

    await warm_clara_caches(app.state)
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
app.add_middleware(LoggingMiddleware)

app.include_router(system_router.router)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None)
    log_event(
        "http_exception",
        str(exc.detail),
        level="warning",
        request_id=request_id,
        status_code=exc.status_code,
        path=request.url.path,
        detail=exc.detail,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={"X-Request-Id": request_id or ""},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.exception(
        "Unhandled exception",
        extra={
            "event": "unhandled_exception",
            "request_id": request_id,
            "path": request.url.path,
            "error": str(exc),
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={"X-Request-Id": request_id or ""},
    )


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
        SL.RETURNS_REFUND.value: ReturnsRefundPipeline,
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


async def _persist_session(
    data: dict, phone_number: str, pipeline_start: float
) -> None:
    client_id = data.get("client_id", DEFAULT_CLIENT_ID)
    save_to_mongo(data=data)
    save_response_time(
        phone_number,
        round((time.time() - pipeline_start) * 1000),
        client_id=client_id,
    )


async def process_message(
    request_data: dict,
    app_state=None,
    *,
    request_id: str | None = None,
) -> None:
    """Process incoming WhatsApp message in the background."""
    phone_number = None
    data: dict = {}
    responses_to_send: dict | None = None
    stop_typing_event: asyncio.Event | None = None
    typing_task = None

    if request_id:
        set_request_context(request_id=request_id)

    try:
        whatsapp_event = request_data["entry"][0]["changes"][0]["value"]
        messages = whatsapp_event["messages"][0]
        phone_number = messages["from"]
        contacts = whatsapp_event.get("contacts", [])
        whatsapp_username = (
            contacts[0]["profile"]["name"] if contacts else ""
        )

        client_id = detect_client_id(request_data)
        message_id = str(messages.get("id", "") or "")
        set_request_context(phone_number=phone_number, client_id=client_id)

        log_event(
            "inbound_message",
            "Processing WhatsApp message",
            phone_number=phone_number,
            client_id=client_id,
            message_id=message_id,
            message_type=messages.get("type"),
        )

        if _log_webhook_payload_enabled():
            try:
                phone_number_id = (
                    whatsapp_event.get("metadata", {}).get("phone_number_id", "")
                )
                logger.info(
                    "Inbound webhook payload (process_message)",
                    extra={
                        "client_id": client_id,
                        "phone_number": phone_number,
                        "phone_number_id": phone_number_id,
                        "message_id": message_id,
                        "message_type": messages.get("type"),
                        "messages": messages,
                    },
                )
            except Exception:
                logger.exception("Failed to log inbound webhook payload")

        if is_rate_limited(phone_number):
            logger.warning(
                "Inbound rate limit exceeded — dropping message",
                extra={"phone_number": phone_number, "count": INBOUND_RATE_LIMIT},
            )
            return

        if not message_id:
            logger.warning(
                "Inbound message missing id; cannot dedupe",
                extra={"phone_number": phone_number, "client_id": client_id},
            )
        else:
            if not mark_inbound_processed(
                client_id=client_id,
                phone_number=phone_number,
                message_id=message_id,
            ):
                logger.info(
                    "Duplicate inbound message ignored",
                    extra={
                        "phone_number": phone_number,
                        "client_id": client_id,
                        "message_id": message_id,
                    },
                )
                return

        lock = await _get_user_lock(phone_number)
        async with lock:
            try:
                phone_number_id = (
                    request_data["entry"][0]["changes"][0]["value"]
                    .get("metadata", {})
                    .get("phone_number_id", "")
                )
                if phone_number_id and phone_number_id not in build_phone_number_id_map():
                    logger.debug(
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
                "app_state": app_state,
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
                content = format_user(messages, phone_number)
                if content:
                    save_user_message_silent(phone_number, content, client_id)
                    await pubsub.publish(
                        phone_number,
                        {"type": "user_message", "content": content},
                    )
                touch_last_message_at(phone_number, client_id)
                return

            if message_id:
                stop_typing_event = asyncio.Event()
                typing_task = asyncio.create_task(typing_indicator_loop(message_id, stop_typing_event))

            data = await UserRegistration().process(data)

            non_text_result = handle_non_text_message(data)
            if non_text_result == "silent":
                touch_last_message_at(phone_number, client_id)
                return

            if non_text_result == "route_store" or "bot_response" in data:
                pipeline_start = time.time()
                if non_text_result == "route_store":
                    data = await AdFlowPipeline().run(data=data)
                if "bot_response" not in data and non_text_result == "route_store":
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": (
                                "Sorry, we couldn't look up stores right now. "
                                "Please try again in a moment."
                            ),
                        }
                    ]
                if "bot_response" in data:
                    await _persist_session(data, phone_number, pipeline_start)
                    responses_to_send = data
                if responses_to_send:
                    ResponseManager().handle_responses(data=responses_to_send)
                return

            pipeline_start = time.time()
            data = await InitialPipeline().run(data=data)

            if "bot_response" in data:
                logger.info(
                    "Bot response from initial pipeline",
                    extra={"phone_number": phone_number},
                )
            else:
                service_selected = data.get("user_profile", {}).get(
                    "service_selected", ""
                )
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

                if "bot_response" not in data:
                    logger.warning(
                        "Pipeline completed without bot_response — sending main menu",
                        extra={
                            "phone_number": phone_number,
                            "service_selected": service_selected,
                        },
                    )
                    data["bot_response"] = [build_main_menu_bot_response()]

            if "bot_response" in data:
                await _persist_session(data, phone_number, pipeline_start)
                responses_to_send = data

        if responses_to_send:
            ResponseManager().handle_responses(data=responses_to_send)

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
            except Exception as save_err:
                logger.exception(
                    "Failed to save error response",
                    extra={"exception": save_err},
                )
            else:
                try:
                    ResponseManager().handle_responses(data=data)
                except Exception as send_err:
                    logger.exception(
                        "Failed to send error response",
                        extra={"exception": send_err},
                    )
    finally:
        if stop_typing_event:
            stop_typing_event.set()
        clear_request_context()


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

    if _log_webhook_payload_enabled():
        try:
            logger.info(
                "Inbound webhook payload (raw)",
                extra={
                    "event": "webhook_payload_raw",
                    "request_data": sanitize_for_log(request_data),
                },
            )
        except Exception:
            logger.exception("Failed to log raw webhook payload")

    if "payload" in request_data:
        logger.info("Payload wrapper found, ignoring")
        return JSONResponse(content={"success": True}, status_code=200)

    try:
        whatsapp_event = request_data["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError, TypeError):
        logger.warning(
            "Webhook payload did not match expected Cloud API format",
            extra={"request_data": request_data},
        )
        return JSONResponse(content={"success": True}, status_code=200)

    if _log_webhook_payload_enabled():
        try:
            messages0 = None
            if "messages" in whatsapp_event and whatsapp_event["messages"]:
                messages0 = whatsapp_event["messages"][0]
            logger.info(
                "Inbound webhook payload (value)",
                extra={
                    "metadata": whatsapp_event.get("metadata", {}),
                    "has_statuses": "statuses" in whatsapp_event,
                    "has_messages": "messages" in whatsapp_event,
                    "messages0": messages0,
                    "value": whatsapp_event,
                },
            )
        except Exception:
            logger.exception("Failed to log whatsapp_event payload")

    if "statuses" in whatsapp_event:
        status_item = whatsapp_event["statuses"][0]
        status = status_item.get("type") or status_item.get("status", "unknown")
        logger.info("Ignoring status update", extra={"status": status})
        return JSONResponse(content={"success": True}, status_code=200)

    if "messages" not in whatsapp_event:
        return JSONResponse(content={"success": True}, status_code=200)

    request_id = getattr(request.state, "request_id", None)
    background_tasks.add_task(
        process_message,
        request_data,
        request.app.state,
        request_id=request_id,
    )
    return JSONResponse(content={"success": True}, status_code=200)
