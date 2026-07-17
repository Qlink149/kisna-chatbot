import json
import time

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.database.collections import users
from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter, ClientAPIError
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_MAX_VARIANTS = 10

_GENERIC_ERROR = (
    "Sorry, we couldn't complete your pre-order right now. Please try again."
)


def _parse_button_msgid(raw_id: str) -> str:
    """Extract msgid from a Gupshup button id (plain or JSON-encoded)."""
    btn_msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            btn_msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    return btn_msgid if isinstance(btn_msgid, str) else raw_id


def _parse_preorder_product_id(raw_id: str) -> str | None:
    """Return product_id if button id/msgid starts with preorder$, else None."""
    btn_msgid = _parse_button_msgid(raw_id)
    if btn_msgid.startswith("preorder$"):
        return btn_msgid.split("$", 1)[1]
    return None


def _parse_variant_list_reply(list_reply: dict) -> tuple[str, str] | None:
    """
    Parse list_reply id JSON into (product_id, variant_id).

    Expected payload: {"msgid": "variant_select$<product_id>", "postbackText": "<variant_id>"}
    """
    raw_list_id = list_reply.get("id", "")
    variant_id = ""
    list_msgid = raw_list_id

    try:
        list_payload = json.loads(raw_list_id)
        if isinstance(list_payload, dict):
            list_msgid = list_payload.get("msgid", raw_list_id)
            variant_id = list_payload.get("postbackText", "")
    except (json.JSONDecodeError, TypeError):
        pass

    if not isinstance(list_msgid, str) or not list_msgid.startswith("variant_select$"):
        return None
    if not variant_id:
        return None

    product_id = list_msgid.split("$", 1)[1]
    return product_id, str(variant_id)


def _build_variant_text_response(variants: list[dict]) -> dict:
    """Build a plain-text numbered variant prompt for pre-order selection."""
    lines = ["This design comes in a few options:"]
    for idx, variant in enumerate(variants[:_MAX_VARIANTS], start=1):
        label = variant.get("label") or "Option"
        price = variant.get("price")
        price_part = f" — ₹{price}" if price is not None else ""
        lines.append(f"{idx}. {label}{price_part}")
    lines.append("Just reply with the number you'd like 😊")
    return {"type": "text", "text": "\n".join(lines)}


def _set_pending_variant_select(
    user_profile: dict, product_id: str, variants: list[dict]
) -> None:
    user_profile["pending_variant_select"] = {
        "product_id": product_id,
        "variants": [
            {
                "id": str(v.get("id", "")),
                "label": v.get("label") or "Option",
                "price": v.get("price"),
            }
            for v in variants[:_MAX_VARIANTS]
        ],
        "created_at": int(time.time()),
    }


def match_pending_variant(user_profile: dict, text: str) -> dict | None:
    """Match a text reply (number or label) against pending variant options."""
    pending = user_profile.get("pending_variant_select")
    if not isinstance(pending, dict):
        return None
    variants = pending.get("variants") or []
    normalized = (text or "").strip().lower().rstrip(".")
    if not normalized or not variants:
        return None
    if normalized.isdigit():
        idx = int(normalized)
        if 1 <= idx <= len(variants):
            return variants[idx - 1]
        return None
    for variant in variants:
        if (variant.get("label") or "").strip().lower() == normalized:
            return variant
    return None


def _build_error_response(text: str) -> list:
    return [{"type": "text", "text": text}]


def _build_success_response(pre_order: dict, variant_label: str = "") -> list:
    """Build confirmation text and payment CTA."""
    pre_order_id = pre_order.get("id") or pre_order.get("pre_order_id") or "N/A"
    estimated_delivery = pre_order.get("estimated_delivery") or "We'll confirm soon"
    payment_url = pre_order.get("payment_url")

    variant_line = f"\n*{variant_label}*" if variant_label else ""
    text = (
        "🎉 *Pre-order confirmed!*\n\n"
        f"✅ Pre-order ID: *{pre_order_id}*{variant_line}\n"
        f"📅 Estimated delivery: *{estimated_delivery}*\n\n"
        "💰 Complete payment using the button below to secure your order."
    )

    if not payment_url:
        return _build_error_response(
            "Your pre-order was created but we couldn't generate a payment link. "
            "Please contact our team for assistance."
        )

    return [
        {"type": "text", "text": text},
        {
            "type": "cta_url",
            "text": "Your pre-order is reserved. Tap below to pay securely.",
            "display_text": "Pay Now",
            "url": payment_url,
        },
    ]


def _append_pre_order(
    user_profile: dict,
    *,
    pre_order_id: str,
    product_id: str,
    variant_id: str,
    estimated_delivery,
) -> list:
    pre_orders = list(user_profile.get("pre_orders") or [])
    pre_orders.append(
        {
            "pre_order_id": pre_order_id,
            "product_id": product_id,
            "variant_id": variant_id,
            "status": "awaiting_payment",
            "created_at": int(time.time()),
            "estimated_delivery": estimated_delivery,
        }
    )
    user_profile["pre_orders"] = pre_orders
    return pre_orders


def _persist_pre_orders(phone_number: str, client_id: str, pre_orders: list) -> None:
    users.update_one(
        {"phone_number": phone_number, "client_id": client_id},
        {"$set": {"pre_orders": pre_orders, "updated_at": int(time.time())}},
    )


