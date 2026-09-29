"""Seed the ``stores`` collection from data/stores_seed.json -- LOCAL / DEV ONLY.

    python scripts/seed_stores.py --dry-run          # normalise + report, no DB
    python scripts/seed_stores.py                    # local Mongo only
    python scripts/seed_stores.py --dev-database     # a remote DEV database

Refuses to run when ENV_MODE=prod, and refuses any non-local MONGO_URI unless
--dev-database is passed. Production stores are loaded through the dashboard
CSV upload, never this script.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import Counter
from urllib.parse import urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = ROOT / "data" / "stores_seed.json"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "mongo", "mongodb"}


def _mongo_host(uri: str) -> str:
    try:
        netloc = urlparse(uri).netloc.rsplit("@", 1)[-1]
        return netloc.split(",")[0].split(":")[0].lower()
    except Exception:
        return ""


def load_seed(path: pathlib.Path = SEED) -> list[dict]:
    from kisna_chatbot.stores.model import from_kisna_record

    raw = json.loads(path.read_text(encoding="utf-8"))
    return [from_kisna_record(r) for r in raw["stores"]]


def report(stores: list[dict]) -> None:
    from kisna_chatbot.stores.model import duplicate_report

    active = [s for s in stores if s["active"] and s["bookable"]]
    states = Counter(s["state"] for s in active)
    cities: dict[str, set] = {}
    per_city = Counter()
    for s in active:
        cities.setdefault(s["state"], set()).add(s["city"])
        per_city[(s["state"], s["city"])] += 1
    big_state = max(cities.items(), key=lambda kv: len(kv[1]))
    big_city = per_city.most_common(1)[0]
    print(f"stores: {len(stores)} (bookable+active: {len(active)})")
    print(f"states: {len(states)}  largest city list: {big_state[0]} ({len(big_state[1])})")
    print(f"largest store list: {big_city[0][1]}, {big_city[0][0]} ({big_city[1]})")
    hours = Counter((s["open_time"], s["close_time"]) for s in stores)
    print("hours:", ", ".join(f"{o}-{c} x{n}" for (o, c), n in hours.most_common()))
    print("weekly_off:", dict(Counter(tuple(s["weekly_off"]) for s in stores)))
    dups = duplicate_report(stores)
    print("duplicates:", {k: v for k, v in dups.items()} if any(dups.values()) else "none")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dev-database", action="store_true")
    args = ap.parse_args()

    stores = load_seed()
    report(stores)
    if args.dry_run:
        return 0

    if os.getenv("ENV_MODE", "dev").lower() == "prod":
        print("REFUSED: ENV_MODE=prod. Load production stores via the dashboard CSV upload.")
        return 2
    host = _mongo_host(os.getenv("MONGO_URI", ""))
    if host not in _LOCAL_HOSTS and not args.dev_database:
        print(f"REFUSED: MONGO_URI host {host!r} is not local. Pass --dev-database for a dev DB.")
        return 2

    from kisna_chatbot.stores.repo import ensure_indexes, upsert_many

    ensure_indexes()
    print("upserted:", upsert_many(stores))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
