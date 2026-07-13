import math
import os
import re
import time

from kisna_chatbot.integrations.clara_api import ClaraAPIError, get_stores
from kisna_chatbot.models.service_list import ServiceList as SL
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.entity_extractor import extract_entities
from kisna_chatbot.processors.service_list import (
    build_flow_switch_bot_response,
    build_main_menu_bot_response,
)
from kisna_chatbot.utils.clara_cache import get_cached_stores
from kisna_chatbot.utils.kisna_url_tracking import append_kisna_utm
from kisna_chatbot.utils.logger_config import logger

_MAX_NEAREST_BY_LOCATION = 5
_PINCODE_ONLY_RE = re.compile(r"^\s*([1-9]\d{5})\s*$")

_ASK_PINCODE_TEXT = (
    "Please share your 6-digit pincode and I'll find the nearest KISNA store."
)
_LOCATION_PINCODE_FALLBACK = (
    "Thanks for sharing your location! To find the nearest "
    "KISNA store, please share your PIN code and I'll search "
    "for you. 📍"
)
_UNPARSEABLE_STORE_TEXT = (
    "I couldn't read that pincode or city. Please send a 6-digit pincode "
    "(e.g. 400001) or a city name like Mumbai."
)
# FIX 5: Retry version includes escape tip (shown from 2nd failed attempt onwards)
_UNPARSEABLE_STORE_TEXT_RETRY = (
    "I couldn't read that pincode or city. Please send a 6-digit pincode "
    "(e.g. 400001) or a city name like Mumbai.\n\n"
    "_Tip: Type *menu* or *cancel* to go back to the main menu._"
)
_ESCAPE_RE = re.compile(r"^(menu|cancel|back)$", re.I)
_GENERIC_ERROR = (
    "Sorry, we couldn't look up stores right now. Please try again in a moment."
)


def _store_locator_url() -> str:
    url = (os.getenv("KISNA_STORE_LOCATOR_URL") or "").strip()
    if url:
        return append_kisna_utm(url)
    return append_kisna_utm("https://www.kisna.com/store")


def _store_phone(store: dict) -> str | None:
    for key in ("phone", "phoneNumber", "phone_number", "mobile"):
        val = store.get(key)
        if val:
            return str(val).strip()
    return None


def _exclude_ecom_stores(stores: list) -> list:
    """Remove ECOM warehouse/online-only locations from customer-facing results."""
    return [
        s
        for s in stores
        if isinstance(s, dict) and "ecom" not in _store_name(s).lower()
    ]


def _store_name(store: dict) -> str:
    return (store.get("name") or store.get("title") or "KISNA Store").strip()


def _store_address_line(store: dict) -> str:
    addr = store.get("address")
    if isinstance(addr, str) and addr.strip():
        return addr.strip()
    if not isinstance(addr, dict):
        return (store.get("fullAddress") or store.get("location") or "Address on request").strip()

    line1 = addr.get("line1") or addr.get("street") or ""
    city_raw = addr.get("city")
    if isinstance(city_raw, dict):
        city = city_raw.get("name", "")
    else:
        city = city_raw or ""
    pin = addr.get("pincode") or addr.get("zip") or ""
    location = ", ".join(p for p in (line1, f"{city} {pin}".strip()) if p)
    return location or (store.get("fullAddress") or store.get("location") or "Address on request").strip()


def _store_map_link(store: dict) -> str:
    addr = store.get("address")
    if isinstance(addr, dict):
        return str(addr.get("mapLink") or "").strip()
    return ""


def _build_store_text(store: dict) -> str:
    lines = [f"*{_store_name(store)}*", f"📍 {_store_address_line(store)}"]
    phone = _store_phone(store)
    if phone:
        lines.append(f"📞 {phone}")
    return "\n".join(lines)


def _build_store_responses(stores: list) -> list[dict]:
    """One interactive message per store: details in body, map link as URL button."""
    stores = _exclude_ecom_stores(stores)
    responses: list[dict] = []
    for store in stores:
        if not isinstance(store, dict):
            continue
        text = _build_store_text(store)
        maplink = _store_map_link(store)
        if maplink:
            responses.append(
                {
                    "type": "cta_url",
                    "text": text,
                    "display_text": "View on Map",
                    "url": maplink,
                }
            )
        else:
            responses.append({"type": "text", "text": text})
    return responses


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
            blob = f"{_store_address_line(s)} {_store_name(s)}".lower()
            if pincode in blob or pincode in str(s.get("pincode", "")):
                filtered.append(s)
        stores = filtered
    elif city:
        city_l = city.lower()
        filtered = [
            s
            for s in stores
            if isinstance(s, dict)
            and (
                city_l in _store_name(s).lower()
                or city_l in _store_address_line(s).lower()
            )
        ]
        stores = filtered

    stores = _exclude_ecom_stores(stores)
    return {"stores": stores, "total_count": len(stores)}


