"""Seasonal Raksha Bandhan title search overlay.

Clara has no rakhi category; live pieces match title=rakhi. Flip
``RAKHI_TITLE_SEARCH_ENABLED`` to False after the festival — prompts, title
hint, and wizard skip all no-op and existing gift/wizard behavior returns.
"""

from __future__ import annotations

import re
from typing import Any

# Seasonal: Raksha Bandhan title search. Set False after the festival.
RAKHI_TITLE_SEARCH_ENABLED = True

RAKHI_API_TITLE = "rakhi"

_RAKHI_SYNONYMS: tuple[str, ...] = (
    "rakhi",
    "rakhni",
    "rakhee",
    "rakkhi",
    "rakhis",
    "raksha bandhan",
    "rakshabandhan",
    "राखी",
    "रक्षा बंधन",
    "रक्षाबंधन",
)

_ASCII_WORD_RE = {
    syn: re.compile(rf"\b{re.escape(syn)}\b", re.I)
    for syn in _RAKHI_SYNONYMS
    if syn.isascii() and " " not in syn
}

RAKHI_INTENT_PROMPT_SNIPPET = """
## RAKHI SEASON (catalogue title search — not a jewellery type)
rakhi / rakhni / rakhee / rakkhi / raksha bandhan / राखी / रक्षा बंधन → product_search
(these are jewellery pieces in the catalogue). "happy rakhi" / festival wishes
with no browse/buy words → greeting, not product_search.
"""

RAKHI_EXTRACTOR_PROMPT_SNIPPET = """
## RAKHI SEASON OVERRIDE (takes precedence over occasion=gift for these words)
rakhi / rakhni / rakhee / rakkhi / rakhis / raksha bandhan / rakshabandhan /
राखी / रक्षा बंधन / रक्षाबंधन → title="rakhi", category=null unless the user
ALSO named a jewellery type (e.g. "rakhi pendant" may keep category=pendant).
Do NOT set occasion=gift from those words alone.

"rakhni dikhao" →
{"title":"rakhi"}

"gold rakhi" →
{"title":"rakhi","material_type":"gold"}
"""


def is_rakhi_query(text: str | None) -> bool:
    """True when the current message names rakhi (typos included). Flag-gated."""
    if not RAKHI_TITLE_SEARCH_ENABLED:
        return False
    normalized = (text or "").lower().strip()
    if not normalized:
        return False
    for syn in _RAKHI_SYNONYMS:
        if syn.isascii() and " " not in syn:
            if _ASCII_WORD_RE[syn].search(normalized):
                return True
        elif syn in (text or "") or syn in normalized:
            return True
    return False


def apply_rakhi_title_hint(
    entities: dict[str, Any] | None,
    *,
    query: str | None = None,
) -> dict[str, Any]:
    """Set title=rakhi when the query (or an already-extracted title) is rakhi.

    No-op when the seasonal flag is off. Never sets or clears category,
    material, price, or gender.
    """
    out = dict(entities or {})
    if not RAKHI_TITLE_SEARCH_ENABLED:
        return out

    current_title = str(out.get("title") or "").strip().lower()
    if query is not None:
        if is_rakhi_query(query):
            out["title"] = RAKHI_API_TITLE
        return out
    if current_title in {s.lower() for s in _RAKHI_SYNONYMS if s.isascii()}:
        out["title"] = RAKHI_API_TITLE
    return out


def should_skip_wizard_for_rakhi(entities: dict[str, Any] | None) -> bool:
    """Title-only rakhi searches already have Clara scope — skip the funnel."""
    if not RAKHI_TITLE_SEARCH_ENABLED:
        return False
    title = str((entities or {}).get("title") or "").strip().lower()
    return title == RAKHI_API_TITLE
