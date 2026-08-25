"""Guided jewellery discovery wizard with smart-skip of known slots."""

from __future__ import annotations

import json
import re
from typing import Any

# Steps in ask order. Category can already be filled from the first user message.
# Occasion removed — Clara has no occasion filter (client confirmed).
WIZARD_STEPS = (
    "category",
    "gender",
    "material",
    "budget",
    "fulfillment",
)

READY_TO_SHIP_EDD_DAYS = 7

DIGITAL_GOLD_URL = "https://www.kisna.com/digital-gold"

# "Doesn't matter" answer: fills the slot so the funnel advances, then drops
# out in entities_from_wizard so no filter is sent.
ANY_SLOT = "any"

_GENDER_TITLE_MAP = {
    "female": "women",
    "male": "men",
    "kids": "kids",
    "women": "women",
    "men": "men",
    "for her": "women",
    "for him": "men",
    "wife": "women",
    "husband": "men",
    "girl": "women",
    "boy": "men",
    "ladies": "women",
    "lady": "women",
    "gents": "men",
    # Relationship / free-text answers at the gender wizard step
    "mom": "women",
    "mother": "women",
    "mummy": "women",
    "maa": "women",
    "for mom": "women",
    "for mother": "women",
    "for mummy": "women",
    "sister": "women",
    "for sister": "women",
    "behen": "women",
    "daughter": "women",
    "beti": "women",
    "girlfriend": "women",
    "gf": "women",
    "aunty": "women",
    "aunt": "women",
    "didi": "women",
    "naniji": "women",
    "dadi": "women",
    "dad": "men",
    "daddy": "men",
    "father": "men",
    "papa": "men",
    "for dad": "men",
    "for daddy": "men",
    "for father": "men",
    "for papa": "men",
    "brother": "men",
    "for brother": "men",
    "bhai": "men",
    "beta": "men",
    "boyfriend": "men",
    "bf": "men",
    "uncle": "men",
    "fufa": "men",
    "mama": "men",
}

_MATERIAL_TITLE_MAP = {
    "gold": "gold",
    "diamond": "diamond",
    "gemstone": "gemstone",
    "gem stone": "gemstone",
    "stone": "gemstone",
    # Devanagari / common Indic spellings (wizard sticky answers)
    "सोना": "gold",
    "सोने": "gold",
    "सोने की": "gold",
    "सोने का": "gold",
    "हीरा": "diamond",
    "हीरे": "diamond",
    "डायमंड": "diamond",
    "डाइमंड": "diamond",
    "डायमण्ड": "diamond",
    "रत्न": "gemstone",
    "जेमस्टोन": "gemstone",
    # Gujarati
    "સોનું": "gold",
    "સોના": "gold",
    "હીરા": "diamond",
    "ડાયમંડ": "diamond",
    "રત્ન": "gemstone",
}

_FULFILLMENT_TITLE_MAP = {
    "ready to ship": "ready",
    "ready-to-ship": "ready",
    "ready": "ready",
    "made to order": "mto",
    "made-to-order": "mto",
    "either is fine": ANY_SLOT,
    "either": ANY_SLOT,
    "custom": "mto",
    "customise": "mto",
    "customize": "mto",
}


def is_fulfillment_slot_answer(text: str | None) -> bool:
    """True when the whole message is an availability answer, not a request.

    "made to order" / "custom" / "ready to ship" are the wizard's own button
    labels and map to a catalogue filter. Callers use this to keep such a
    message out of intent overrides that would route it somewhere else.
    """
    normalized = " ".join((text or "").strip().lower().split())
    normalized = normalized.strip("*.!? ")
    return normalized in _FULFILLMENT_TITLE_MAP


# Everything the funnel has collected so far. An escape tears the wizard down
# (clear_wizard_state), so anything not handed forward here is GONE.
#
# This used to be only the three button-tapped slots, which meant an off-step
# message wiped the category the user had just given: "Do you have rings" ->
# "Under 10k ?" came back as "What are you looking for today?" with
# shopping_wizard_data = {max_price: 10000} and no category. Gender survived and
# category did not, purely because gender was on this list.
#
# Safe to widen because BOTH consumers apply carryover as a FALLBACK, never an
# override -- product_search_agent_v3 only fills keys where the new message left
# `entities[k] is None`. A genuine new product ("show me necklaces") still wins,
# because that message supplies its own category.
#
# collection/title are deliberately absent: seed_wizard_from_entities never
# stores them, so they would be dead keys. A collection anchored search is held
# in the pending-confirmation state instead, and is preserved there
# (product_search_agent_v3._confirm_refinement_merge).
WIZARD_CARRYOVER_KEYS = (
    "gender",
    "material_type",
    "fulfillment",
    "category",
    "min_price",
    "max_price",
    # Not a slot the funnel fills -- a constraint it must respect. Without it,
    # someone who opened with "I don't want gold" was then offered Gold as one
    # of three buttons on the very next screen.
    "excluded_material",
)


def filter_wizard_carryover(
    carryover: dict | None,
    entities: dict | None,
    prior_filters: dict | None,
    *,
    query: str | None = None,
) -> dict:
    """Drop sticky slots that must not survive a new product / audience ask.

    - Category change vs last search → drop material and gender.
    - Ambiguous audience ("for parents") → drop gender so wizard asks again.
    - Prior completed search + bare category ask ("show me rings") → drop
      unevidenced gender/material so those steps are not skipped.
    Same-funnel (Female + Gold, then "rings under 30k") keeps both when there
    is no prior category and the message is not ambiguous.
    """
    out = dict(carryover or {})
    if not out:
        return out
    new_cat = (entities or {}).get("category")
    prior_cat = (prior_filters or {}).get("category")
    category_changed = bool(
        new_cat
        and prior_cat
        and str(new_cat).strip().lower() != str(prior_cat).strip().lower()
    )
    if category_changed:
        out.pop("material_type", None)
        out.pop("gender", None)

    from kisna_chatbot.processors.entity_extractor import (
        _gender_evidenced,
        is_ambiguous_audience,
    )

    if is_ambiguous_audience(query):
        out.pop("gender", None)

    # After a completed search, only keep carryover slots the NEW message
    # actually restates — otherwise "show me rings" skips Who/material.
    if prior_cat and query:
        carried_gender = out.get("gender")
        if carried_gender and not _gender_evidenced(query, carried_gender):
            out.pop("gender", None)
        carried_material = out.get("material_type")
        if carried_material and not _material_evidenced_in_text(
            query, carried_material
        ):
            out.pop("material_type", None)
    return out


