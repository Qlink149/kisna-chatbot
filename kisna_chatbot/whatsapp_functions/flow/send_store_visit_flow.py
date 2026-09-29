import secrets

import httpx

from kisna_chatbot.config.store_visit import FLOW_TOKEN_PREFIX, get_store_visit_flow_id
from kisna_chatbot.processors.store_visit_flow import remember_send
from kisna_chatbot.prompts.form_copy import STORE_VISIT_PREFORM, fit_flow_body
from kisna_chatbot.stores import cache as store_cache
from kisna_chatbot.utils.env_load import gupshup_app_id, gupshup_token
from kisna_chatbot.utils.logger_config import logger


def new_flow_token(flow_id: str) -> str:
    """Unique per form sent: the submission idempotency key."""
    return f"{FLOW_TOKEN_PREFIX}:{flow_id}:{secrets.token_hex(8)}"


def store_visit_form_available() -> bool:
    """False when the Flow id is unset or no store is bookable -- the caller
    then sends the store locator link instead of the form."""
    if not get_store_visit_flow_id():
        return False
    try:
        return bool(store_cache.list_states())
    except Exception:
        logger.exception("Store list unavailable; store visit form not offered")
        return False


def send_store_visit_flow(
    phone_number: str,
    body_text: str | None = None,
    first_name: str = "",
):
    """Send the Store Visit Flow with flow_action data_exchange: WhatsApp asks
    the endpoint for the first screen (INIT), which prefills the WhatsApp
    profile name and this number saved here under the form's flow_token.
    Returns None (nothing sent) when the form is unavailable."""
    flow_id = get_store_visit_flow_id()
    if not store_visit_form_available():
        logger.warning(
            "Store visit form unavailable (flow id unset or no bookable stores)",
            extra={"phone_number": phone_number, "flow_id_set": bool(flow_id)},
        )
        return None

    flow_token = new_flow_token(flow_id)
    try:
        # INIT reads this back to prefill First Name and Phone No.
        remember_send(flow_token, first_name, phone_number)
    except Exception:
        logger.exception(
            "Store visit prefill not saved; form opens without it",
            extra={"phone_number": phone_number},
        )
    url = f"https://partner.gupshup.io/partner/app/{gupshup_app_id}/v3/message"
    headers = {
        "Authorization": f"{gupshup_token}",
        "Content-Type": "application/json",
    }
    data = {
        "recipient_type": "individual",
        "messaging_product": "whatsapp",
        "to": f"{phone_number}",
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "header": {"type": "text", "text": "Store Visit"},
            "body": {"text": fit_flow_body(body_text, STORE_VISIT_PREFORM)},
            "footer": {"text": "Kisna"},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_token": flow_token,
                    "flow_id": flow_id,
                    "flow_message_version": "3",
                    # The first screen comes from the endpoint's INIT, the
                    # same path Meta's interactive preview uses; Meta requires
                    # no flow_action_payload with data_exchange.
                    "flow_action": "data_exchange",
                    "flow_cta": "Book a Store Visit",
                },
            },
        },
    }
    logger.info(
        "Sending store visit flow",
        extra={"phone_number": phone_number, "flow_id": flow_id},
    )
    try:
        response = httpx.post(url, headers=headers, json=data, timeout=30)
    except Exception as e:
        logger.error(
            "Error sending store visit flow",
            extra={"phone_number": phone_number, "error": str(e)},
        )
        raise
    body = response.json()
    logger.info(
        "Store visit flow API response",
        extra={"status_code": response.status_code, "body": body},
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Gupshup flow send failed: HTTP {response.status_code} — {body}"
        )
    return body
