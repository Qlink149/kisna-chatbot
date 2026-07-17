"""Run the classifier accuracy matrix and print a results table.

Usage:
    python scripts/run_classifier_audit.py          # regex/shortcut layer only
    python scripts/run_classifier_audit.py --llm    # full audit against live LLM
                                                    # (needs real OPENAI_API_KEY in .env)
"""

import asyncio
import os
import sys

USE_LLM = "--llm" in sys.argv

os.environ.setdefault("ENV_MODE", "dev")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
if not USE_LLM:
    # Fake key only for the offline run; in --llm mode load_dotenv() (override=False)
    # must see the real key from .env, so we must not pre-set it here.
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt")
os.environ.setdefault("SYSTEM_API_KEY", "test-api")
os.environ.setdefault("KISNA_PRODUCT_API", "https://example.com/products")
os.environ.setdefault("KISNA_CLARA_BASE_URL", "https://clara.example.com")
os.environ.setdefault("CLARA_API_KEY", "test-clara-key")
os.environ.setdefault("GUPSHUP_APP_ID", "test-app-id")
os.environ.setdefault("GUPSHUP_TOKEN", "test-token")
os.environ.setdefault("GUPSHUP_APP_NAME", "test-app")
os.environ.setdefault("GUPSHUP_API_KEY", "test-api-key")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("KISNA_OFFERS_API", "https://example.com/offers")
os.environ.setdefault("KISNA_STORE_API", "https://example.com/stores")
os.environ.setdefault("KISNA_VTIGER_BASE", "https://example.com/crm")
os.environ.setdefault("KISNA_VTIGER_TOKEN", "test-vtiger")
os.environ.setdefault("KISNA_PHONE_NUMBER_ID", "850788844795304")

from kisna_chatbot.main import app  # noqa: F401
from kisna_chatbot.processors.classifier import classify_query_for_audit

MATRIX = [
    ("show me diamond rings", "product_search"),
    ("gold earrings", "product_search"),
    ("sone ki anguthi dikhao", "product_search"),
    ("heere ki bali 50k tak", "product_search"),
    ("necklace under 30000", "product_search"),
    ("Rivaah collection", "product_search"),
    ("mangalsutra dikhao", "product_search"),
    ("1.5 lakh tak kuch dikhao", "product_search"),
    ("anniversary ke liye kuch accha dikhao", "product_search"),
    ("something for my wife", "product_search"),
    ("Evil Eye bracelet", "product_search"),
    ("daily wear ring", "product_search"),
    ("wedding jewellery", "product_search"),
    ("what is the price of Elysia ring?", "product_info"),
    ("is this available in 18KT?", "product_info"),
    ("does it come with chain?", "product_info"),
    ("how many days delivery?", "product_info"),
    ("Maggio ring ki price kya hai?", "product_info"),
    ("yeh ring ka weight kitna hai?", "product_info"),
    ("koi offer hai kya?", "offers"),
    ("aaj kya discount hai?", "offers"),
    ("making charge offer batao", "offers"),
    ("sale chal rahi hai?", "offers"),
    ("koi cashback milega?", "offers"),
    ("nearest store", "store_info"),
    ("Mumbai mein store", "store_info"),
    ("store near 302001", "store_info"),
    ("KISNA showroom kahan hai?", "store_info"),
    ("Jaipur outlet", "store_info"),
    ("mera order kahan hai?", "order_tracking"),
    ("order track karna hai", "order_tracking"),
    ("delivery kab hogi?", "order_tracking"),
    ("order status", "order_tracking"),
    ("return karna hai", "returns_refund"),
    ("refund chahiye", "returns_refund"),
    ("product wapas karna hai", "returns_refund"),
    # "possible hai?" is a policy QUESTION (rule 11a) -> general
    ("exchange possible hai?", "general"),
    ("complaint darz karni hai", "complaint"),
    ("product kharab nikla", "complaint"),
    ("wrong item aaya", "complaint"),
    ("damage hua hai", "complaint"),
    ("agent se baat karni hai", "human_handoff"),
    ("mujhe kisi se baat karni hai", "human_handoff"),
    ("human support chahiye", "human_handoff"),
    ("kya hallmark jewellery hai?", "general"),
    ("EMI available hai?", "general"),
    ("return policy kya hai?", "general"),
    ("certificate kya hota hai?", "general"),
    ("KISNA ki guarantee kya hai?", "general"),
    ("BIS certified hai?", "general"),
    ("Hi", "greeting"),
    ("hello", "greeting"),
    ("namaste", "greeting"),
    ("hey", "greeting"),
    # --- routing v2: gold rate ---
    ("aaj ka gold rate kya hai?", "gold_rate"),
    ("sona kitne ka chal raha hai", "gold_rate"),
    ("22kt ka bhav batao", "gold_rate"),
    ("gold price today", "gold_rate"),
    # --- routing v2: video call ---
    ("can you schedule a video call?", "video_call"),
    ("video pe jewellery dikha sakte ho", "video_call"),
    ("video consultation book karni hai", "video_call"),
    # --- routing v2: schemes / KMR -> KB ---
    ("koi scheme hai kya", "general"),
    ("KMR ke baare mein batao", "general"),
    ("gold saving plan available?", "general"),
    ("meri roshni plan kya hai", "general"),
    # --- routing v2: custom jewellery ---
    ("custom ring banwana hai", "human_handoff"),
    ("engraving karwana hai", "human_handoff"),
]

# LLM-only rows: no regex shortcut exists on purpose; skipped in offline mode.
LLM_MATRIX = [
    ("mera order damage aa gaya", "complaint"),
    ("order cancel karna hai", "human_handoff"),
    ("show me some lightweight rings", "product_search"),
    ("necklaces under 50k", "product_search"),
    ("shaadi ke liye kuch dikhao budget 1 lakh", "product_search"),
    ("book me a flight to Delhi", "general"),
    ("monthly installment plan hai kya jewellery ke liye?", "general"),
    ("kya aap hindi samajhte ho?", "general"),
    ("gold ring dikhao aur nearest store bhi batao", "product_search"),
    ("mujhe kuch gift karna hai wife ko", "product_search"),
]


async def main() -> None:
    rows = list(MATRIX) + (list(LLM_MATRIX) if USE_LLM else [])
    mode = "LLM + shortcuts" if USE_LLM else "shortcuts only"
    print(f"Mode: {mode} ({len(rows)} queries)")
    print("Input | Expected | Actual | Confidence | Source | PASS/FAIL")
    print("-" * 80)
    passed = 0
    failures: list[tuple[str, str, str, float, str]] = []
    for text, expected in rows:
        result = await classify_query_for_audit(text, use_llm=USE_LLM)
        actual = result["intent"]
        conf = result["confidence"]
        source = result["source"]
        ok = actual == expected
        passed += int(ok)
        if not ok:
            failures.append((text, expected, actual, conf, source))
        status = "PASS" if ok else "FAIL"
        print(
            f"{text!r} | {expected} | {actual} | {conf} | {source} | {status}"
        )
    print(f"\n{mode}: {passed}/{len(rows)} passed, {len(failures)} failed")
    if failures:
        print("\nFailures:")
        for text, expected, actual, conf, source in failures:
            print(f"  {text!r}: expected {expected}, got {actual} ({conf}, {source})")


if __name__ == "__main__":
    asyncio.run(main())