def _store_coordinates(store: dict) -> tuple[float, float] | None:
    if not isinstance(store, dict):
        return None
    for lat_key, lng_key in (
        ("latitude", "longitude"),
        ("lat", "lng"),
        ("lat", "lon"),
    ):
        lat = store.get(lat_key)
        lng = store.get(lng_key)
        if lat is not None and lng is not None:
            try:
                return float(lat), float(lng)
            except (TypeError, ValueError):
                continue
    addr = store.get("address")
    if isinstance(addr, dict):
        for lat_key, lng_key in (
            ("latitude", "longitude"),
            ("lat", "lng"),
            ("lat", "lon"),
        ):
            lat = addr.get(lat_key)
            lng = addr.get(lng_key)
            if lat is not None and lng is not None:
                try:
                    return float(lat), float(lng)
                except (TypeError, ValueError):
                    continue
    return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_stores_from_cache(cached: dict, lat: float, lng: float) -> dict:
    ranked: list[tuple[float, dict]] = []
    for store in cached.get("stores") or []:
        coords = _store_coordinates(store)
        if coords is None:
            continue
        distance = _haversine_km(lat, lng, coords[0], coords[1])
        ranked.append((distance, store))
    ranked.sort(key=lambda item: item[0])
    stores = _exclude_ecom_stores(
        [store for _distance, store in ranked[:_MAX_NEAREST_BY_LOCATION]]
    )
    return {"stores": stores, "total_count": len(ranked)}


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
                result = await get_stores(pincode=pincode)
            elif city:
                result = await get_stores(city=city)
            else:
                result = {"stores": [], "total_count": 0}
            stores = _exclude_ecom_stores(result.get("stores") or [])
            return {"stores": stores, "total_count": len(stores)}
        except ClaraAPIError:
            raise
        except Exception:
            if not use_cache_fallback:
                raise
            logger.warning(
                f"Store lookup fallback | live API failed → using cache | "
                f"pincode={pincode or '-'} city={city or '-'}",
                exc_info=True,
                extra={"pincode": pincode, "city": city},
            )

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

        inbound_location = data.get("inbound_location")
        if inbound_location:
            lat = inbound_location.get("lat")
            lng = inbound_location.get("lng")
            if lat is not None and lng is not None and app_state is not None:
                try:
                    cached = await get_cached_stores(app_state)
                    result = _nearest_stores_from_cache(cached, float(lat), float(lng))
                    stores = result.get("stores") or []
                    if stores:
                        data["bot_response"] = _build_store_responses(stores)
                        user_profile["awaiting_store_pincode"] = False
                        user_profile["service_selected"] = ""
                        data.pop("inbound_location", None)
                        return data
                except Exception as e:
                    logger.warning(
                        "Location store lookup failed",
                        extra={"phone_number": phone_number, "error": str(e)},
                    )

            user_profile["awaiting_store_pincode"] = True
            data["bot_response"] = [{"type": "text", "text": _LOCATION_PINCODE_FALLBACK}]
            data.pop("inbound_location", None)
            return data

        user_message = (messages.get("text", {}) or {}).get("body", "") or ""
        user_message = user_message.strip()

        pincode: str | None = None
        city: str | None = None

        try:
            if user_profile.get("awaiting_store_pincode"):
                if _ESCAPE_RE.match(user_message):
                    user_profile["awaiting_store_pincode"] = False
                    user_profile["service_selected"] = ""
                    data["bot_response"] = [build_main_menu_bot_response()]
                    return data

                from kisna_chatbot.processors.classifier import _store_pincode_escape_intent

                escape_intent = _store_pincode_escape_intent(user_message)
                if escape_intent:
                    user_profile["awaiting_store_pincode"] = False
                    user_profile["store_pincode_attempts"] = 0
                    new_service = (
                        SL.PRODUCT_SEARCH.value
                        if escape_intent in ("product_search", "product_info")
                        else {
                            "offers": SL.OFFERS.value,
                            "order_tracking": SL.ORDER_TRACKING.value,
                            "returns_refund": SL.RETURNS_REFUND.value,
                            "complaint": SL.COMPLAINT.value,
                        }.get(escape_intent, SL.GENERAL.value)
                    )
                    # FIX 13: stamp created_at on all pending_flow_switch writes
                    user_profile["pending_flow_switch"] = {
                        "intent": escape_intent,
                        "service": new_service,
                        "created_at": time.time(),
                    }
                    current = user_profile.get("service_selected") or SL.AD_FLOW.value
                    data["bot_response"] = build_flow_switch_bot_response(
                        current, escape_intent
                    )
                    return data

                user_profile["awaiting_store_pincode"] = False
                m = _PINCODE_ONLY_RE.match(user_message)
                if m:
                    pincode = m.group(1)
                else:
                    entities = extract_entities(user_message)
                    pincode = entities.get("pincode")
                    city = entities.get("city")
                if not pincode and not city:
                    # FIX 5: show escape tip from 2nd failed attempt onwards
                    attempts = user_profile.get("store_pincode_attempts", 0) + 1
                    user_profile["store_pincode_attempts"] = attempts
                    reprompt_text = (
                        _UNPARSEABLE_STORE_TEXT_RETRY if attempts >= 2
                        else _UNPARSEABLE_STORE_TEXT
                    )
                    data["bot_response"] = [
                        {"type": "text", "text": reprompt_text}
                    ]
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

            if not stores:
                user_profile["awaiting_store_pincode"] = False
                user_profile["service_selected"] = ""
                user_profile["store_pincode_attempts"] = 0
                data["bot_response"] = [{"type": "text", "text": _zero_results_message()}]
                return data

            data["bot_response"] = _build_store_responses(stores)
            user_profile["awaiting_store_pincode"] = False
            user_profile["service_selected"] = ""
            user_profile["store_pincode_attempts"] = 0
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
