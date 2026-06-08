import os

from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.integrations.clara_api import ClaraAPIError, get_promotions
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.product_search_agent_v3 import _material_button_msgid
from kisna_chatbot.utils.clara_cache import get_cached_promotions
from kisna_chatbot.utils.logger_config import logger

_EMPTY_OFFERS_TEXT = (
    "No active offers right now. Check back soon — we've got fresh deals coming!"
)
_PARTIAL_OFFERS_TEXT = (
    "We have promotions available but none match making-charge offers right now. "
    "Browse pieces below:"
)
_ERROR_TEXT = (
    "Sorry, we couldn't load offers right now. Please try again in a moment."
)

_FOOTER_LINES = (
    "_Making charges are the craftsmanship cost added to the gold rate._\n"
    "_These offers apply to the making charges portion of your order._"
)


def _is_labour_promo(promo: dict) -> bool:
    disc_on = (promo.get("discOn") or "").strip().lower()
    if not disc_on:
        return True
    return disc_on in ("labour", "making charges", "making charge")


def _format_amount_range(promo: dict) -> str:
    try:
        from_amt = int(float(promo.get("fromAmt", 0)))
    except (TypeError, ValueError):
        from_amt = 0
    try:
        to_amt = int(float(promo.get("toAmt", 0)))
    except (TypeError, ValueError):
        to_amt = 0

    if from_amt == 0:
        return f"up to ₹{to_amt:,}"
    if to_amt >= 999999999:
        return f"₹{from_amt:,} and above"
    return f"₹{from_amt:,} – ₹{to_amt:,}"


def _format_promo_line(promo: dict) -> str | None:
    label = promo.get("discountLable") or promo.get("discountLabel") or ""
    label = label.replace(" %", "%")
    if not label:
        disc = promo.get("disc") or promo.get("discount")
        disc_on = promo.get("discOn") or "Making Charges"
        if disc is None:
            return None
        try:
            disc_val = int(float(disc))
        except (TypeError, ValueError):
            return None
        label = f"{disc_val}% off on {disc_on}"
    return f"• {label} — {_format_amount_range(promo)}"


def _sorted_category_promos(promos: list[dict], category: str) -> list[dict]:
    return sorted(
        [
            p
            for p in promos
            if isinstance(p, dict)
            and p.get("category", "").lower() == category
        ],
        key=lambda p: p.get("fromAmt", 0),
    )


def _build_offers_text(promotions: list) -> str:
    labour_promos = [
        p for p in promotions if isinstance(p, dict) and _is_labour_promo(p)
    ]

    diamond_promos = _sorted_category_promos(labour_promos, "diamond")
    gold_promos = _sorted_category_promos(labour_promos, "gold")

    parts = ["*Current KISNA Offers* 🎁", ""]

    parts.append("*Diamond Jewellery*")
    diamond_lines = [
        line
        for p in diamond_promos
        if (line := _format_promo_line(p)) is not None
    ]
    if diamond_lines:
        parts.extend(diamond_lines)
    else:
        parts.append("• No active diamond offers at the moment")
    parts.append("")

    parts.append("*Gold Jewellery*")
    gold_lines = [
        line for p in gold_promos if (line := _format_promo_line(p)) is not None
    ]
    if gold_lines:
        parts.extend(gold_lines)
    else:
        parts.append("• No active gold offers at the moment")
    parts.append("")
    parts.append(_FOOTER_LINES)

    return "\n".join(parts)


def _build_material_ctas() -> list[dict]:
    return [
        {
            "type": "quickreply",
            "text": "Want to see pieces with these offers?",
            "caption": "",
            "options": [{"title": "Browse Gold"}],
            "msgid": "search$material$gold",
        },
        {
            "type": "quickreply",
            "text": "Or browse diamond pieces:",
            "caption": "",
            "options": [{"title": "Browse Diamond"}],
            "msgid": "search$material$diamond",
        },
    ]


def _build_bot_response(offers_text: str) -> list:
    return [{"type": "text", "text": offers_text}, *_build_material_ctas()]


def _build_empty_response() -> list:
    return [{"type": "text", "text": _EMPTY_OFFERS_TEXT}, *_build_material_ctas()]


def _build_partial_response() -> list:
    return [{"type": "text", "text": _PARTIAL_OFFERS_TEXT}, *_build_material_ctas()]


def _clara_configured() -> bool:
    return bool(
        (os.getenv("KISNA_CLARA_BASE_URL") or "").strip()
        and (os.getenv("CLARA_API_KEY") or "").strip()
    )


def _build_error_response() -> list:
    return [{"type": "text", "text": _ERROR_TEXT}, *_build_material_ctas()]


class OffersAgent(Processor):
    """Fetches and formats active promotions from Clara API (cached)."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False
        if _material_button_msgid(data.get("messages", {})):
            return False
        user_profile = data.get("user_profile", {})
        if (
            data.get("classified_category") != "offers"
            and user_profile.get("service_selected") != "offers"
        ):
            return False

        client_config = data.get("client_config") or get_client_config(
            data.get("client_id", "kisna")
        )
        return client_config.has_offers

    def _clear_offers_session(self, data: dict, user_profile: dict) -> None:
        if _material_button_msgid(data.get("messages", {})):
            return
        user_profile["service_selected"] = ""

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        user_profile = data.get("user_profile", {})
        client_id = data.get("client_id", "kisna")
        app_state = data.get("app_state")

        if not self.should_run(data):
            logger.info(
                "Skipping processor",
                extra={
                    "processor": self.__class__.__name__,
                    "phone_number": phone_number,
                },
            )
            return data

        try:
            logger.info(
                "Offers requested",
                extra={"phone_number": phone_number, "client_id": client_id},
            )

            if not _clara_configured():
                data["bot_response"] = _build_error_response()
                self._clear_offers_session(data, user_profile)
                logger.warning(
                    "Offers requested but Clara API is not configured",
                    extra={"phone_number": phone_number, "client_id": client_id},
                )
                return data

            promotions = await get_cached_promotions(app_state)

            if not promotions:
                try:
                    promotions = await get_promotions() or []
                except ClaraAPIError:
                    data["bot_response"] = _build_error_response()
                    self._clear_offers_session(data, user_profile)
                    return data
                except Exception:
                    data["bot_response"] = _build_error_response()
                    self._clear_offers_session(data, user_profile)
                    return data

            if not promotions:
                data["bot_response"] = _build_empty_response()
                self._clear_offers_session(data, user_profile)
                logger.info(
                    "No active promotions returned",
                    extra={"phone_number": phone_number, "client_id": client_id},
                )
                return data

            labour_promos = [
                p for p in promotions if isinstance(p, dict) and _is_labour_promo(p)
            ]
            logger.info(
                "Offers promotion filter",
                extra={
                    "phone_number": phone_number,
                    "client_id": client_id,
                    "raw_promotion_count": len(promotions),
                    "labour_promotion_count": len(labour_promos),
                },
            )
            if not labour_promos:
                if promotions:
                    data["bot_response"] = _build_partial_response()
                else:
                    data["bot_response"] = _build_empty_response()
                self._clear_offers_session(data, user_profile)
                return data

            offers_text = _build_offers_text(promotions)
            data["bot_response"] = _build_bot_response(offers_text)
            self._clear_offers_session(data, user_profile)
            logger.info(
                "Offers loaded successfully",
                extra={
                    "phone_number": phone_number,
                    "client_id": client_id,
                    "promotion_count": len(promotions),
                    "labour_promotion_count": len(labour_promos),
                },
            )
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in OffersAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = _build_error_response()
            self._clear_offers_session(data, user_profile)
            return data