def _material_evidenced_in_text(query: str | None, material: str | None) -> bool:
    """True when the message clearly names gold/diamond/gemstone (Latin)."""
    if not query or not material:
        return False
    key = str(material).strip().lower()
    if key not in ("gold", "diamond", "gemstone"):
        return False
    normalized = query.lower()
    if key == "gold":
        return bool(re.search(r"\b(gold|sona|sone)\b", normalized))
    if key == "diamond":
        return bool(re.search(r"\b(diamond|heera|heere|solitaire)\b", normalized))
    if key == "gemstone":
        return bool(
            re.search(r"\b(gemstone|gem\s*stone|ruby|emerald|sapphire)\b", normalized)
        )
    return False

# Steps a user may decline to answer. Category is excluded — Clara needs a
# scope, so "anything" there is a browse-everything escape, not a slot value.
_ANY_ANSWER_STEPS = ("gender", "material", "budget", "fulfillment")

_ANY_ANSWER_RE = re.compile(
    r"\b(skip|anyone|anybody|any\s*one|any|either|whatever|flexible|"
    r"doesn'?t\s+matter|dont\s+matter|no\s+preference|no\s+specific|"
    r"no\s+budget|no\s+limit|no\s+bar|not\s+decided|not\s+sure|"
    r"limit\s+nahi|koi\s+limit|price\s+koi|"
    r"koi\s+bhi|kuch\s+bhi|jo\s+bhi|kisi\s+ke\s+liye\s+bhi|"
    r"budget\s+nahi|decide\s+nahi)\b"
    # Devanagari (Hindi/Marathi) equivalents. No \b here on purpose: Python's
    # \w classification excludes some Devanagari combining marks (e.g. ं,
    # anusvara), so a trailing \b silently fails to match words that end in
    # one -- confirmed live, "\bनहीं\b" alone does not match "नहीं" in
    # "...budget नहीं है।" even with clear whitespace on both sides. This
    # regex only runs when the wizard is ALREADY on an _ANY_ANSWER_STEPS
    # question, so the wider, boundary-free "कोई ... नहीं" gap match is
    # safe here (the reply is answering THAT question, not free text) --
    # unlike the romanized side above, which needs exact phrases since it
    # also runs as a general escape check.
    r"|कोई.{0,20}नहीं|जो\s*भी|कुछ\s*भी|कोई\s*भी|"
    r"पक्का\s*नहीं|तय\s*नहीं|बजट\s*नहीं|कोई\s*(खास|विशेष)",
    re.I,
)

_ESCAPE_RE = re.compile(
    r"\b(skip|browse\s+all|any\s+will\s+do|"
    r"doesn't\s+matter|dont\s+matter|koi\s+bhi|kuch\s+bhi)\b",
    re.I,
)

# "show me" was in _ESCAPE_RE, which made ANY answer containing it tear the
# funnel down: at the material step "show me gold ones" threw away the category
# and restarted from "What are you looking for today?". It only means "leave"
# when it asks for a DIFFERENT product -- otherwise it is just how people phrase
# an answer.
_SHOW_ME_RE = re.compile(r"\b(just\s+show|show\s+me)\b", re.I)


def _names_new_product(text: str) -> bool:
    """True when the message asks for a product other than the one in progress."""
    from kisna_chatbot.processors.entity_extractor import (
        _matched_collection_label,
        extract_entities,
    )

    ents = extract_entities(text or "")
    if ents.get("category") or ents.get("categories") or ents.get("title"):
        return True
    return bool(_matched_collection_label(text or ""))

_WIZARD_MSGID_PREFIX = "wizard$"


def _gender_from_text(text: str | None) -> str | None:
    """Word-boundary gender lookup for wizard free text.

    A plain substring scan silently matched "men" inside ornaments / recommend /
    gentlemen and flipped the audience filter. The search path already guards
    this with entity_extractor._gender_evidenced — reuse it so both paths agree.
    """
    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return None
    if normalized in _GENDER_TITLE_MAP:
        return _GENDER_TITLE_MAP[normalized]

    from kisna_chatbot.processors.entity_extractor import _gender_evidenced

    for candidate in ("kids", "women", "men"):
        if _gender_evidenced(normalized, candidate):
            return candidate
    return None


def _looks_like_pincode(digits: str, text: str | None) -> bool:
    """True for a bare 6-digit pincode typed at the budget step.

    Budgets that size are round ("100000", "250000"); an Indian pincode almost
    never is. Without this, a user answering the wrong question with "400001"
    silently got a ₹4 lakh search.
    """
    if len(digits) != 6 or digits.endswith("000"):
        return False
    normalized = (text or "").strip()
    if re.search(r"[₹]|\b(k|lakh|lac|hazaar|budget|under|below|upto|tak)\b",
                 normalized, re.I):
        return False
    return digits == re.sub(r"[^\d]", "", normalized)


# No jewellery budget is above ₹1 crore. Anything larger is a phone number, an
# order id, or a typo — never a budget. A user answering the wrong question with
# "987654321" was silently given a ₹98.7 crore search.
MAX_REALISTIC_BUDGET = 10_000_000


def budget_rejection_reason(text: str | None) -> str | None:
    """Why a budget answer was refused: 'pincode', 'too_large', or None."""
    normalized = (text or "").strip()
    if not normalized:
        return None
    digits = re.sub(r"[^\d]", "", normalized)
    if not digits.isdigit() or not digits:
        return None
    # A bare number with no budget word attached.
    bare = digits == re.sub(r"[^\d]", "", normalized) and not re.search(
        r"[₹]|\b(k|lakh|lac|lakhs|crore|hazaar|hazar|hajar|thousand|budget"
        r"|under|below|upto|tak|se)\b",
        normalized,
        re.I,
    )
    if bare and len(digits) == 6 and not digits.endswith("000"):
        return "pincode"
    if bare and len(digits) >= 7:
        return "too_large"
    return None


def _budget_restated_in_text(
    text: str | None, llm_entities: dict | None
) -> bool:
    """True when THIS message names a budget / price band."""
    llm = llm_entities or {}
    if llm.get("min_price") is not None or llm.get("max_price") is not None:
        return True
    from kisna_chatbot.processors.entity_extractor import (
        _extract_prices,
        extract_entities,
    )

    ents = extract_entities(text or "")
    if ents.get("min_price") is not None or ents.get("max_price") is not None:
        return True
    min_p, max_p = _extract_prices(text or "")
    return min_p is not None or max_p is not None


