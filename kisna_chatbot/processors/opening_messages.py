"""How a turn opens -- one place for the welcome rules (applied in main.py just
before localisation, after every pipeline has built its reply).

- New user, greeting only  -> the client's welcome (time line + body), built
  by the classifier's greeting route. Left as is.
- New user with an intent  -> message 1 the client's welcome, message 2 the
  reply, as separate WhatsApp messages; a greeting opener ("Hi! 👋") at the
  start of the reply is removed, so the customer is greeted once.
- Returning user, greeting only -> service_list.build_greeting_text's
  returning form. Left as is.
- Returning user with an intent -> no greeting: just the reply, with any
  greeting opener removed.

"Greeting only" = the turn's reply is the greeting route's own message
(_compose greeting_new / greeting_return). "New user" = no stored chat history
when the message arrived (main._stamp_inbound records it).
"""

from __future__ import annotations

import re

GREETING_COMPOSE_KEYS = ("greeting_new", "greeting_return")

_EMOJI = r"[\U0001F300-\U0001FAFF☀-➿️‍]"
_GREETING_WORD = (
    r"(?:hi+|hello+|hey+|hiya|namaste|namaskar(?:am)?|"
    r"नमस्ते|नमस्कार|નમસ્તે|வணக்கம்|నమస్తే|ನಮಸ್ತೆ|നമസ്കാരം|নমস্কার)"
)
# "Hi! 👋 ", "Hello there! ", "Namaste 🙏 ", "Hi Priya! ". It must end in
# punctuation and/or emoji, so a sentence that merely starts with "Hi" is not cut.
_GREETING_OPENER_RE = re.compile(
    rf"^\s*{_GREETING_WORD}(?:\s+there)?(?:[ ,]+[^\W\d_][\w'’-]*)?"
    rf"(?:\s*[!.,]+(?:\s*{_EMOJI})*|(?:\s*{_EMOJI})+)\s*",
    re.IGNORECASE,
)


def strip_greeting_opener(text: str) -> str:
    """Remove one greeting opener from the start of ``text``. Never empties it."""
    if not text:
        return text
    m = _GREETING_OPENER_RE.match(text)
    if not m:
        return text
    rest = text[m.end():]
    if not rest.strip():
        return text
    return rest[:1].upper() + rest[1:]


def _is_greeting_turn(responses: list[dict]) -> bool:
    return any(r.get("_compose") in GREETING_COMPOSE_KEYS for r in responses)


def _strip_first_reply_opener(responses: list[dict]) -> None:
    for response in responses:
        if response.get("type") == "skip":
            continue
        text = response.get("text")
        if isinstance(text, str) and text.strip():
            response["text"] = strip_greeting_opener(text)
        return


def apply_opening_rules(data: dict, now=None) -> None:
    """Shape this turn's opening per the rules above. Mutates data in place."""
    responses = data.get("bot_response")
    if not isinstance(responses, list) or not responses:
        return
    if _is_greeting_turn(responses):
        return
    _strip_first_reply_opener(responses)
    data["_opening_reply_index"] = 0
    if not data.get("_new_user"):
        return
    from kisna_chatbot.processors.service_list import build_greeting_welcome_bot_responses

    welcome = build_greeting_welcome_bot_responses(
        phone_number=data.get("phone_number"),
        chat_history=[],
        user_profile=data.get("user_profile") or {},
        now=now,
    )
    data["bot_response"] = welcome + responses
    data["_opening_reply_index"] = len(welcome)


def strip_reply_opener_after_localize(data: dict) -> None:
    """Localisation may rewrite a reply (narrate() for warm, personality-tagged
    lines) and greet again; strip the reply's opener once more. The welcome
    itself is never touched."""
    idx = data.get("_opening_reply_index")
    responses = data.get("bot_response")
    if idx is None or not isinstance(responses, list):
        return
    _strip_first_reply_opener(responses[idx:])
