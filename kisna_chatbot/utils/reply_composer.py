"""Lightweight LLM reply mirroring for non-English users."""

from __future__ import annotations

import re

from kisna_chatbot.ai.config import resolve_compose_model, resolve_max_tokens
from kisna_chatbot.ai.factory import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.utils.logger_config import logger

_CACHE: dict[tuple[str, str], str] = {}

# Same range the classifier uses: Devanagari through Malayalam (includes Gujarati).
_INDIC_SCRIPT_RE = re.compile(r"[ऀ-ൿ]")

_LANGUAGE_LABELS = {
    "hi": "Hindi (Devanagari script)",
    "hi-Latn": "Hinglish (Hindi in Latin script)",
    "ta": "Tamil (Tamil script)",
    "te": "Telugu (Telugu script)",
    "mr": "Marathi (Devanagari script)",
    "bn": "Bengali (Bengali script)",
    "gu": "Gujarati (Gujarati script)",
    "kn": "Kannada (Kannada script)",
    # Added after a Gurmukhi message was answered in Gujarati: an unlisted
    # language falls back to the nearest listed one, which is worse than
    # replying in English.
    "ml": "Malayalam (Malayalam script)",
    "pa": "Punjabi (Gurmukhi script)",
    "or": "Odia (Odia script)",
    "as": "Assamese (Bengali-Assamese script)",
    # Urdu is the one supported language NOT written in an Indic script. Every
    # script rule below had to learn about Arabic for it -- see _SCRIPT_RANGES.
    "ur": "Urdu (Nastaliq/Arabic script)",
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


def _needs_native_script(lang: str) -> bool:
    """True when the rewrite must contain Indic characters (not Hinglish / -Latn)."""
    return lang in _LANGUAGE_LABELS and not lang.endswith("-Latn")


# Per-script ranges, so "is this the RIGHT script" can be asked rather than the
# far weaker "is this SOME Indic script". _INDIC_SCRIPT_RE above spans
# U+0900-U+0D7F, i.e. Devanagari through Malayalam, so a Telugu reply with
# Devanagari spliced into it, or a Gujarati reply carrying Malayalam, sailed
# through the echo check untouched. Both were observed live.
_SCRIPT_RANGES: dict[str, tuple[int, int]] = {
    "hi": (0x0900, 0x097F),
    "mr": (0x0900, 0x097F),
    "bn": (0x0980, 0x09FF),
    "as": (0x0980, 0x09FF),
    "pa": (0x0A00, 0x0A7F),
    "gu": (0x0A80, 0x0AFF),
    "or": (0x0B00, 0x0B7F),
    "ta": (0x0B80, 0x0BFF),
    "te": (0x0C00, 0x0C7F),
    "kn": (0x0C80, 0x0CFF),
    "ml": (0x0D00, 0x0D7F),
    # Urdu-specific letters (ٹ U+0679, ڈ U+0688, ڑ U+0691, ک U+06A9, گ U+06AF,
    # ں U+06BA, ہ U+06C1, ی U+06CC, ے U+06D2) all sit inside this one block, so
    # a single range covers the alphabet -- Arabic Supplement is not needed.
    "ur": (0x0600, 0x06FF),
}
# Scripts a reply must never contain, whatever the target language.
_FOREIGN_SCRIPT_RANGES: tuple[tuple[int, int], ...] = (
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x4E00, 0x9FFF),  # CJK
    (0x3040, 0x30FF),  # Kana
    (0x0400, 0x04FF),  # Cyrillic
    (0x0E00, 0x0E7F),  # Thai
)