def _slot_restated_in_text(
    slot: str, value: str, text: str | None, llm_entities: dict | None
) -> bool:
    """True when THIS message explicitly restates a gender / material / fulfillment choice.

    The LLM is instructed to emit these only from the current message, so its
    verdict counts as evidence in any language; the Latin check is the fallback.
    """
    llm_key = "material_type" if slot == "material" else slot
    if (llm_entities or {}).get(llm_key) == value:
        return True
    if slot in ("gender",):
        return _gender_from_text(text) == value
    if slot in ("material", "material_type"):
        if value not in ("gold", "diamond", "gemstone"):
            return False
        if _material_evidenced_in_text(text, value):
            return True
        normalized = " ".join((text or "").strip().lower().split())
        if normalized in _MATERIAL_TITLE_MAP:
            return _MATERIAL_TITLE_MAP[normalized] == value
        return False
    if slot == "fulfillment":
        from kisna_chatbot.processors.entity_extractor import extract_fulfillment

        normalized = " ".join((text or "").strip().lower().split())
        if normalized in _FULFILLMENT_TITLE_MAP:
            return _FULFILLMENT_TITLE_MAP[normalized] == value
        return extract_fulfillment(text) == value
    return False


def _llm_slot_values(llm_entities: dict | None) -> dict:
    """Non-null wizard slots the LLM understood (the only Indic-capable source).

    ``extract_entities`` is Latin-only, so a Devanagari/Gujarati slot answer
    ("अंगूठी", "५० हज़ार") parses to nothing there.
    """
    ents = llm_entities or {}
    out: dict[str, Any] = {}
    category = ents.get("category")
    if category:
        out["category"] = str(category).strip().lower()
    material = ents.get("material_type")
    if material in ("gold", "diamond", "gemstone"):
        out["material_type"] = material
    gender = ents.get("gender")
    if gender in ("women", "men", "kids"):
        out["gender"] = gender
    fulfillment = ents.get("fulfillment")
    if fulfillment in ("ready", "mto"):
        out["fulfillment"] = fulfillment
    elif fulfillment == "any":
        # The contract has always allowed "any" here and this dropped it, so
        # "either is fine" in any language was thrown away and the wizard asked
        # the availability question again.
        out["fulfillment"] = ANY_SLOT
    if ents.get("min_price") is not None or ents.get("max_price") is not None:
        out["min_price"] = ents.get("min_price")
        out["max_price"] = ents.get("max_price")
    elif ents.get("budget") == "any":
        out["budget"] = ANY_SLOT
    return out


def is_wizard_active(user_profile: dict) -> bool:
    return bool(user_profile.get("shopping_wizard_active"))


def clear_wizard_state(user_profile: dict) -> None:
    for key in (
        "shopping_wizard_active",
        "shopping_wizard_step",
        "shopping_wizard_data",
        "shopping_wizard_explicit",
    ):
        user_profile.pop(key, None)


_EXPLICIT_ENTITY_KEYS = (
    "karat",
    "metal_colour",
    "collection",
    "size",
    "style",
    "occasion",
    "title",
)


def extract_explicit_entities(entities: dict | None) -> dict[str, Any]:
    """Non-wizard-slot fields volunteered in the user's message."""
    ents = entities or {}
    out: dict[str, Any] = {}
    for key in _EXPLICIT_ENTITY_KEYS:
        value = ents.get(key)
        if value is None or value == "":
            continue
        if value == ANY_SLOT:
            continue
        out[key] = value
    return out


def update_wizard_explicit(
    user_profile: dict,
    entities: dict | None,
) -> dict:
    """Merge newly stated explicit fields into shopping_wizard_explicit."""
    incoming = extract_explicit_entities(entities)
    if not incoming:
        existing = user_profile.get("shopping_wizard_explicit")
        return existing if isinstance(existing, dict) else {}
    current = user_profile.get("shopping_wizard_explicit")
    if not isinstance(current, dict):
        current = {}
    current = {**current, **incoming}
    user_profile["shopping_wizard_explicit"] = current
    return current


def _wizard_data(user_profile: dict) -> dict:
    data = user_profile.get("shopping_wizard_data")
    if not isinstance(data, dict):
        data = {}
        user_profile["shopping_wizard_data"] = data
    return data


def seed_wizard_from_entities(
    entities: dict | None,
    *,
    query: str | None = None,
) -> dict:
    """Pre-fill wizard slots from classifier / regex entities (smart-skip)."""
    ents = entities or {}
    seeded: dict[str, Any] = {}

    category = ents.get("category")
    if category:
        seeded["category"] = str(category).strip().lower()

    gender = ents.get("gender")
    if gender in ("women", "men", "kids"):
        # Never smart-skip gender for ambiguous recipients (parents/friend).
        # Carryover / sticky prior Female must not hide "Who is it for?".
        from kisna_chatbot.processors.entity_extractor import is_ambiguous_audience

        if not (query and is_ambiguous_audience(query)):
            seeded["gender"] = gender
    elif query:
        inferred_gender = _gender_from_text(query)
        if inferred_gender:
            seeded["gender"] = inferred_gender

    material = ents.get("material_type")
    if material in ("gold", "diamond", "gemstone"):
        seeded["material_type"] = material

    # A metal the customer ruled out. Carried as a constraint, never as an
    # answer: it narrows what the material step may offer and survives into the
    # search, but it never fills the slot or lets the funnel skip the question.
    excluded = ents.get("excluded_material")
    if excluded in ("gold", "diamond", "gemstone"):
        seeded["excluded_material"] = excluded

    if ents.get("min_price") is not None or ents.get("max_price") is not None:
        seeded["min_price"] = ents.get("min_price")
        seeded["max_price"] = ents.get("max_price")
    elif ents.get("budget") == ANY_SLOT or ents.get("budget") == "any":
        # A budget DECLINED in the opening message is not a number, so the
        # branch above never sees it and the funnel asked for a budget the
        # customer had just given -- in its own prompt's words.
        #
        # LLM-PRIMARY: this reads "any price", "koi budget nahi", "কোনো বাজেট
        # নেই" and every other phrasing, because the model understands the
        # sentence. A phrase list cannot -- that is exactly how the kinship
        # gender bug happened.
        seeded["budget"] = ANY_SLOT
    elif query and _ANY_ANSWER_RE.search(query) and _names_budget(query):
        # Deterministic fallback. Two jobs, and neither is "read more
        # languages" -- do NOT grow this list to chase those; that is the
        # failure the budget field above exists to end.
        #
        # 1. An LLM outage.
        # 2. One genuine parsing ambiguity the model cannot be prompted out
        #    of: in "14kt diamond rings OF any price FOR MEN", the phrase sits
        #    mid-noun-phrase, grammatically parallel to "of 14kt", so the model
        #    reads it as another product attribute rather than a budget
        #    statement (0/5 live, systematic). Ablation showed it needs all
        #    three together -- a karat, "of any price", and a trailing
        #    audience; "at any price" (a fixed idiom) and the same words at the
        #    start or end of the sentence are all read correctly. That reading
        #    is defensible English, and forcing it risks the opposite error.
        seeded["budget"] = ANY_SLOT

    fulfillment = ents.get("fulfillment")
    if fulfillment in ("ready", "mto"):
        seeded["fulfillment"] = fulfillment
    elif query:
        from kisna_chatbot.processors.entity_extractor import extract_fulfillment

        inferred = extract_fulfillment(query)
        if inferred:
            seeded["fulfillment"] = inferred

    return seeded


