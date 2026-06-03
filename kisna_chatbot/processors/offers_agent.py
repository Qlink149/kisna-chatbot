from kisna_chatbot.config.clients import get_client_config
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.product_search_agent_v3 import _material_button_msgid
from kisna_chatbot.utils.clara_cache import get_cached_promotions
from kisna_chatbot.utils.logger_config import logger

_EMPTY_OFFERS_TEXT = (
    "No active offers right now. Check back soon — we've got fresh deals coming!"
)
_ERROR_TEXT = (
    "Sorry, we couldn't load offers right now. Please try again in a moment."
)

_FOOTER_LINES = (
    "Making charges are the craftsmanship cost added to gold rate.\n"
    "These offers apply to the making charges portion of your order."
)


def _promo_text_blob(promo: dict) -> str:
    parts = []
    for key in ("materialType", "productType", "type", "category", "name", "title"):
        val = promo.get(key)
        if val:
            parts.append(str(val).lower())
    return " ".join(parts)


def _is_labour_promo(promo: dict) -> bool:
    disc_on = promo.get("discOn")
    if disc_on is None:
        return True
    return disc_on == "Labour"


def _classify_material(promo: dict) -> set[str]:
    blob = _promo_text_blob(promo)
    buckets: set[str] = set()
    if "gold" in blob or "sona" in blob:
        buckets.add("gold")
    if "diamond" in blob or "heera" in blob or "solitaire" in blob:
        buckets.add("diamond")
    if not buckets:
        buckets.update({"gold", "diamond"})
    return buckets


def _tier_sort_key(promo: dict) -> float:
    try:
        return float(promo.get("toAmt", 0))
    except (TypeError, ValueError):
        return 0.0


def _format_tier_line(promo: dict) -> str | None:
    disc = promo.get("disc")
    if disc is None:
        return None
    try:
        disc_val = float(disc)
        disc_str = str(int(disc_val)) if disc_val == int(disc_val) else str(disc_val)
    except (TypeError, ValueError):
        return None

    try:
        to_amt = int(float(promo.get("toAmt", 0)))
    except (TypeError, ValueError):
        to_amt = 0

    return f"• {disc_str}% off making charges — orders below ₹{to_amt:,}"


def _unique_sorted_tiers(promos: list[dict]) -> list[str]:
    seen: set[str] = set()
    lines: list[str] = []
    for promo in sorted(promos, key=_tier_sort_key):
        line = _format_tier_line(promo)
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return lines


def _build_offers_text(promotions: list) -> str:
    gold_promos: list[dict] = []
    diamond_promos: list[dict] = []

    for promo in promotions:
        if not isinstance(promo, dict) or not _is_labour_promo(promo):
            continue
        buckets = _classify_material(promo)
        if "gold" in buckets:
            gold_promos.append(promo)
        if "diamond" in buckets:
            diamond_promos.append(promo)

    parts = ["*Current KISNA Offers* 🎁", ""]

    gold_lines = _unique_sorted_tiers(gold_promos)
    parts.append("*Gold Jewellery*")
    if gold_lines:
        parts.extend(gold_lines)
    else:
        parts.append("• No active gold offers at the moment")
    parts.append("")

    diamond_lines = _unique_sorted_tiers(diamond_promos)
    parts.append("*Diamond Jewellery*")
    if diamond_lines:
        parts.extend(diamond_lines)
    else:
        parts.append("• No active diamond offers at the moment")
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


def _build_error_response() -> list:
    return [{"type": "text", "text": _ERROR_TEXT}]


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

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
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

            promotions = await get_cached_promotions(app_state)

            if not promotions:
                data["bot_response"] = _build_empty_response()
                logger.info(
                    "No active promotions returned",
                    extra={"phone_number": phone_number, "client_id": client_id},
                )
                return data

            offers_text = _build_offers_text(promotions)
            data["bot_response"] = _build_bot_response(offers_text)
            logger.info(
                "Offers loaded successfully",
                extra={
                    "phone_number": phone_number,
                    "client_id": client_id,
                    "promotion_count": len(promotions),
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
