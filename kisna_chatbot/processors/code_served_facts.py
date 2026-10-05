"""Facts served by code, not by the model.

A fact lands here when the model's own prior beats the prompt: several prompt
wordings at temperature 0.2 still produce the common-but-wrong answer, so the
reply is decided in code and the model never sees the question.

    1. Making-charge percentages -- classifier.py `_MAKING_CHARGES_RE` hard-routes
       every making-charge question to View Offers (the live Clara slab); the
       model is told never to quote a figure and the campaigns block never gives
       it one.
    2. 14KT vs 18KT (KB v2.1, 2026-09-27) -- `karat_comparison_response` below.
       gpt-4o-mini kept saying "18K has a richer colour, 14K is more durable" and
       inventing "58.3%" through three prompt wordings; the client's position is
       that purity is the only difference.
    3. "Which banks offer EMI?" (client test, 2026-10-05) -- `emi_banks_response`
       below. Reason: client requires exact wording (their "Customers commonly
       ask" paragraph, verbatim); the model's paraphrase was flagged.

If a THIRD fact needs this treatment, revisit the model choice, not the prompt.
"""

from __future__ import annotations

import re

# "14K", "14 kt", "18KT", "18 karat", "22 carat" ...
_KARAT = r"\b(?:9|14|18|22|24)\s*(?:k|kt|kts|karat|carat|ct)\b"
_KARAT_RE = re.compile(_KARAT, re.I)
_COMPARE_RE = re.compile(
    r"\b(?:better|best|difference|differ\w*|vs\.?|versus|or|compare\w*|comparison)\b",
    re.I,
)

KARAT_COMPARISON_TEXT = (
    "Certainly! 💍 The main difference between 14KT and 18KT is the gold purity "
    "— 18KT contains 75% pure gold, 14KT a little less. Visually, there is "
    "generally no significant difference. Both are available at KISNA. If you'd "
    "like, I can help you find a design in either. ✨"
)
KARAT_COMPARISON_COMPOSE_KEY = "karat_comparison_canned"
# Kept exactly as written through translation (reply_composer honours "_pin").
KARAT_COMPARISON_PINS = ("14KT", "18KT", "75%")


# Shopping phrasing: "show me 18K rings or earrings" is a search, not a
# question about purity -- it must reach product search, not this answer.
_BROWSE_RE = re.compile(
    r"\b(?:show|dikhao|dikha|find|search|browse|under|below|above|budget|price|"
    # budgets from 30k up -- never a karat (9/14/18/22/24)
    r"(?:[3-9]\d|\d{3,})\s*k|rs\.?|inr)\b|₹",
    re.I,
)


def is_karat_comparison(text: str | None) -> bool:
    """Two karats together, or one karat plus a comparison word -- unless the
    message is a shopping search."""
    t = text or ""
    if _BROWSE_RE.search(t):
        return False
    karats = _KARAT_RE.findall(t)
    if len(karats) >= 2:
        return True
    return len(karats) == 1 and bool(_COMPARE_RE.search(t))


EMI_BANKS_TEXT = (
    "Please note that EMI options are currently not available directly at KISNA. "
    "However, you can conveniently make your payment using a Credit Card from a "
    "major bank and, if your bank offers the option, convert the transaction into "
    "an EMI.\n\n"
    "For any assistance or queries regarding the EMI conversion process, we kindly "
    "recommend reaching out to your bank\u2019s customer support team. They will be "
    "happy to guide you further. 💳✨"
)
EMI_BANKS_COMPOSE_KEY = "emi_banks_canned"
_EMI_RE = re.compile(r"\bemis?\b", re.I)
_BANK_RE = re.compile(r"\bbanks?\b", re.I)


def is_emi_banks_question(text: str | None) -> bool:
    """An EMI question that names banks ("Which banks offer EMI?")."""
    t = text or ""
    return bool(_EMI_RE.search(t) and _BANK_RE.search(t))


def emi_banks_response() -> list[dict]:
    return [{"type": "text", "text": EMI_BANKS_TEXT, "_compose": EMI_BANKS_COMPOSE_KEY, "_pin": ("KISNA", "EMI")}]


def serve_emi_banks(data: dict) -> None:
    data["bot_response"] = emi_banks_response()
    data["classified_category"] = "emi_banks"
    data["_trace_outcome"] = "canned_sent"
    try:
        from kisna_chatbot.utils.message_trace import trace_step

        trace_step(data, "Result", "Canned answer: EMI banks (client wording, served by code)")
    except Exception:
        pass


def karat_comparison_response() -> list[dict]:
    """The client-approved answer, tagged for faithful translation (compose)."""
    return [
        {
            "type": "text",
            "text": KARAT_COMPARISON_TEXT,
            "_compose": KARAT_COMPARISON_COMPOSE_KEY,
            "_pin": KARAT_COMPARISON_PINS,
        }
    ]


def serve_karat_comparison(data: dict) -> None:
    """Set the canned karat answer on `data`, marked canned for the dashboard."""
    data["bot_response"] = karat_comparison_response()
    data["classified_category"] = "karat_comparison"
    data["_trace_outcome"] = "canned_sent"
    try:
        from kisna_chatbot.utils.message_trace import trace_step

        trace_step(data, "Result", "Canned answer: 14KT vs 18KT (fact served by code)")
    except Exception:
        pass
