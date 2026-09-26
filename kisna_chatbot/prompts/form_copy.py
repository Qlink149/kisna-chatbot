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