# Words that name a slot outright, so a decline can be routed to the slot the
# user MEANT rather than whichever question happens to be on screen.
_ANY_ANSWER_SLOT_WORDS = (
    (
        "budget",
        re.compile(
            r"budget|price|bajet|बजट|बजेट|कीमत|दाम|બજેટ|કિંમત|"
            r"বাজেট|দাম|బడ్జెట్|பட்ஜெட்|ಬಜೆಟ್|ബജറ്റ്",
            re.I,
        ),
    ),
)


def _names_budget(text: str) -> bool:
    """True when the message explicitly says 'budget'/'price' (any language)."""
    for slot, pattern in _ANY_ANSWER_SLOT_WORDS:
        if slot == "budget" and pattern.search(text or ""):
            return True
    return False


def _any_answer_target_step(text: str, step: str) -> str:
    """The slot the user declined -- the one they NAMED, not the one we asked.

    "no specific budget" typed at the material step used to set
    material_type = any, because the decline was applied to the question on
    screen. The user named their budget; that is the slot to mark, and the
    material question still needs asking.
    """
    for slot, pattern in _ANY_ANSWER_SLOT_WORDS:
        if pattern.search(text or ""):
            return slot
    return step


def _apply_any_slot(collected: dict, step: str) -> None:
    """Mark a step as answered with "no preference"."""
    if step == "gender":
        collected["gender"] = ANY_SLOT
    elif step == "material":
        collected["material_type"] = ANY_SLOT
    elif step == "budget":
        collected["budget"] = ANY_SLOT
    elif step == "fulfillment":
        collected["fulfillment"] = ANY_SLOT


def get_next_step(collected: dict) -> str | None:
    """Return the next missing step, or None when ready to search.

    Applies dynamic filter-driven skips/auto-sets (Phase 4) before picking
    the next prompt so ≤1-option facets never ask the user.
    """
    apply_dynamic_wizard_skips(collected)
    if not collected.get("category"):
        return "category"
    if not collected.get("gender"):
        return "gender"
    if not collected.get("material_type"):
        return "material"
    if (
        collected.get("budget") != ANY_SLOT
        and collected.get("min_price") is None
        and collected.get("max_price") is None
    ):
        return "budget"
    if not collected.get("fulfillment"):
        return "fulfillment"
    return None


# Clara gender labels → bot-canonical + WhatsApp quick-reply titles.
_CLARA_GENDER_TO_CANONICAL = {
    "women": "women",
    "female": "women",
    "mens": "men",
    "men": "men",
    "male": "men",
    "kids": "kids",
    "kid": "kids",
    "children": "kids",
}
_GENDER_UI_TITLE = {
    "women": "Female",
    "men": "Male",
    "kids": "Kids",
}


def _wizard_category_id(collected: dict) -> str | None:
    cat = collected.get("category")
    if not cat:
        return None
    from kisna_chatbot.integrations.clara_filters import get_category_id
    from kisna_chatbot.processors.entity_extractor import CATEGORY_NORMALIZATION_MAP

    # The wizard stores the raw internal token (e.g. "necklace_set"), but Clara's
    # own category labels are multi-word plurals ("Necklace Sets"). The real
    # search path normalizes through this same map before resolving an id
    # (entity_extractor.entities_to_api_params); this lookup must match it, or
    # get_category_id's singular/plural variant guessing silently fails on
    # short underscored tokens (necklace_set, pendant_set - confirmed: their
    # raw fuzzy-match ratio lands just under the 0.9 cutoff), and the wizard
    # falls back to the global gender list instead of the category-scoped one.
    normalized = CATEGORY_NORMALIZATION_MAP.get(str(cat), str(cat))
    if not normalized:
        return None
    return get_category_id(normalized)


def _canonical_gender_from_clara_label(label: str) -> str | None:
    key = str(label or "").strip().lower()
    return _CLARA_GENDER_TO_CANONICAL.get(key)


def live_gender_options_for_wizard(collected: dict) -> list[dict] | None:
    """Return live gender quick-reply options, or None to use the legacy list.

    None ⇒ filters cold — caller keeps Female/Male/Kids.
    Empty list ⇒ 0 options (caller should have skipped via apply_dynamic_wizard_skips).
    """
    from kisna_chatbot.integrations import clara_filters as cf
    from kisna_chatbot.integrations.clara_filters import (
        FACET_GENDER,
        filters_available,
        get_available_options,
    )

    if not filters_available():
        return None
    cid = _wizard_category_id(collected)
    if cid:
        scoped = cf._resolve_cached_payload(cid)
        if scoped is not None:
            opts = get_available_options(cid, FACET_GENDER, fallback_global=False)
        else:
            # Missing category payload → nearest parent (global).
            opts = get_available_options(None, FACET_GENDER)
    else:
        opts = get_available_options(None, FACET_GENDER)

    ui: list[dict] = []
    seen: set[str] = set()
    for opt in opts:
        canon = _canonical_gender_from_clara_label(str(opt.get("label") or ""))
        if not canon or canon in seen:
            continue
        seen.add(canon)
        ui.append({"title": _GENDER_UI_TITLE.get(canon, canon.title())})
    return ui


def apply_dynamic_wizard_skips(collected: dict) -> None:
    """Silent auto-set / skip wizard slots from cached /filters (Phase 4).

    Rule: ≤1 live option for the scoped category → do not ask.
    Exactly 1 → auto-set that value and log. Zero → leave unset (skip ask).
    Cold / unavailable filters → no-op (legacy behaviour).
    """
    from kisna_chatbot.integrations.clara_filters import (
        FACET_GENDER,
        filters_available,
        get_available_options,
    )
    from kisna_chatbot.utils.logger_config import logger

    if not filters_available():
        return
    cid = _wizard_category_id(collected)
    if not cid:
        return

    from kisna_chatbot.integrations import clara_filters as cf

    scoped = cf._resolve_cached_payload(cid)
    if scoped is None:
        # Nearest parent only — do not skip based on global counts alone.
        return

    if not collected.get("gender"):
        opts = get_available_options(cid, FACET_GENDER, fallback_global=False)
        if len(opts) == 0:
            collected["gender"] = ANY_SLOT
            logger.info(
                "Wizard gender skipped — 0 live options",
                extra={"category_id": cid, "category": collected.get("category")},
            )
        elif len(opts) == 1:
            canon = _canonical_gender_from_clara_label(str(opts[0].get("label") or ""))
            if canon:
                collected["gender"] = canon
                logger.info(
                    "Wizard gender auto-set from filters",
                    extra={
                        "category_id": cid,
                        "category": collected.get("category"),
                        "gender": canon,
                        "label": opts[0].get("label"),
                    },
                )


