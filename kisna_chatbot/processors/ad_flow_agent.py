import os
import re

from kisna_chatbot.integrations.clara_api import ClaraAPIError, get_stores
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.entity_extractor import extract_entities
from kisna_chatbot.utils.clara_cache import get_cached_stores
from kisna_chatbot.utils.logger_config import logger

_MAX_STORES_SHOWN = 5
_PINCODE_ONLY_RE = re.compile(r"^\s*([1-9]\d{5})\s*$")

_ASK_PINCODE_TEXT = (
    "Please share your 6-digit pincode and I'll find the nearest KISNA store."
)
_GENERIC_ERROR = (
    "Sorry, we couldn't look up stores right now. Please try again in a moment."
)


def _store_locator_url() -> str:
    url = (os.getenv("KISNA_STORE_LOCATOR_URL") or "").strip()
    if url:
        return url
    domain = (os.getenv("KISNA_WEBSITE_DOMAIN") or "www.kisna.com").strip()
    return f"https://{domain}/stores"


def _store_phone(store: dict) -> str | None:
    for key in ("phone", "phoneNumber", "phone_number", "mobile"):
        val = store.get(key)
        if val:
            return str(val).strip()
    return None


def _store_name(store: dict) -> str:
    return (store.get("name") or store.get("title") or "KISNA Store").strip()


def _store_address(store: dict) -> str:
    addr = store.get("address")
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    if isinstance(addr, dict):
        parts = [
            addr.get("line1") or addr.get("street"),
            addr.get("city"),
            addr.get("state"),
            addr.get("pincode") or addr.get("zip"),
        ]
        return ", ".join(p for p in parts if p)
    return (store.get("fullAddress") or store.get("location") or "Address on request").strip()


def _format_stores_message(stores: list, total_count: int) -> str:
    lines: list[str] = []
    for store in stores[:_MAX_STORES_SHOWN]:
        if not isinstance(store, dict):
            continue
        lines.append(f"*{_store_name(store)}*")
        lines.append(f"📍 {_store_address(store)}")
        phone = _store_phone(store)
        if phone:
            lines.append(f"📞 {phone}")
        lines.append("")

    if total_count > _MAX_STORES_SHOWN:
        lines.append(f"and {total_count - _MAX_STORES_SHOWN} more stores near you")

    return "\n".join(lines).strip()


def _zero_results_message() -> str:
    return (
        "No KISNA stores found near you.\n"
        f"Browse all locations: {_store_locator_url()}"
    )


def _filter_cached_stores(
    cached: dict,
    *,
    pincode: str | None = None,
    city: str | None = None,
) -> dict:
    stores = list(cached.get("stores") or [])
    if pincode:
        filtered = []
        for s in stores:
            if not isinstance(s, dict):
                continue
            blob = f"{_store_address(s)} {_store_name(s)}".lower()
            if pincode in blob or pincode in str(s.get("pincode", "")):
                filtered.append(s)
        stores = filtered or stores
    elif city:
        city_l = city.lower()
        filtered = [
            s
            for s in stores
            if isinstance(s, dict)
            and (
                city_l in _store_name(s).lower()
                or city_l in _store_address(s).lower()
            )
        ]
        stores = filtered

    return {"stores": stores[:_MAX_STORES_SHOWN], "total_count": len(stores)}


