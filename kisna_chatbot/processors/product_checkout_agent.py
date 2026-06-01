import json

from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger


def _parse_button_msgid(raw_id: str) -> str:
    btn_msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            btn_msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    return btn_msgid if isinstance(btn_msgid, str) else raw_id


def _is_buy_button(interactive: dict) -> bool:
    if interactive.get("type") != "button_reply":
        return False
    raw_id = interactive.get("button_reply", {}).get("id", "")
    return _parse_button_msgid(raw_id).startswith("buy$")


def _is_variant_list_reply(messages: dict) -> bool:
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return False
    raw_list_id = interactive.get("list_reply", {}).get("id", "")
    try:
        payload = json.loads(raw_list_id)
        if isinstance(payload, dict):
            msgid = payload.get("msgid", "")
            return isinstance(msgid, str) and msgid.startswith("variant_select$")
    except (json.JSONDecodeError, TypeError):
        pass
    return isinstance(raw_list_id, str) and raw_list_id.startswith("variant_select$")


class ProductCheckoutAgent(Processor):
    """
    Product checkout agent (stub).

    Reserved for buy$ button and variant_select$ list flows (cart / checkout CTA).
    Kisna pre-orders use PreOrderAgent with preorder$ in parallel.
    """

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        user_profile = data.get("user_profile", {})
        if user_profile.get("service_selected") == SL.PRODUCT_CHECKOUT.value:
            return True
        messages = data.get("messages", {})
        interactive = messages.get("interactive", {})
        return _is_buy_button(interactive) or _is_variant_list_reply(messages)

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        if not self.should_run(data):
            return data

        logger.info(
            "ProductCheckoutAgent (stub) processing",
            extra={"phone_number": phone_number},
        )
        data["bot_response"] = [
            {
                "type": "text",
                "text": (
                    "Checkout is being set up. For now, use *Pre-Order* on a product "
                    "or browse our collection from the main menu."
                ),
            }
        ]
        return data