def start_wizard(
    user_profile: dict,
    *,
    entities: dict | None = None,
    prepend_welcome: list[dict] | None = None,
    query: str | None = None,
) -> list[dict]:
    """Activate wizard, seed known slots, return next prompt messages."""
    collected = seed_wizard_from_entities(entities, query=query)
    # A stale store-wait must not steal later budget answers like "50k", and a
    # stale custom-budget wait must not steal the wizard's own budget step.
    # Sticky waits are mutually exclusive — see clear_all_sticky_states.
    from kisna_chatbot.utils.session_state import clear_all_sticky_states

    clear_all_sticky_states(user_profile)
    user_profile["shopping_wizard_active"] = True
    user_profile["shopping_wizard_data"] = collected
    user_profile["shopping_wizard_explicit"] = extract_explicit_entities(entities)
    step = get_next_step(collected)
    if step is None:
        # Everything known — leave active so caller can complete search.
        user_profile["shopping_wizard_step"] = "complete"
        responses = list(prepend_welcome or [])
        return responses

    user_profile["shopping_wizard_step"] = step
    responses = list(prepend_welcome or [])
    note = _unsupported_material_note(entities)
    if note:
        responses.append(note)
    responses.append(build_step_prompt(step, collected))
    return responses


# Deliberately NOT the search path's constant: that one ends "Here are some
# beautiful options we do have", which is a lie in the funnel — a question
# follows, not products. Only the factual first sentence is shared wording.
_UNSUPPORTED_MATERIAL_FUNNEL_NOTE = (
    "We specialise in *gold, diamond, and gemstone* jewellery — we don't carry "
    "silver, platinum, or pearl. Let's find you something from what we do have 💎"
)


def _unsupported_material_note(entities: dict | None) -> dict | None:
    """Say we don't carry silver/platinum/pearl before offering alternatives.

    seed_wizard_from_entities keeps only gold/diamond/gemstone, so "Kya apke
    pass silver ki ring milti hai kya?" entered the funnel with the material
    silently discarded and the customer was then asked to choose between
    Gold / Diamond / Gemstone as though they had never named silver. The
    direct-search path has always said this; the funnel never did.
    """
    if not (entities or {}).get("unsupported_material"):
        return None
    return {
        "type": "text",
        "text": _UNSUPPORTED_MATERIAL_FUNNEL_NOTE,
        "_compose": "unsupported_material",
    }


def build_budget_rejection_prompt() -> dict:
    """Re-ask after a pincode / phone number was typed at the budget step."""
    return {
        "type": "text",
        "text": (
            "That doesn't look like a budget amount — could you type your "
            "budget in rupees? e.g. *25000* or *1 lakh*"
        ),
        "_compose": "wizard_budget",
    }


def _material_step_subject(collected: dict | None) -> str:
    """What to call the product in the material question.

    By this step the funnel usually knows the category, so ask about the thing
    itself ("What type of rings...") rather than the generic "jewellery". The
    label is interpolated INTO the composed text, not appended after it, so it
    gets translated with the rest of the sentence instead of sitting in English
    inside a Tamil question.
    """
    category = (collected or {}).get("category")
    if not category:
        return "jewellery"
    from kisna_chatbot.processors.product_search_agent_v3 import (
        _humanize_category_label,
    )

    return _humanize_category_label(str(category).strip().lower()) or "jewellery"


def build_step_prompt(step: str, collected: dict | None = None) -> dict:
    collected = collected or {}
    if step == "category":
        return {
            "type": "text",
            "text": (
                "Hi! 👋 What are you looking for today? "
                "e.g. rings, earrings, necklaces…"
            ),
            "_compose": "wizard_category",
        }
    if step == "gender":
        options = [
            {"title": "Female"},
            {"title": "Male"},
            {"title": "Kids"},
        ]
        live = live_gender_options_for_wizard(collected)
        if live is not None and len(live) >= 2:
            options = live
        return {
            "type": "quickreply",
            "text": "Great! Who is it for? (or type *anyone*)",
            "caption": "",
            "options": options,
            "msgid": "wizard$gender",
            "_compose": "wizard_gender",
        }
    if step == "material":
        # Offering a metal the customer has just ruled out reads as not having
        # listened. Only ever removes one of the three, so at least two remain.
        refused = str((collected or {}).get("excluded_material") or "").lower()
        options = [
            {"title": title}
            for title in ("Gold", "Diamond", "Gemstone")
            if title.lower() != refused
        ]
        return {
            "type": "quickreply",
            "text": (
                f"What type of {_material_step_subject(collected)} "
                "are you interested in?"
            ),
            "caption": "",
            "options": options,
            "msgid": "wizard$material",
            "_compose": "wizard_material",
        }
    if step == "budget":
        return {
            "type": "text",
            "text": (
                "What's your budget? e.g. under 25k, 15–35k, around 1 lakh "
                "(or say *no specific budget*)"
            ),
            "_compose": "wizard_budget",
        }
    if step == "fulfillment":
        return {
            "type": "quickreply",
            "text": (
                "Are you looking for a ready-to-ship product or would you "
                "prefer a made-to-order design?"
            ),
            "caption": "",
            "options": [
                {"title": "Ready to ship"},
                {"title": "Made to order"},
                {"title": "Either is fine"},
            ],
            "msgid": "wizard$fulfillment",
            "_compose": "wizard_fulfillment",
        }
    return {
        "type": "text",
        "text": "Tell me a bit more about what you're looking for 🙂",
        "_compose": "wizard_more_info",
    }


def build_wizard_summary(collected: dict) -> str:
    """Final intro before product cards.

    ``collected`` should be the merged entities dict (entities_from_wizard
    output, or equivalent) so karat / metal_colour / collection -- explicit
    fields the confirmation recap already shows -- don't silently vanish
    from this line right after the user confirmed them.
    """
    from kisna_chatbot.processors.search_confirmation import (
        _collection_phrase,
        _metal_phrase,
    )

    parts: list[str] = []
    material = collected.get("material_type")
    metal = _metal_phrase(collected) if material != ANY_SLOT else None
    if metal:
        parts.append(metal)
    category = collected.get("category")
    if category:
        label = category if str(category).endswith("s") else f"{category}s"
        if label == "mangalsutras":
            label = "mangalsutra"
        parts.append(label.replace("_", " "))
    collection = _collection_phrase(collected)
    if collection:
        parts.append(collection)
    max_p = collected.get("max_price")
    min_p = collected.get("min_price")
    if max_p is not None and (min_p is None or float(min_p) == 0):
        parts.append(f"under ₹{int(max_p):,}")
    elif min_p is not None and max_p is not None:
        parts.append(f"₹{int(min_p):,}–₹{int(max_p):,}")
    elif min_p is not None:
        parts.append(f"above ₹{int(min_p):,}")
    desc = " ".join(parts) if parts else "jewellery"
    fulfillment = collected.get("fulfillment")
    if fulfillment == "ready":
        return f"Perfect! Let me show you the best ready-to-ship {desc}."
    if fulfillment == "mto":
        return (
            f"Perfect! Here are {desc} you can get made to order — "
            f"any of these can be crafted for you."
        )
    return f"Perfect! Let me show you the best {desc}."