def _script_violations(lang: str, rewritten: str) -> list[str]:
    """Characters from a script this language must not contain.

    Latin, digits, punctuation and emoji are always allowed -- prices, URLs,
    SKUs and product names are meant to survive untranslated.
    """
    text = rewritten or ""
    if not text:
        return []
    target = _SCRIPT_RANGES.get(lang.split("-")[0])
    bad: set[str] = set()
    for ch in text:
        cp = ord(ch)
        # Danda / double danda and the zero-width joiners are shared across
        # Indic scripts — Bengali and Gurmukhi both end sentences with "।".
        # Flagging them as foreign made clean replies look contaminated.
        if cp in (0x0964, 0x0965, 0x200C, 0x200D):
            continue
        # A language's OWN script is never foreign to it. This has to come
        # before the loop below because Arabic is IN that list -- it is foreign
        # to every Indic language, but it is exactly what Urdu must be written
        # in. Without this guard the composer flags a perfect Urdu reply as
        # entirely contaminated and falls back to English.
        if target and target[0] <= cp <= target[1]:
            continue
        for lo, hi in _FOREIGN_SCRIPT_RANGES:
            if lo <= cp <= hi:
                bad.add(ch)
        # Any Indic block other than the target one.
        if 0x0900 <= cp <= 0x0D7F and target and not (target[0] <= cp <= target[1]):
            bad.add(ch)
    return sorted(bad)


def _is_native_script_echo(lang: str, rewritten: str) -> bool:
    """True when a native-script language came back with no Indic characters."""
    if not _needs_native_script(lang):
        return False
    return not bool(_INDIC_SCRIPT_RE.search(rewritten or ""))


def _is_unusable_rewrite(lang: str, rewritten: str) -> bool:
    """Reject a rewrite that echoed English or mixed in a foreign script."""
    if _is_native_script_echo(lang, rewritten):
        return True
    if _needs_native_script(lang) and _script_violations(lang, rewritten):
        return True
    return False


# Phrases the user must be able to type back to us verbatim. Translating them
# silently breaks the flow they trigger -- observed live: the return-policy
# answer's closing CTA came back translated in one run and left in English in
# another, so it was never dependable either way.
_PINNED_PHRASES = ("I want to return my order",)

# Some copy names metals in BOTH a positive and a negative clause, and getting
# one of them wrong inverts the meaning. Live: the "we don't carry silver"
# note came back as "hum sone, platinum, ya moti nahi rakhte" -- telling the
# customer KISNA does not sell GOLD. Keeping the metal nouns in English is
# unambiguous for Indian readers and removes the failure mode entirely.
_PINNED_WORDS_BY_TEMPLATE: dict[str, tuple[str, ...]] = {
    "unsupported_material": (
        "gold",
        "diamond",
        "gemstone",
        "silver",
        "platinum",
        "pearl",
    ),
}