class AdFlowAgent(Processor):
    """Store locator via Clara API with pincode/city entity extraction."""

    def should_run(self, data: dict) -> bool:
        if "bot_response" in data:
            return False

        user_profile = data.get("user_profile", {})
        if user_profile.get("awaiting_store_pincode"):
            return True
        if data.get("classified_category") == "store_info":
            return True
        return user_profile.get("service_selected") == SL.AD_FLOW.value

    async def _fetch_stores(
        self,
        *,
        pincode: str | None = None,
        city: str | None = None,
        app_state,
        use_cache_fallback: bool = False,
    ) -> dict:
        try:
            if pincode:
                return await get_stores(pincode=pincode, page_size=_MAX_STORES_SHOWN)
            if city:
                return await get_stores(name=city, page_size=_MAX_STORES_SHOWN)
        except ClaraAPIError:
            raise
        except Exception:
            if not use_cache_fallback:
                raise
            logger.warning("Live store lookup failed; trying cache", exc_info=True)

        if use_cache_fallback and app_state is not None:
            cached = await get_cached_stores(app_state)
            return _filter_cached_stores(cached, pincode=pincode, city=city)

        return {"stores": [], "total_count": 0}

    async def process(self, data: dict) -> dict:
        phone_number = data["phone_number"]
        user_profile = data.get("user_profile", {})
        messages = data.get("messages", {})
        app_state = data.get("app_state")

        if not self.should_run(data):
            return data

        user_message = (messages.get("text", {}) or {}).get("body", "") or ""
        user_message = user_message.strip()

        pincode: str | None = None
        city: str | None = None

        try:
            if user_profile.get("awaiting_store_pincode"):
                user_profile["awaiting_store_pincode"] = False
                m = _PINCODE_ONLY_RE.match(user_message)
                if m:
                    pincode = m.group(1)
                else:
                    entities = extract_entities(user_message)
                    pincode = entities.get("pincode")
                    city = entities.get("city")
                if not pincode and not city:
                    data["bot_response"] = [{"type": "text", "text": _ASK_PINCODE_TEXT}]
                    user_profile["awaiting_store_pincode"] = True
                    return data
            else:
                entities = extract_entities(user_message) if user_message else {}
                pincode = entities.get("pincode")
                city = entities.get("city")

                if not pincode and not city:
                    user_profile["awaiting_store_pincode"] = True
                    data["bot_response"] = [{"type": "text", "text": _ASK_PINCODE_TEXT}]
                    return data

            logger.info(
                "Store lookup",
                extra={
                    "phone_number": phone_number,
                    "pincode": pincode,
                    "city": city,
                },
            )

            try:
                result = await self._fetch_stores(
                    pincode=pincode,
                    city=city,
                    app_state=app_state,
                )
            except ClaraAPIError as e:
                logger.exception(
                    "Store lookup failed",
                    extra={"phone_number": phone_number, "error": str(e)},
                )
                try:
                    result = await self._fetch_stores(
                        pincode=pincode,
                        city=city,
                        app_state=app_state,
                        use_cache_fallback=True,
                    )
                except Exception:
                    data["bot_response"] = [{"type": "text", "text": e.args[0]}]
                    return data
            except Exception as e:
                logger.exception(
                    "Unexpected store lookup error",
                    extra={"phone_number": phone_number, "error": str(e)},
                )
                result = await self._fetch_stores(
                    pincode=pincode,
                    city=city,
                    app_state=app_state,
                    use_cache_fallback=True,
                )

            stores = result.get("stores") or []
            total_count = int(result.get("total_count") or len(stores))

            if not stores:
                fallback = await self._fetch_stores(
                    pincode=pincode,
                    city=city,
                    app_state=app_state,
                    use_cache_fallback=True,
                )
                stores = fallback.get("stores") or []
                total_count = int(fallback.get("total_count") or len(stores))

            if not stores:
                data["bot_response"] = [{"type": "text", "text": _zero_results_message()}]
                return data

            text = _format_stores_message(stores, total_count)
            data["bot_response"] = [{"type": "text", "text": text}]
            return data

        except ClaraAPIError as e:
            logger.exception(
                "Store lookup failed",
                extra={"phone_number": phone_number, "error": str(e)},
            )
            data["bot_response"] = [{"type": "text", "text": e.args[0]}]
            return data
        except Exception as e:
            logger.exception(
                "AdFlowAgent error",
                extra={"phone_number": phone_number, "error": str(e)},
            )
            data["bot_response"] = [{"type": "text", "text": _GENERIC_ERROR}]
            return data