def entities_from_wizard(collected: dict, explicit: dict | None = None) -> dict:
    """Map wizard data into product-search entities.

    Wizard slot answers win for slot fields. Explicit non-slot fields from the
    original (or mid-wizard) message are merged back so karat / colour /
    collection survive completion.
    """
    # ANY_SLOT fills a slot so the funnel moves on, but it must never reach the
    # API as a filter.
    def _filter(key: str):
        value = collected.get(key)
        return None if value == ANY_SLOT else value

    entities = {
        "category": collected.get("category"),
        "material_type": _filter("material_type"),
        # Survives the funnel so the client-side filter can still honour it when
        # the customer answers the material question with "koi bhi".
        "excluded_material": collected.get("excluded_material"),
        "min_price": collected.get("min_price"),
        "max_price": collected.get("max_price"),
        "gender": _filter("gender"),
        "fulfillment": _filter("fulfillment"),
        "title": None,
        "city": None,
        "pincode": None,
        "karat": None,
        "metal_colour": None,
        "size": None,
        "collection": None,
        "style": None,
        "action": None,
        "occasion": None,
    }
    for key, value in (explicit or {}).items():
        if key not in _EXPLICIT_ENTITY_KEYS:
            continue
        if value is None or value == "" or value == ANY_SLOT:
            continue
        # Slot answers already occupy category/material/gender/fulfillment/
        # budget — never let explicit overwrite those.
        if key in entities and entities.get(key) is not None:
            continue
        entities[key] = value
    return entities


def filter_by_fulfillment(
    products: list[dict],
    fulfillment: str | None,
    *,
    edd_days: int = READY_TO_SHIP_EDD_DAYS,
) -> tuple[list[dict], str | None]:
    """Legacy EDD post-filter — no longer used when Clara readyTOShip is set.

    Kept for tests / emergency fallback only. Prefer API boolean readyTOShip.
    MTO must never post-filter (every product is MTO-eligible).
    """
    if not fulfillment or fulfillment != "ready" or not products:
        return products, None

    ready: list[dict] = []
    for p in products:
        shipping = p.get("shipping") if isinstance(p, dict) else None
        edd = None
        if isinstance(shipping, dict):
            edd = shipping.get("edd")
        try:
            if edd is not None and int(edd) <= edd_days:
                ready.append(p)
        except (TypeError, ValueError):
            continue

    if ready:
        return ready, None
    return products, None


def parse_wizard_button(messages: dict) -> tuple[str, str] | None:
    """Return (step, value) from a wizard quick-reply tap, or None."""
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "button_reply":
        return None
    button_reply = interactive.get("button_reply", {})
    raw_id = button_reply.get("id", "")
    msgid = raw_id
    try:
        parsed = json.loads(raw_id)
        if isinstance(parsed, dict):
            msgid = parsed.get("msgid", raw_id)
    except (json.JSONDecodeError, TypeError):
        pass
    if not isinstance(msgid, str) or not msgid.startswith(_WIZARD_MSGID_PREFIX):
        # Fallback: parent msgid may be wizard$gender — match title maps
        title = (button_reply.get("title") or "").strip().lower()
        if title in _GENDER_TITLE_MAP:
            return "gender", _GENDER_TITLE_MAP[title]
        if title in _MATERIAL_TITLE_MAP:
            return "material", _MATERIAL_TITLE_MAP[title]
        if title in _FULFILLMENT_TITLE_MAP:
            return "fulfillment", _FULFILLMENT_TITLE_MAP[title]
        return None

    parts = msgid.split("$")
    # wizard$gender or wizard$gender$female
    if len(parts) >= 3 and parts[2]:
        step, value = parts[1], parts[2]
        return step, value

    step = parts[1] if len(parts) >= 2 else ""
    title = (button_reply.get("title") or "").strip().lower()
    if step == "gender" and title in _GENDER_TITLE_MAP:
        return "gender", _GENDER_TITLE_MAP[title]
    if step == "material" and title in _MATERIAL_TITLE_MAP:
        return "material", _MATERIAL_TITLE_MAP[title]
    if step == "fulfillment" and title in _FULFILLMENT_TITLE_MAP:
        return "fulfillment", _FULFILLMENT_TITLE_MAP[title]
    return None


def parse_wizard_list(messages: dict) -> tuple[str, str] | None:
    """Return (step, value) from a wizard list reply, or None.

    Occasion list replies are ignored (step removed); kept for stale inbound taps.
    """
    interactive = messages.get("interactive", {})
    if interactive.get("type") != "list_reply":
        return None
    list_reply = interactive.get("list_reply", {})
    raw_id = list_reply.get("id", "")
    postback = ""
    try:
        payload = json.loads(raw_id)
        if isinstance(payload, dict):
            postback = str(payload.get("postbackText", "") or "")
    except (json.JSONDecodeError, TypeError):
        pass

    candidate = postback or ""
    # Stale occasion taps from older sessions — ignore (do not set occasion)
    if candidate.startswith("wizard$occasion$"):
        return None
    return None


def is_wizard_interactive(messages: dict) -> bool:
    return parse_wizard_button(messages) is not None or parse_wizard_list(messages) is not None


def _apply_slot(collected: dict, step: str, value: Any) -> None:
    if step == "category" and value:
        collected["category"] = str(value).strip().lower()
    elif step == "gender" and value:
        collected["gender"] = value
    elif step == "material" and value:
        collected["material_type"] = value
    elif step == "budget":
        if value == ANY_SLOT:
            # "no preference", however the customer phrased it. Without this
            # branch the marker returned by _parse_text_for_step is silently
            # dropped and the step is asked again.
            collected["budget"] = ANY_SLOT
        elif isinstance(value, tuple) and len(value) == 2:
            collected["min_price"] = value[0]
            collected["max_price"] = value[1]
    elif step == "fulfillment" and value:
        collected["fulfillment"] = value


