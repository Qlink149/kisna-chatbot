from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.integrations.client_api_adapter import ClientAPIAdapter
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.utils.logger_config import logger

_MAX_OFFERS = 5

_EMPTY_OFFERS_TEXT = (
    "No active offers right now. Check back soon — we've got fresh deals coming!"
)
_ERROR_TEXT = (
    "Sorry, we couldn't load offers right now. Please try again in a moment."
)


def _format_validity(start_date, end_date) -> str:
    if start_date and end_date:
        return f"Valid: {start_date} – {end_date}"
    if start_date:
        return f"Valid from: {start_date}"
    if end_date:
        return f"Valid until: {end_date}"
    return "See terms for validity"


def _format_offer_block(offer: dict) -> str:
    title = offer.get("title") or "Offer"
    lines = [f"*{title}*"]

    description = (offer.get("description") or "").strip()
    if description:
        lines.append(description)

    code = offer.get("code")
    if code:
        lines.append(f"Code: `{code}`")

    discount = offer.get("discount_percent")
    if discount is not None:
        lines.append(f"Discount: {discount}% off")

    min_order = offer.get("min_order_value")
    if min_order is not None:
        lines.append(f"Min order: ₹{min_order}")

    lines.append(_format_validity(offer.get("start_date"), offer.get("end_date")))
    return "\n".join(lines)


def _build_offers_text(offers: list) -> str:
    blocks = [_format_offer_block(offer) for offer in offers[:_MAX_OFFERS]]
    body = "\n\n".join(blocks)
    return f"🎉 *Active offers for you*\n\n🎁 {body}"


def _build_ctas() -> list:
    return [
        {
            "type": "quickreply",
            "text": "Ready to browse our collection?",
            "caption": "",
            "options": [{"title": "Explore Products"}],
            "msgid": "search$explore",
        },
        {
            "type": "quickreply",
            "text": "Need something else?",
            "caption": "",
            "options": [{"title": "Back"}],
            "msgid": "menu$back",
        },
    ]


def _build_bot_response(offers_text: str) -> list:
    return [{"type": "text", "text": offers_text}, *_build_ctas()]


def _build_empty_response() -> list:
    return [{"type": "text", "text": _EMPTY_OFFERS_TEXT}, *_build_ctas()]


def _build_error_response() -> list:
    return [{"type": "text", "text": _ERROR_TEXT}, *_build_ctas()]


class OffersAgent(Processor):
    """Fetches and formats active promotions when the user asks about offers."""

    def should_run(self, data: dict) -> bool:
        """Run when classifier routed to offers and no response yet."""
        if "bot_response" in data:
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

    async def process(self, data: dict) -> dict:
        """Fetch active offers and return formatted WhatsApp response."""
        phone_number = data["phone_number"]
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
            logger.info(
                "Offers requested",
                extra={"phone_number": phone_number, "client_id": client_id},
            )

            offers = await adapter.get_active_offers()

            if not offers:
                data["bot_response"] = _build_empty_response()
                logger.info(
                    "No active offers returned",
                    extra={"phone_number": phone_number, "client_id": client_id},
                )
                return data

            data["bot_response"] = _build_bot_response(
                _build_offers_text(offers)
            )
            logger.info(
                "Offers loaded successfully",
                extra={
                    "phone_number": phone_number,
                    "client_id": client_id,
                    "offer_count": min(len(offers), _MAX_OFFERS),
                },
            )
            return data

        except Exception as e:
            logger.exception(
                "Exception occurred in OffersAgent",
                extra={"phone_number": phone_number, "exception": e},
            )
            data["bot_response"] = _build_error_response()
            return data
        finally:
            await adapter.aclose()
