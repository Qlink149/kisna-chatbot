#!/usr/bin/env python3
"""Compare live Clara GET /filters against the committed snapshot.

Usage (from repo root, with .env loaded):
  python scripts/report_filters_drift.py

Exit code 0 always (report only). Writes audit/filters_drift_report.json.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

SNAPSHOT_PATH = (
    ROOT / "kisna_chatbot" / "integrations" / "data" / "clara_filters_snapshot.json"
)
OUT_PATH = ROOT / "audit" / "filters_drift_report.json"


def _labels(payload: dict | None, facet: str) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    opts = payload.get(facet) or []
    out: set[str] = set()
    for opt in opts:
        if isinstance(opt, dict) and opt.get("label"):
            out.add(str(opt["label"]).strip().lower())
    return out


async def _fetch_live() -> dict:
    import httpx

    base = (os.getenv("KISNA_CLARA_BASE_URL") or "").rstrip("/")
    key = (os.getenv("CLARA_API_KEY") or "").strip()
    if not base or not key:
        raise SystemExit("KISNA_CLARA_BASE_URL and CLARA_API_KEY required")

    headers = {"x-clara-api-key": key}
    async with httpx.AsyncClient(timeout=60) as client:
        global_r = await client.get(f"{base}/api/v1/clara/filters", headers=headers)
        global_r.raise_for_status()
        global_payload = global_r.json().get("data") or global_r.json()

        by_category: dict[str, dict] = {}
        cats = global_payload.get("categories") or []
        for cat in cats:
            cid = str(cat.get("value") or "")
            if not cid:
                continue
            r = await client.get(
                f"{base}/api/v1/clara/filters",
                params={"categoryId": cid},
                headers=headers,
            )
            if r.status_code != 200:
                continue
            by_category[cid] = {
                "label": cat.get("label"),
                "payload": r.json().get("data") or r.json(),
            }
    return {"global": global_payload, "by_category": by_category}


def _diff_facets(live: dict, snap: dict, facets: list[str]) -> dict:
    report: dict = {}
    for facet in facets:
        live_l = _labels(live, facet)
        snap_l = _labels(snap, facet)
        report[facet] = {
            "live_count": len(live_l),
            "snapshot_count": len(snap_l),
            "added": sorted(live_l - snap_l),
            "removed": sorted(snap_l - live_l),
        }
    return report


async def main() -> None:
    snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    live = await _fetch_live()
    facets = ["karat", "color", "collection", "gender", "categories", "availability"]

    snap_global = snap.get("global") or {}
    if isinstance(snap_global, dict) and "payload" in snap_global:
        snap_global = snap_global.get("payload") or {}

    global_diff = _diff_facets(live["global"], snap_global, facets)
    per_cat: dict = {}
    snap_by = snap.get("by_category") or {}
    for cid, entry in live["by_category"].items():
        snap_entry = snap_by.get(cid)
        snap_payload: dict = {}
        if isinstance(snap_entry, dict):
            snap_payload = snap_entry.get("payload") or snap_entry
        per_cat[cid] = {
            "label": entry.get("label"),
            "in_snapshot": cid in snap_by,
            "diff": _diff_facets(
                entry.get("payload") or {},
                snap_payload if isinstance(snap_payload, dict) else {},
                ["karat", "color", "collection", "gender", "availability"],
            ),
        }

    live_ids = set(live["by_category"])
    snap_ids = set(snap_by)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_path": str(SNAPSHOT_PATH.relative_to(ROOT)),
        "global": global_diff,
        "categories_only_live": sorted(live_ids - snap_ids),
        "categories_only_snapshot": sorted(snap_ids - live_ids),
        "by_category": per_cat,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")
    # One-line summary
    added = sum(len(v["added"]) for v in global_diff.values())
    removed = sum(len(v["removed"]) for v in global_diff.values())
    print(f"Global facet label drift: +{added} / -{removed}")


if __name__ == "__main__":
    asyncio.run(main())