def _budget_from_text(text: str) -> tuple[Any, Any] | None:
    """Deterministic budget read. None when this message states no budget."""
    from kisna_chatbot.processors.entity_extractor import (
        _RANGE_INDICATOR_RE,
        _extract_prices,
        _snap_single_price_to_band,
        extract_entities,
    )

    # A pincode / phone number is never a budget, whichever parser reads it.
    if budget_rejection_reason(text):
        return None

    ents = extract_entities(text)
    min_p = ents.get("min_price")
    max_p = ents.get("max_price")
    if min_p is None and max_p is None:
        # Prefer the shared price parser (handles "15 to 35 thousand").
        min_p, max_p = _extract_prices(text or "")
    if min_p is not None or max_p is not None:
        if max(p for p in (min_p, max_p) if p is not None) > MAX_REALISTIC_BUDGET:
            return None
        return (min_p, max_p)
    # Bare digit fallback ("20000") — never concatenate range halves
    # ("15 to 35 thousand" → "1535"), which _RANGE_INDICATOR_RE below rejects.
    #
    # No length floor: a single stated amount belongs in whatever PRICE_BANDS
    # bracket contains it, at every magnitude. A `len(digits) < 3` floor used
    # to drop 1-2 digit answers here, so "25" never reached the band snapper
    # and fell through to the model's literal read — the recap said "under
    # ₹25" and the search went out with maxPrice=25. Reading the number as
    # given is the predictable rule; a customer who means 25,000 types "25k".
    if _RANGE_INDICATOR_RE.search(text or ""):
        return None
    digits = re.sub(r"[^\d]", "", text or "")
    if not digits or not digits.isdigit():
        return None
    if _looks_like_pincode(digits, text):
        return None
    if int(digits) > MAX_REALISTIC_BUDGET:
        return None
    return _snap_single_price_to_band(int(digits))


def _parse_text_for_step(
    step: str, text: str, llm_entities: dict | None = None
) -> Any | None:
    from kisna_chatbot.processors.entity_extractor import (
        extract_entities,
        normalize_internal_category,
    )

    normalized = " ".join((text or "").strip().lower().split())
    if not normalized:
        return None

    # The LLM is the only slot parser that reads native script — prefer it.
    llm_slots = _llm_slot_values(llm_entities)
    if step == "category" and llm_slots.get("category"):
        return llm_slots["category"]
    if step == "material" and llm_slots.get("material_type"):
        return llm_slots["material_type"]
    if step == "gender" and llm_slots.get("gender"):
        return llm_slots["gender"]
    if step == "fulfillment" and llm_slots.get("fulfillment"):
        return llm_slots["fulfillment"]
    if step == "budget" and llm_slots.get("budget") == ANY_SLOT:
        # The model says the customer declined, in whatever language they said
        # it. _ANY_ANSWER_RE below is Latin + Devanagari only and misses Tamil,
        # Telugu, Kannada and Malayalam declines outright, so without this the
        # funnel re-asks a budget they already waved away.
        return ANY_SLOT

    if step == "budget" and (
        llm_slots.get("min_price") is not None
        or llm_slots.get("max_price") is not None
    ):
        llm_min = llm_slots.get("min_price")
        llm_max = llm_slots.get("max_price")
        # The deterministic parser gets this right every time, so it wins
        # whenever it can read the message; the LLM stays the fallback for
        # native script, which only it can parse.
        #
        # There are two ways the model mangles a single stated amount:
        #   min == max   -- "under 50k" read as an exact price, then widened
        #                   UPWARD, so every result costs more than the ceiling
        #                   the customer gave.
        #   min is None  -- a bare "1 lakh" read as a bare ceiling, so the recap
        #                   says "under Rs 1,00,000" instead of the
        #                   Rs 1,00,000-Rs 1,50,000 bucket kisna.com offers.
        # Guarding only the first left the second live: _budget_from_text was
        # never consulted, because `llm_min is not None` is False for a
        # max-only read. Free-text search already snaps these (see
        # normalize_price_entities); the wizard was the one path that did not.
        deterministic = _budget_from_text(text)
        if deterministic is not None:
            return deterministic
        return (llm_min, llm_max)

    if step == "category":
        ents = extract_entities(text)
        if ents.get("category"):
            return ents["category"]
        guess = normalize_internal_category(
            {"category": normalized.replace(" ", "_")}
        )
        if guess.get("category") and guess["category"] != normalized.replace(
            " ", "_"
        ):
            return guess["category"]
        if ents.get("categories"):
            return ents["categories"][0]
        return None

    if step == "gender":
        return _gender_from_text(text)

    if step == "material":
        if normalized in _MATERIAL_TITLE_MAP:
            return _MATERIAL_TITLE_MAP[normalized]
        for key, val in _MATERIAL_TITLE_MAP.items():
            if key in normalized:
                return val
        ents = extract_entities(text)
        mat = ents.get("material_type")
        if mat in ("gold", "diamond", "gemstone"):
            return mat
        return None

    if step == "budget":
        return _budget_from_text(text)

    if step == "fulfillment":
        if normalized in _FULFILLMENT_TITLE_MAP:
            return _FULFILLMENT_TITLE_MAP[normalized]
        for key, val in _FULFILLMENT_TITLE_MAP.items():
            if key in normalized:
                return val
        from kisna_chatbot.processors.entity_extractor import extract_fulfillment

        return extract_fulfillment(text)

    return None


