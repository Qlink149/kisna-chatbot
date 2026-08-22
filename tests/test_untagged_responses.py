"""Every canned reply we write must be tagged for translation, or listed here.

``localize_bot_responses`` only rewrites bot_response items carrying a
"_compose" key. Anything else reaches the customer in whatever language the
code was written in — English. That is invisible in English testing and
invisible to every other test in this suite, so it grew to ~46 untagged
customer-facing strings before anyone noticed: a Marathi customer asking for a
human was told "Our team is currently offline" in English, at the one moment in
the conversation they most need to understand the answer.

This test does not ban untagged responses — several MUST stay untagged. It bans
*new* ones appearing without a decision being recorded. If this fails, either
add "_compose" to the new response, or add it to ALLOWED below with a reason.
"""

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "kisna_chatbot"

# A dict literal with "type": "text" | "cta_url" and no nested braces.
# text, cta_url and flow all carry customer-facing prose in "text".
ITEM_RE = re.compile(
    r"\{[^{}]*?[\"']type[\"']\s*:\s*[\"'](?:text|cta_url|flow)[\"'][^{}]*?\}", re.S
)

# Untagged ON PURPOSE. Key is "<path>:<text expression>", value is why.
ALLOWED = {
    # --- already in the customer's language: the model wrote it -------------
    "processors/product_search_agent_v3.py:spoken": "LLM answer, already localised",
    "processors/general_agent.py:result.message_text": "LLM answer, already localised",
    "processors/callback_agent.py:resolved": "LLM/flow answer, already localised",
    "processors/product_details_agent.py:text": "answer text built upstream",
    "processors/product_details_agent.py:answer": "LLM answer, already localised",
    "processors/product_details_agent.py:answer or format_product_buy_caption(product),":
        "LLM answer, falling back to product data",
    "processors/secondary_intent.py:text": "delegates to the tagged builders",
    # --- must NEVER be translated -----------------------------------------
    "processors/ad_flow_agent.py:text": "store card: name/address are proper nouns",
    "processors/product_search_agent_v3.py:format_product_buy_caption(cheapest)":
        "product name and price",
    "processors/pre_order_agent.py:text": "order/product data",
    "processors/complaint_agent.py:\"\\n\".join(lines)": "ticket data echoed back",
    "processors/callback_agent.py:\"\\n\".join(lines)": "slot data echoed back",
    "processors/pre_order_agent.py:\"\\n\".join(lines)": "order data echoed back",
    # Clara API error text — comes from the API, not from us.
    "processors/product_search_agent_v3.py:e.args[0]": "upstream API error text",
    "processors/ad_flow_agent.py:e.args[0]": "upstream API error text",
    # Callback/complaint prompts assembled from flow state, not canned prose.
    "processors/callback_agent.py:error": "flow validation text built upstream",
    "processors/callback_agent.py:prompt": "flow prompt built upstream",
    "processors/ad_flow_agent.py:reprompt_text": "tagged at the call site",
    "processors/order_tracking_agent.py:text": "order id / tracking data",
    # --- the localiser never sees these -----------------------------------
    # ResponseManager builds its fallbacks AFTER main.py has localised, so a
    # tag here would be dead code. Fixing these means moving them earlier or
    # localising inside ResponseManager — a real gap, tracked separately.
    "processors/response_manager.py:*": "built after localisation runs",
    # The admin takeover route calls send_text_message directly.
    "routes/system_sub_routes/conversation.py:*": "admin route, bypasses localiser",
    # WhatsApp Flow payloads go straight to the Gupshup API and never become a
    # bot_response at all, so _compose cannot reach them.
    "whatsapp_functions/*": "direct Gupshup Flow API payload, not a bot_response",
}


def _text_expression(blob: str) -> str:
    m = re.search(r"[\"']text[\"']\s*:\s*(.+?)(?:,\s*[\"']|\s*\})", blob, re.S)
    return " ".join(m.group(1).split()) if m else "?"


def _allowed(rel: str, expr: str) -> bool:
    for pattern in ALLOWED:
        # "dir/*" exempts a whole directory; "file.py:*" a whole file;
        # "file.py:<expr>" one specific response.
        if pattern.endswith("*") and ":" not in pattern:
            if rel.startswith(pattern[:-1]):
                return True
            continue
        path_part, _, expr_part = pattern.partition(":")
        if rel != path_part:
            continue
        if expr_part in ("*", expr):
            return True
    return False


def _untagged() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        src = path.read_text(encoding="utf-8")
        for m in ITEM_RE.finditer(src):
            blob = m.group(0)
            if "_compose" in blob:
                continue
            expr = _text_expression(blob)
            if _allowed(rel, expr):
                continue
            line = src[: m.start()].count("\n") + 1
            found.append((rel, line, expr))
    return found


class UntaggedResponseTests(unittest.TestCase):
    def test_no_new_untagged_customer_facing_responses(self):
        found = _untagged()
        if found:
            listing = "\n".join(f"    {r}:{ln}  text={e}" for r, ln, e in found)
            self.fail(
                "Customer-facing responses with no \"_compose\" tag — these reach "
                "every non-English customer in English:\n" + listing +
                "\n\nAdd \"_compose\": \"<key>\" to the response, or add it to "
                "ALLOWED in this file with the reason it must stay untagged."
            )

    def test_the_allowlist_itself_is_not_a_blanket(self):
        """A wildcard per file would defeat the point of the test."""
        wildcards = [k for k in ALLOWED if k.endswith(":*") or k.endswith("*")]
        self.assertLessEqual(
            len(wildcards), 3,
            "Too many wildcard exemptions — the guardrail stops guarding.",
        )

    def test_every_tagged_response_parses(self):
        """A tag inserted into the wrong place would be a syntax error."""
        for path in sorted(ROOT.rglob("*.py")):
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:  # pragma: no cover
                self.fail(f"{path}:{exc.lineno} {exc.msg}")


if __name__ == "__main__":
    unittest.main()
