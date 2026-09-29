"""Client-approved customer copy for the forms and the handoff fallback (P3).

Every string here is the client's wording, confirmed in writing, emoji
included. Keep it verbatim: the confirmation builders only insert the request
ID and the booked slot. English is sent as-is; other languages get a faithful
compose() translation with the tokens in ``confirmation_pins`` kept unchanged.
"""

from __future__ import annotations

from datetime import datetime

from kisna_chatbot.utils.support_hours import is_within_working_hours

BRAND = "Kisna Diamond & Gold"

# ---------------------------------------------------------------- pre-form
COMPLAINT_PREFORM = (
    "We're here to help! 💙 Please share the details of your concern below, "
    "and our support team will review it and get back to you shortly."
)
# Callback and video callback share one pre-form message.
CALLBACK_PREFORM = (
    "✨ We'd be happy to assist you! Please share your details below, and our "
    "jewellery expert will connect with you at your preferred time. 📞💎"
)
VIDEO_CALL_PREFORM = CALLBACK_PREFORM
STORE_VISIT_PREFORM = (
    "Would you like to schedule a store visit? 💎\n"
    "Please share your details below, and our jewellery expert will get in "
    "touch with you to assist with your visit. ✨"
)

# ------------------------------------------------------------ confirmations
COMPLAINT_RESPONSE_TIME = "1 working day"


def complaint_confirmation(request_id: str) -> str:
    return "\n".join(
        [
            f"Thank you for reaching out to {BRAND}. 💙",
            "Your complaint has been successfully registered. 📝",
            f"Request ID: {request_id}",
            "Our support team will review your concern and get in touch with "
            f"you within {COMPLAINT_RESPONSE_TIME}.",
            "We appreciate your patience and thank you for choosing Kisna. ✨",
        ]
    )


def _clock(hour: int) -> str:
    """13 -> "1:00 PM", 10 -> "10:00 AM", 12 -> "12:00 PM"."""
    suffix = "AM" if hour < 12 else "PM"
    return f"{(hour - 1) % 12 + 1}:00 {suffix}"


def format_scheduled_for(iso_date: str, slot_id: str) -> str:
    """The client's "Scheduled for" format: "29 September 2026 · 10:00 AM–1:00 PM".

    ``slot_id`` is the booked slot ("10-13", or a legacy id, normalised to its
    block). Anything unparseable is passed through rather than guessed. The
    stored ``preferred_time_label`` (Mongo, dashboard, Clara event) is a
    separate field and keeps its existing format.
    """
    from datetime import date as _date

    from kisna_chatbot.utils.support_slots import normalize_slot_id

    try:
        day = _date.fromisoformat(iso_date)
        date_text = f"{day.day} {day.strftime('%B')} {day.year}"
    except (TypeError, ValueError):
        date_text = iso_date or ""
    block = normalize_slot_id(slot_id, iso_date) if slot_id else ""
    start, _, end = block.partition("-")
    if start.isdigit() and end.isdigit():
        slot_text = f"{_clock(int(start))}–{_clock(int(end))}"
    else:
        slot_text = slot_id or ""
    return f"{date_text} · {slot_text}" if date_text and slot_text else ""


_RESCHEDULED_LINE = (
    "Your preferred slot was full, so we booked the next available time for you."
)


def callback_confirmation(
    request_id: str,
    request_type: str,
    *,
    scheduled_for: str,
    now: datetime | None = None,
    was_rescheduled: bool = False,
) -> str:
    """Callback / video-callback confirmation.

    The variant is chosen by whether the submission happens inside working
    hours (support_hours.is_within_working_hours -- Mon–Fri 10:00–18:30, Sat
    10:00–16:00 IST, Sunday and holidays closed). ``scheduled_for`` is the
    existing "{date} · {slot}" text, unchanged. The rescheduled line is not in
    the client's copy; it is added only when the booked slot differs from the
    one the customer picked, because a changed slot must never go unsaid.
    """
    video = request_type == "video_call"
    label = "video callback" if video else "callback"
    open_now = is_within_working_hours(now)
    lines = [f"Thank you for reaching out to {BRAND}! 💎"]
    if open_now:
        lines.append(f"Your {label} request has been successfully registered. 📞")
    else:
        lines.append(
            f"Our team is currently offline, but your {label} request has been "
            "successfully registered. 📞"
        )
    lines.append(f"Request ID: {request_id}")
    lines.append(f"Scheduled for: {scheduled_for}")
    if was_rescheduled:
        lines.append(_RESCHEDULED_LINE)
    lines.append(
        "Our jewellery expert will connect with you during your selected time slot. ✨"
    )
    if open_now:
        lines.append(
            "We appreciate your patience and look forward to assisting you!"
            if video
            else "We appreciate your patience and look forward to assisting you."
        )
    elif video:
        lines.append("Thank you for your patience. We look forward to assisting you!")
    return "\n".join(lines)