def _compose_token_budget(text: str) -> int:
    """Scale the output budget to the source length.

    Native scripts tokenise far less efficiently than English, so a long FAQ
    answer needs headroom the old flat 400 did not always give. A flat 1024 is
    the wrong answer too: on a reasoning-capable model the spare budget is
    spent thinking, and mean compose latency tripled to 4.6s on strings barely
    60 characters long. (Truncation was tested and is NOT the cause of the
    mistranslations this rewrite fixes — the headroom is insurance only.)
    """
    return max(400, min(resolve_max_tokens(AgentName.GENERAL), len(text or "") // 2 + 300))


def _compose_instruction(label: str, *, strict: bool = False) -> str:
    """Faithful rewrite prompt. ``strict`` is the one-shot echo retry."""
    instruction = (
        "You rewrite WhatsApp customer-service messages for KISNA jewellery. "
        "Keep the tone warm, natural, and concise like a jewellery salesperson "
        "on WhatsApp — never bazaar or chat slang. "
        "Keep emojis. Keep prices, URLs, emails, phone numbers, pincodes, SKUs, "
        "and proper product titles (e.g. Tanishta) EXACTLY unchanged. "
        "DO translate generic jewellery words in canned copy — gold, rings, "
        "necklace, for women, for men, for kids, ready to ship, made to order. "
        "Those are not product names. "
        "People: never crude or overly casual adult words (do not use औरत, मर्द, "
        "aurat, mard, or लड़की/लड़का for adult jewellery). Hindi Devanagari: "
        "महिला / पुरुष, बच्चों for kids. Hinglish or other Latin script: keep "
        "women / men / kids. Other native scripts: that language's respectful "
        "adult pair, same idea as महिला/पुरुष. "
        "Budget: keep the rupee figures; never recast a price as cheap / सस्ता "
        "/ equivalent. "
        "Products: use the normal shop words for jewellery in that language; "
        "never माल or similar slang. "
        "Use EXACTLY the language AND script requested — if Latin/romanized is "
        "requested, do not output native script, and vice versa. "
        # *asterisks* are WhatsApp bold markers. Models were reading them as the
        # "proper product titles" the rule above protects, and leaving *anyone*
        # / *no specific budget* in English inside an otherwise translated
        # sentence — naming a word the slot parser will then never accept.
        "FORMATTING: *asterisks* are WhatsApp bold markers, NOT product names. "
        "Translate the words INSIDE them and keep the asterisks. "
        # The mistranslations that actually reached customers were all in this
        # small closed set: rings became bangles / emerald pearls / a garland,
        # and gold became silver.
        "JEWELLERY WORDS: always use the natural everyday word in the target "
        "language for ring, earring, necklace, chain, pendant, bangle, "
        "bracelet, mangalsutra and nose pin. NEVER swap one item for another "
        "(a ring is not a bangle, not a pearl) and NEVER change the metal or "
        "stone (gold stays gold, never silver; diamond stays diamond). "
        "Write ONLY in the requested script — never mix in characters from "
        "another language's script. "
        "Output only the rewritten message — no quotes or explanation."
    )
    if strict:
        instruction += (
            f" STRICT: You MUST write in {label}. Do not leave the English "
            "sentence unchanged. Translate fully into the requested language "
            "and script. Keep prices, URLs, emails, phones, pincodes, SKUs, "
            "and proper product titles unchanged."
        )
    return instruction


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

    # Cache by the ACTUAL text (+language), never by template_key alone: many
    # templates share a key but vary in content (flow_switch_ack has 9 variants;
    # greetings carry the user's name). Keying by text means identical source
    # reuses a translation while different source can never collide — no more
    # "store ack served for a returns switch" or one user's name leaking to
    # another.
    cache_key = (lang, text)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    label = _language_label(lang)
    pinned = [p for p in _PINNED_PHRASES if p in text]
    instruction_extra = ""
    if pinned:
        quoted = " and ".join(f'"{p}"' for p in pinned)
        instruction_extra = (
            f" Keep {quoted} EXACTLY as-is in English — it is a phrase the "
            "customer must type back to us verbatim, not prose."
        )
    pinned_words = [
        w for w in _PINNED_WORDS_BY_TEMPLATE.get(template_key, ()) if w in text.lower()
    ]
    if pinned_words:
        instruction_extra += (
            " Leave these words in English exactly as written: "
            + ", ".join(pinned_words)
            + ". Do NOT translate or substitute them — this sentence says which "
            "metals we do and do not sell, and swapping one inverts its meaning."
        )
    user_msg = f"Rewrite this message in {label}:\n\n{text}"
    # Low-resource Indic translation goes to a stronger model; everything else
    # stays on the agent's normal one. See ai/config.resolve_compose_model.
    compose_model = resolve_compose_model(lang)

    async def _rewrite(instruction: str) -> str:
        rewritten = await complete_chat(
            agent=AgentName.GENERAL,
            instruction=instruction + instruction_extra,
            messages=[{"role": "user", "content": user_msg}],
            max_output_tokens=_compose_token_budget(text),
            phone_number=phone_number,
            client_id=client_id,
            model=compose_model,
        )
        return (rewritten or "").strip()

    try:
        result = await _rewrite(_compose_instruction(label))
        if not result:
            result = text
        if _is_unusable_rewrite(lang, result):
            retry = await _rewrite(_compose_instruction(label, strict=True))
            if retry and not _is_unusable_rewrite(lang, retry):
                result = retry
            else:
                logger.warning(
                    "reply_composer unusable rewrite — using English",
                    extra={
                        "template_key": template_key,
                        "language": lang,
                        "model": compose_model,
                        "foreign_chars": "".join(_script_violations(lang, retry or result))[:20],
                    },
                )
                return text
        if pinned or pinned_words:
            # A pinned phrase that did not survive makes the reply actively
            # misleading: it tells the customer to send words that trigger
            # nothing, or claims we don't sell the metal we do. English is the
            # safer answer.
            lowered = result.lower()
            missing = [p for p in pinned if p not in result]
            missing += [w for w in pinned_words if w not in lowered]
            if missing:
                logger.warning(
                    "reply_composer dropped a pinned phrase — using English",
                    extra={"template_key": template_key, "language": lang,
                           "missing": missing[:2]},
                )
                return text
        if len(_CACHE) < 2000:
            _CACHE[cache_key] = result
        return result
    except Exception as exc:
        logger.warning(
            "reply_composer failed — using English",
            extra={"template_key": template_key, "language": lang, "error": str(exc)},
        )
        return text


# Personality surfaces: the canned English is only a HINT of intent. The narrator
# rewrites it fresh each time — varied, warm, in the user's language — so the bot
# never repeats the same robotic line. Functional surfaces (pincode ask, budget
# prompt, rating, form-related) are NOT here: they stay faithful so no instruction
# is lost.
_PERSONALITY_TAGS = frozenset(
    {
        "greeting_new",
        "greeting_return",
        "acknowledgement",
        "flow_switch_ack",
        "slot_fill",
        "clarification",
        "vague_fallback",
        "small_talk",
        "fallback_unclear",
        "repair",
    }
)


async def narrate(
    intent_text: str,
    *,
    language: str = "en",
    user_message: str = "",
    phone_number: str | None = None,
    client_id: str | None = None,
) -> str:
    """Fresh, varied, natural rewrite of a personality-surface message.

    Unlike compose (faithful translation, cached), this always calls the LLM —
    English included — and never caches, so greetings/acks feel alive. Falls
    back to the original text on any failure.
    """
    lang = normalize_language(language)
    label = "English" if lang == "en" else _language_label(lang)
    instruction = (
        "You are KIA, a warm, friendly jewellery shopping assistant for KISNA on "
        "WhatsApp. You'll be given the INTENT of a message to convey. Write ONE "
        "short, natural, human reply that conveys ONLY that intent — vary your "
        f"wording, sound like a real person, never robotic. Reply in {label}. "
        "Keep it to 1-2 short lines. Keep any prices, URLs, names, and numbers "
        "exact. Use at most one emoji. Output only the message.\n"
        "STRICT: Do NOT invent or suggest any specific product, category, "
        "material, collection, or offer that is not in the given intent — do not "
        "say things like 'want to see silver rings?'. NEVER mention silver, "
        "platinum, or pearl (KISNA doesn't sell them). Do not reference earlier "
        "messages to propose products. For a greeting, stay warm and open-ended "
        "(e.g. 'what can I help you find today?') — never name a product."
    )
    if _needs_native_script(lang):
        instruction += (
            " Write ONLY in the requested script — never mix in characters or "
            "words from another language. Use the natural everyday word for "
            "'jewellery' in that language."
        )
    ctx = f"Customer said: {user_message}\n" if user_message else ""
    user_msg = f"{ctx}Convey this: {intent_text}"
    try:
        out = await complete_chat(
            agent=AgentName.GENERAL,
            instruction=instruction,
            messages=[{"role": "user", "content": user_msg}],
            # A flat 200 starved the routed model: it spent the budget
            # reasoning and returned an EMPTY string, so `out or
            # intent_text` handed the customer the whole English intro
            # as their first message -- 38% of native-script greetings
            # live. compose() never had this: it already scales.
            max_output_tokens=_compose_token_budget(intent_text),
            phone_number=phone_number,
            client_id=client_id,
            # Greetings and acks are the FIRST thing a customer reads, and the
            # default model mangles them in low-resource languages — a Marathi
            # greeting came back as "wheat sinus assistant". Same routing as
            # compose(); without it this path silently kept the old quality.
            model=resolve_compose_model(lang),
        )
        text = (out or intent_text).strip() or intent_text
        # Empty output falls back to the English source, which the purity
        # check happily accepts -- English contains no FOREIGN script. Ask
        # the echo question too, as _is_unusable_rewrite does for compose().
        if _needs_native_script(lang) and (
            _script_violations(lang, text) or _is_native_script_echo(lang, text)
        ):
            # One resample before giving up. Falling straight back to English
            # leaves a greeting in English glued to a native-script prompt on
            # the very next line, which reads worse than either alone.
            retry = await complete_chat(
                agent=AgentName.GENERAL,
                instruction=instruction,
                messages=[{"role": "user", "content": user_msg}],
                max_output_tokens=_compose_token_budget(intent_text),
                phone_number=phone_number,
                client_id=client_id,
                model=resolve_compose_model(lang),
            )
            retry = (retry or "").strip()
            if retry and not (
                _script_violations(lang, retry)
                or _is_native_script_echo(lang, retry)
            ):
                return retry
            logger.warning(
                "reply_composer.narrate mixed scripts — using original",
                extra={"language": lang},
            )
            return intent_text
        return text
    except Exception as exc:
        logger.warning(
            "reply_composer.narrate failed — using original",
            extra={"language": lang, "error": str(exc)},
        )
        return intent_text


async def _localize_quick_reply(item: dict, language: str, data: dict) -> None:
    """Translate a quick reply's PROMPT. Button titles stay in English.

    Gupshup sends one ``msgid`` for the whole message (e.g. "wizard$gender"), so
    the button *title* is the only per-option discriminator on the way back —
    ``shopping_wizard.parse_wizard_button`` resolves the tap by looking the title
    up in _GENDER_TITLE_MAP / _MATERIAL_TITLE_MAP. Translating titles would make
    every tap unparseable. Localizing the question is the safe half, and it is
    what actually read as broken: a Gujarati funnel that switched to English
    mid-way. Per-button msgids would be needed to translate the labels too.
    """
    if language == "en" or not item.get("text"):
        return
    item["text"] = await compose(
        "quickreply_text",
        item["text"],
        language=language,
        phone_number=data.get("phone_number"),
        client_id=data.get("client_id"),
    )


async def localize_bot_responses(data: dict) -> None:
    """
    Rewrite tagged text responses in-place before sending.

    Builders tag canned English texts with "_compose": <template_key>.
    - Personality tags → narrate() (fresh, varied, any language incl. English).
    - Functional tags → compose() (faithful translation; English passes through).
    Tags are always stripped.
    """
    responses = data.get("bot_response")
    if not isinstance(responses, list):
        return
    user_profile = data.get("user_profile") or {}
    language = normalize_language(user_profile.get("language", "en"))
    messages = data.get("messages") or {}
    user_message = ""
    if isinstance(messages, dict) and messages.get("type") != "interactive":
        user_message = ((messages.get("text") or {}).get("body") or "")[:200]

    for item in responses:
        if not isinstance(item, dict):
            continue
        template_key = item.pop("_compose", None)
        if not template_key:
            continue
        # Quick replies carry their prompt in "text" plus button titles. They
        # used to fall through the type check below with the tag already popped,
        # so a Gujarati wizard asked "Great! Who is it for?" in English between
        # two translated steps.
        if item.get("type") == "quickreply":
            await _localize_quick_reply(item, language, data)
            continue
        if item.get("type") != "text" or not item.get("text"):
            continue
        if template_key in _PERSONALITY_TAGS:
            item["text"] = await narrate(
                item["text"],
                language=language,
                user_message=user_message,
                phone_number=data.get("phone_number"),
                client_id=data.get("client_id"),
            )
        elif language != "en":
            item["text"] = await compose(
                template_key,
                item["text"],
                language=language,
                phone_number=data.get("phone_number"),
                client_id=data.get("client_id"),
            )
