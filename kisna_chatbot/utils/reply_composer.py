"""Lightweight LLM reply mirroring for non-English users."""

from __future__ import annotations

from kisna_chatbot.ai.factory import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.utils.logger_config import logger

_CACHE: dict[tuple[str, str], str] = {}

_LANGUAGE_LABELS = {
    "hi": "Hindi (Devanagari script)",
    "hi-Latn": "Hinglish (Hindi in Latin script)",
    "ta": "Tamil (Tamil script)",
    "te": "Telugu (Telugu script)",
    "mr": "Marathi (Devanagari script)",
    "bn": "Bengali (Bengali script)",
    "gu": "Gujarati (Gujarati script)",
    "kn": "Kannada (Kannada script)",
}


def _language_label(lang: str) -> str:
    """Human label for the composer prompt; supports romanized (-Latn) variants."""
    if lang in _LANGUAGE_LABELS:
        return _LANGUAGE_LABELS[lang]
    if lang.endswith("-Latn"):
        base = lang[:-5]
        base_label = _LANGUAGE_LABELS.get(base, base)
        base_name = base_label.split(" (")[0]
        return (
            f"romanized {base_name} — {base_name} written in Latin/English "
            f"letters, the way people type it in chats (like Hinglish)"
        )
    return lang

# Static canned replies — safe to cache per (template_key, language).
_CACHEABLE_TEMPLATES = frozenset(
    {
        "greeting_new",
        "greeting_return",
        "acknowledgement",
        "clarification",
        "menu_help",
        "non_text",
        "rating_prompt",
        "slot_fill",
        "budget_prompt",
        "store_pincode",
        "flow_switch_ack",
        "fallback_unclear",
        "fallback_error",
        "product_detail_hint",
        "vague_fallback",
    }
)


def normalize_language(code: str | None) -> str:
    """Return a supported language code; default English."""
    raw = (code or "en").strip()
    if not raw or raw.lower() in ("en", "english"):
        return "en"
    if raw in _LANGUAGE_LABELS:
        return raw
    if raw.lower() in ("hinglish", "hi_latn", "hi-latin"):
        return "hi-Latn"
    if raw.lower() in ("hindi", "hin"):
        return "hi"
    # Best effort — pass through short codes for composer prompt.
    if len(raw) <= 8 and raw.replace("-", "").isalnum():
        return raw
    return "en"


def sanitize_classifier_language(code: str | None) -> str:
    """Allowlist classifier language output."""
    normalized = normalize_language(code)
    if normalized == "en":
        return "en"
    if normalized in _LANGUAGE_LABELS or normalized == "hi-Latn":
        return normalized
    # Unknown short codes are kept for best-effort mirroring.
    if normalized and normalized != "en":
        return normalized
    return "en"


async def compose(
    template_key: str,
    text: str,
    *,
    language: str = "en",
    name: str | None = None,
    phone_number: str | None = None,
    client_id: str | None = None,
) -> str:
    """
    Mirror canned English text into the user's language.

  English bypasses the LLM entirely (zero added cost).
    """
    lang = normalize_language(language)
    if lang == "en":
        return text

    cache_key = (template_key, lang)
    if template_key in _CACHEABLE_TEMPLATES and cache_key in _CACHE:
        return _CACHE[cache_key]

    label = _language_label(lang)
    instruction = (
        "You rewrite WhatsApp customer-service messages for KISNA jewellery. "
        "Keep the tone warm, natural, and concise like a helpful salesperson. "
        "Keep emojis. Keep prices, URLs, product names, and numbers EXACTLY unchanged. "
        "Use EXACTLY the language AND script requested — if Latin/romanized is "
        "requested, do not output native script, and vice versa. "
        "Output only the rewritten message — no quotes or explanation."
    )
    user_msg = f"Rewrite this message in {label}:\n\n{text}"

    try:
        rewritten = await complete_chat(
            agent=AgentName.GENERAL,
            instruction=instruction,
            messages=[{"role": "user", "content": user_msg}],
            max_output_tokens=400,
            phone_number=phone_number,
            client_id=client_id,
        )
        result = (rewritten or text).strip() or text
        if template_key in _CACHEABLE_TEMPLATES:
            _CACHE[cache_key] = result
        return result
    except Exception as exc:
        logger.warning(
            "reply_composer failed — using English",
            extra={"template_key": template_key, "language": lang, "error": str(exc)},
        )
        return text


async def localize_bot_responses(data: dict) -> None:
    """
    Localize tagged text responses in-place before sending.

    Builders tag canned English texts with "_compose": <template_key>.
    English users skip the LLM entirely; tags are always stripped.
    """
    responses = data.get("bot_response")
    if not isinstance(responses, list):
        return
    user_profile = data.get("user_profile") or {}
    language = normalize_language(user_profile.get("language", "en"))
    for item in responses:
        if not isinstance(item, dict):
            continue
        template_key = item.pop("_compose", None)
        if not template_key or language == "en":
            continue
        if item.get("type") != "text" or not item.get("text"):
            continue
        item["text"] = await compose(
            template_key,
            item["text"],
            language=language,
            phone_number=data.get("phone_number"),
            client_id=data.get("client_id"),
        )