def format_visit_scheduled_for(iso_date: str, hhmm: str) -> str:
    """Store visit "Scheduled for": "29 September 2026 · 11:00 AM"."""
    from datetime import date as _date

    from kisna_chatbot.utils.store_visit_slots import clock_label

    try:
        day = _date.fromisoformat(iso_date)
        date_text = f"{day.day} {day.strftime('%B')} {day.year}"
    except (TypeError, ValueError):
        date_text = iso_date or ""
    try:
        time_text = clock_label(hhmm)
    except (AttributeError, ValueError):
        time_text = hhmm or ""
    return f"{date_text} · {time_text}" if date_text and time_text else ""


def store_visit_confirmation(
    request_id: str, store_line: str, scheduled_for: str
) -> str:
    """``store_line`` is "{store name}, {address}"."""
    return "\n".join(
        [
            "Your appointment is confirmed! 📍✨",
            f"Request ID: {request_id}",
            f"Store: {store_line}",
            f"Scheduled for: {scheduled_for}",
            "Our store jewellery expert will get in touch with you shortly to "
            "assist with your visit.",
            "We appreciate your patience and look forward to welcoming you. 💎",
            f"Thank you for choosing {BRAND}! 💙",
        ]
    )


def store_visit_pins(
    request_id: str, store_name: str, address: str, scheduled_for: str
) -> tuple[str, ...]:
    """Request ID, store name, address, date and time stay verbatim."""
    pins = list(confirmation_pins(request_id, scheduled_for))
    pins.extend(p for p in (store_name, address) if p)
    return tuple(pins)


# -------------------------------------------------- 5-minute handoff fallback
HANDOFF_FALLBACK = "\n".join(
    [
        "Apologies for the delayed response. 🙏",
        "We're currently experiencing a high volume of inquiries, which may "
        "result in a slightly longer response time than usual. Please rest "
        "assured that our team is working diligently to assist you as soon as "
        "possible.",
        "✨ We'd be delighted to assist you! Please share your details below, "
        "and one of our jewellery experts will connect with you at your "
        "preferred time. 📞💎",
    ]
)


# ------------------------------------------------------- Flow body length
# WhatsApp caps an interactive message body (the Flow's pre-form text) at
# 1,024 characters. The English copy is well under it; a translation can
# grow. Over the limit, Gupshup rejects the send and the customer gets no
# form, so the client's English copy is sent instead -- never a cut-off one.
FLOW_BODY_MAX_CHARS = 1024


def fit_flow_body(body_text: str | None, english: str) -> str:
    """The (translated) body if it fits in a Flow message, else ``english``."""
    text = (body_text or "").strip()
    if not text:
        return english
    if len(text) <= FLOW_BODY_MAX_CHARS:
        return text
    from kisna_chatbot.utils.logger_config import logger

    logger.warning(
        "Flow body over %s chars after translation; sending the English copy",
        FLOW_BODY_MAX_CHARS,
        extra={"chars": len(text), "english_chars": len(english)},
    )
    return english


# ------------------------------------------------------------ localisation
def confirmation_pins(
    request_id: str, scheduled_for: str | None = None
) -> tuple[str, ...]:
    """Tokens compose() must keep unchanged in a translated confirmation."""
    pins: list[str] = [request_id, BRAND, COMPLAINT_RESPONSE_TIME]
    if scheduled_for:
        date_part, _, slot_part = scheduled_for.partition(" · ")
        pins.append(scheduled_for)
        if date_part:
            pins.append(date_part)
        if slot_part:
            pins.append(slot_part)
    return tuple(pins)