def advance_wizard(
    user_profile: dict,
    messages: dict,
    *,
    text: str | None = None,
    llm_entities: dict | None = None,
) -> tuple[str, list[dict] | None]:
    """
    Process one wizard turn.

    ``llm_entities`` are the context-free entity extractor's reading of THIS
    message (see ``_current_message_entities``). They are the only slot source
    that parses native script, so they take precedence over the Latin-only
    regex extractor.

    Returns:
        ("prompt", [bot_responses]) — ask next step
        ("complete", None) — all slots filled; caller should search
        ("escape", None) — user bailed; clear and fall through
        ("reask", [bot_responses]) — invalid answer; re-prompt
    """
    from kisna_chatbot.processors.entity_extractor import (
        _CLARA_UNSUPPORTED_MATERIALS,
        extract_entities,
    )
    from kisna_chatbot.utils.rakhi_season import is_rakhi_query

    collected = _wizard_data(user_profile)
    # Drop stale occasion from older sessions
    collected.pop("occasion", None)
    step = user_profile.get("shopping_wizard_step") or get_next_step(collected)
    # Seasonal: rakhi is a title search, not a wizard category. Escape so the
    # entity path can set title=rakhi (wizard completion always zeros title).
    if text and step == "category" and is_rakhi_query(text):
        clear_wizard_state(user_profile)
        return "escape", None
    if step == "occasion":
        step = get_next_step(collected)
        user_profile["shopping_wizard_step"] = step

    # "koi bhi" / "no specific budget" / "skip" read as a browse-everything
    # escape at the category step, but on a filter question they are a real
    # answer — check first so the user is not thrown out of a half-filled
    # funnel for declining to pick.
    if text and step in _ANY_ANSWER_STEPS and _ANY_ANSWER_RE.search(text):
        _apply_any_slot(collected, _any_answer_target_step(text, step))
        user_profile["shopping_wizard_data"] = collected
        next_step = get_next_step(collected)
        if next_step is None:
            user_profile["shopping_wizard_step"] = "complete"
            return "complete", None
        user_profile["shopping_wizard_step"] = next_step
        return "prompt", [build_step_prompt(next_step, collected)]

    if text and (
        _ESCAPE_RE.search(text)
        or (_SHOW_ME_RE.search(text) and _names_new_product(text))
    ):
        clear_wizard_state(user_profile)
        return "escape", None

    # Set on the free-text path below; the button path shares the exit.
    unsupported_note: dict | None = None

    # Interactive answers
    parsed = parse_wizard_button(messages) or parse_wizard_list(messages)
    if parsed:
        ans_step, value = parsed
        if ans_step == "occasion":
            # Stale occasion reply — skip and continue to next missing step
            next_step = get_next_step(collected)
            if next_step is None:
                user_profile["shopping_wizard_step"] = "complete"
                return "complete", None
            user_profile["shopping_wizard_step"] = next_step
            return "prompt", [build_step_prompt(next_step, collected)]
        if ans_step == "gender":
            value = _GENDER_TITLE_MAP.get(str(value).lower(), value)
        if ans_step == "material":
            value = _MATERIAL_TITLE_MAP.get(str(value).lower(), value)
        if ans_step == "fulfillment":
            value = _FULFILLMENT_TITLE_MAP.get(
                str(value).lower().replace("_", " "), value
            )
            if value not in ("ready", "mto"):
                if str(value).lower() in ("ready", "mto"):
                    pass
                elif "ready" in str(value).lower():
                    value = "ready"
                elif "mto" in str(value).lower() or "order" in str(value).lower():
                    value = "mto"
        _apply_slot(collected, ans_step, value)
    elif text:
        # Free-text for current step; also allow multi-slot extraction
        value = _parse_text_for_step(step, text, llm_entities) if step else None
        if value is not None and step:
            _apply_slot(collected, step, value)
        # Opportunistic fill. The LLM pass wins over the Latin-only regex so
        # native-script answers land in the right slot.
        ents = {**extract_entities(text or ""), **_llm_slot_values(llm_entities)}
        update_wizard_explicit(user_profile, {**ents, **(llm_entities or {})})
        # Did THIS message name a metal we don't stock? The LLM is the
        # primary reader -- it is the only one that parses native script,
        # so "चांदी की" / "பிளாட்டினம்" are seen here too, not just "silver".
        # Scoped to this message on purpose: reading it off `collected`
        # would re-emit the note on every later turn of the funnel.
        named_material = (llm_entities or {}).get("material_type") or ents.get(
            "material_type"
        )
        unsupported_note = (
            _unsupported_material_note({"unsupported_material": True})
            if named_material in _CLARA_UNSUPPORTED_MATERIALS
            else None
        )
        before = dict(collected)
        seeded = seed_wizard_from_entities(ents, query=text)
        for k, v in seeded.items():
            if v is None:
                continue
            if k in ("gender", "material_type", "fulfillment") and k != step:
                # Only let a later turn overwrite an audience / material /
                # shipping choice when THIS message actually restates it.
                # Without the evidence check a stray word ("recommend",
                # "ornaments") silently flipped a slot the user had already
                # chosen by tapping a button. Material must be overwriteable
                # so "I want in gold" replaces a prior diamond pick.
                if _slot_restated_in_text(k, v, text, llm_entities):
                    collected[k] = v
                elif not collected.get(k):
                    collected[k] = v
            elif k in ("min_price", "max_price"):
                # Budget is a pair — handled below when restated.
                continue
            elif not collected.get(k):
                collected[k] = v
        # Replace the whole budget when the user restates it mid-funnel
        # ("under 40k" at fulfillment). Empty-only fill left 15–30k stuck.
        if _budget_restated_in_text(text, llm_entities):
            # `ents` merges the model's read LAST, so a bare "1 lakh" that the
            # model saw as a bare ceiling landed here as (None, 100000) and
            # overwrote the banded value _parse_text_for_step had just worked
            # out. Same rule as there: the deterministic parser wins whenever it
            # can read the message, the model stays the native-script fallback.
            restated = _budget_from_text(text)
            if restated is None:
                restated = (ents.get("min_price"), ents.get("max_price"))
            collected["min_price"], collected["max_price"] = restated
            collected.pop("budget", None)
        if unsupported_note and step == "material":
            # "silver" is a real answer to "what type of ring?" -- it is just
            # one we cannot fulfil. Accepting it silently sent the customer
            # down the funnel to the budget question and on to results that
            # were never silver; re-asking without the note looped them on the
            # same screen with no idea why. Say why, then re-ask.
            collected.pop("material_type", None)
            user_profile["shopping_wizard_data"] = collected
            user_profile["shopping_wizard_step"] = step
            return "reask", [unsupported_note, build_step_prompt(step, collected)]
        if value is None and collected == before and step:
            # Nothing parsed — re-ask
            user_profile["shopping_wizard_step"] = step
            if step == "budget" and budget_rejection_reason(text):
                return "reask", [build_budget_rejection_prompt()]
            if unsupported_note:
                return "reask", [unsupported_note, build_step_prompt(step, collected)]
            return "reask", [build_step_prompt(step, collected)]
    else:
        if step:
            return "reask", [build_step_prompt(step, collected)]
        return "complete", None

    user_profile["shopping_wizard_data"] = collected
    next_step = get_next_step(collected)
    if next_step is None:
        user_profile["shopping_wizard_step"] = "complete"
        return "complete", None

    user_profile["shopping_wizard_step"] = next_step
    prompt = build_step_prompt(next_step, collected)
    if unsupported_note:
        return "prompt", [unsupported_note, prompt]
    return "prompt", [prompt]


def should_start_wizard(entities: dict | None, *, confidence: float = 1.0) -> bool:
    """True when product search should enter the guided funnel.

    Smart-skip: if every slot is already known, skip the wizard entirely.
    """
    from kisna_chatbot.utils.rakhi_season import should_skip_wizard_for_rakhi

    if should_skip_wizard_for_rakhi(entities):
        return False
    collected = seed_wizard_from_entities(entities)
    if get_next_step(collected) is None:
        return False
    return True
