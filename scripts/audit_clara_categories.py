"""Probe Clara API category query strings and record which return 200 with products."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Load .env when run locally (does not override existing env vars).
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

CANDIDATES = [
    "ring",
    "rings",
    "earring",
    "earrings",
    "necklace",
    "necklaces",
    "pendant",
    "pendants",
    "bangle",
    "bangles",
    "bracelet",
    "bracelets",
    "mangalsutra",
    "maang tikka",
    "maang_tikka",
    "Maang Tikka",
    "MaangTikka",
    "nose wear",
    "nose_wear",
    "nosewear",
    "Nose Wear",
    "watch wear",
    "watch_wear",
    "watchwear",
    "Watch Wear",
    "mangalsutra bracelet",
    "mangalsutra_bracelet",
    "chain",
    "solitaire",
    "pendant set",
    "pendant_set",
    "necklace set",
    "necklace_set",
]


def main() -> int:
    base = (os.environ.get("KISNA_CLARA_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("CLARA_API_KEY") or "").strip()
    if not base or not key:
        print("Set KISNA_CLARA_BASE_URL and CLARA_API_KEY in the environment.")
        return 1

    print(f"{'Category':35} Status  Count")
    print("-" * 55)
    results: dict[str, tuple[int, int | str]] = {}

    with httpx.Client(timeout=10.0) as client:
        for cat in CANDIDATES:
            response = client.get(
                f"{base}/api/v1/clara/products",
                headers={"x-clara-api-key": key},
                params={"pageNo": 1, "pageSize": 3, "category": cat},
            )
            count: int | str = 0
            if response.status_code == 200:
                try:
                    count = int(response.json()["data"]["totalCount"])
                except (KeyError, TypeError, ValueError):
                    count = "?"
            results[cat] = (response.status_code, count)
            print(f"{cat:35} {response.status_code}      {count}")

    out_path = ROOT / "scripts" / "audit_clara_categories_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {cat: {"status": status, "count": count} for cat, (status, count) in results.items()},
            f,
            indent=2,
        )
    print(f"\nSaved results to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