class PreOrderAgent(Processor):
    """
    Handles pre-order flow: variant selection (list) then payment CTA.

    Step 1 — preorder$ button: fetch variants, show list if multiple.
    Step 2 — variant_select$ list reply or single variant: create pre-order.
    """

    def should_run(self, data: dict) -> bool:
        """Run for preorder$ buttons, variant list replies, or pending text picks."""
        if "bot_response" in data:
            return False

        messages = data.get("messages", {})
        interactive = messages.get("interactive", {})
        interactive_type = interactive.get("type")

        if interactive_type == "button_reply":
            raw_id = interactive.get("button_reply", {}).get("id", "")
            return _parse_preorder_product_id(raw_id) is not None

        if interactive_type == "list_reply":
            list_reply = interactive.get("list_reply", {})
            return _parse_variant_list_reply(list_reply) is not None

        if "text" in messages:
            user_profile = data.get("user_profile", {})
            text = (messages.get("text", {}) or {}).get("body", "")
            return match_pending_variant(user_profile, text) is not None

        return False

    async def _complete_pre_order(
        self,
        data: dict,
        adapter: ClientAPIAdapter,
        *,
        phone_number: str,
        client_id: str,
        product_id: str,
        variant_id: str,
        variant_label: str = "",
    ) -> dict:
        logger.info(
            "Creating pre-order",
            extra={
                "phone_number": phone_number,
                "product_id": product_id,
                "variant_id": variant_id,
                "client_id": client_id,
            },
        )

        result = await adapter.create_pre_order(
            product_id, variant_id, phone_number, quantity=1
        )

        pre_order_id = result.get("id") or ""
        user_profile = data["user_profile"]
        pre_orders = _append_pre_order(
            user_profile,
            pre_order_id=pre_order_id,
            product_id=product_id,
            variant_id=variant_id,
            estimated_delivery=result.get("estimated_delivery"),
        )
        _persist_pre_orders(phone_number, client_id, pre_orders)

        data["bot_response"] = _build_success_response(result, variant_label)
        logger.info(
            "Pre-order created successfully",
            extra={
                "phone_number": phone_number,
                "pre_order_id": pre_order_id,
                "product_id": product_id,
            },
        )
        return data

    async def process(self, data: dict) -> dict:
        """Process pre-order button or variant list selection."""
        phone_number = data["phone_number"]
        messages = data.get("messages", {})
        user_profile = data.get("user_profile", {})
        client_id = data.get("client_id", "kisna")
        client_config = data.get("client_config") or get_client_config(client_id)

        if not self.should_run(data):
            logger.info(
                "Skipping processor",
                extra={
                    "processor": self.__class__.__name__,
                    "phone_number": phone_number,
                },
            )
            return data

        adapter = ClientAPIAdapter(client_config)
        try:
            interactive = messages.get("interactive", {})
            interactive_type = interactive.get("type")

            if interactive_type == "button_reply":
                raw_id = interactive["button_reply"]["id"]
                product_id = _parse_preorder_product_id(raw_id)
                if not product_id:
                    logger.warning(
                        "Could not parse product id from preorder button",
                        extra={"phone_number": phone_number, "raw_id": raw_id},
                    )
                    return data

                logger.info(
                    "Pre-order requested",
                    extra={
                        "phone_number": phone_number,
                        "product_id": product_id,
                        "client_id": client_id,
                    },
                )

                variants = await adapter.get_product_variants(product_id)
                variants = [v for v in variants if v.get("available", True)]

                if not variants:
                    data["bot_response"] = _build_error_response(
                        "Sorry, no variants are available for this product right now."
                    )
                    return data

                if len(variants) == 1:
                    variant = variants[0]
                    return await self._complete_pre_order(
                        data,
                        adapter,
                        phone_number=phone_number,
                        client_id=client_id,
                        product_id=product_id,
                        variant_id=str(variant.get("id", "")),
                        variant_label=variant.get("label") or "",
                    )

                _set_pending_variant_select(user_profile, product_id, variants)
                data["bot_response"] = [_build_variant_text_response(variants)]
                return data

            if "text" in messages:
                text = (messages.get("text", {}) or {}).get("body", "")
                matched = match_pending_variant(user_profile, text)
                pending = user_profile.pop("pending_variant_select", None) or {}
                if matched and pending.get("product_id"):
                    return await self._complete_pre_order(
                        data,
                        adapter,
                        phone_number=phone_number,
                        client_id=client_id,
                        product_id=str(pending["product_id"]),
                        variant_id=str(matched.get("id", "")),
                        variant_label=matched.get("label") or "",
                    )
                return data

            if interactive_type == "list_reply":
                list_reply = interactive["list_reply"]
                parsed = _parse_variant_list_reply(list_reply)
                if not parsed:
                    logger.warning(
                        "Could not parse variant list reply",
                        extra={"phone_number": phone_number},
                    )
                    return data

                product_id, variant_id = parsed
                variant_label = list_reply.get("title", "")
                return await self._complete_pre_order(
                    data,
                    adapter,
                    phone_number=phone_number,
                    client_id=client_id,
                    product_id=product_id,
                    variant_id=variant_id,
                    variant_label=variant_label,
                )

            return data

        except ClientAPIError as e:
            logger.exception(
                "Pre-order API error",
                extra={"phone_number": phone_number, "error": str(e)},
            )
            data["bot_response"] = _build_error_response(_GENERIC_ERROR)
            return data
        except Exception as e:
            logger.exception(
                "Exception occurred in PreOrderAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = _build_error_response(_GENERIC_ERROR)
            return data
        finally:
            await adapter.aclose()
