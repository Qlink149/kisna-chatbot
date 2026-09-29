#!/usr/bin/env python3
"""Create / update the Store Visit WhatsApp Flow as a DRAFT on Gupshup, upload
json/store_visit.json, print Meta's validation errors and a preview URL.

NEVER publishes. Publishing is manual, after sign-off:
    python scripts/setup_gupshup_flow.py --flow-id <id> --publish-only

Usage:
    python scripts/store_visit_flow_draft.py --name kisna_store_visit_draft_v1 \
        [--endpoint-uri https://<api-host>/whatsapp/flows/data-exchange]
    python scripts/store_visit_flow_draft.py --flow-id <id>        # re-upload JSON only

Gupshup's Update Flow ignores endpoint_uri, so the endpoint can only be set
when the draft is CREATED (same as the callback / video flows, .env.example).
The interactive preview calls that endpoint, so it must be running code that
knows the SV_* screens (feat/store-visit).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402

import setup_gupshup_flow as g  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FLOW_JSON = ROOT / "json" / "store_visit.json"


def create_draft(app_id: str, token: str, name: str, endpoint_uri: str | None, category: str) -> str:
    body: dict = {"name": name, "categories": [category]}
    if endpoint_uri:
        body["endpoint_uri"] = endpoint_uri
    r = g.request_with_retries(
        "Create flow",
        lambda: requests.post(
            f"{g.PARTNER_BASE_URL}/partner/app/{app_id}/flows",
            headers={**g.auth_headers(token), "Content-Type": "application/json"},
            json=body,
            timeout=60,
        ),
    )
    data = g.ensure_ok(r, "Create flow")
    flow_id = str(data.get("id") or "").strip()
    if not flow_id:
        raise SystemExit(f"Create flow returned no id: {data}")
    return flow_id


def flow_details(app_id: str, token: str, flow_id: str) -> dict:
    r = requests.get(
        f"{g.PARTNER_BASE_URL}/partner/app/{app_id}/flows/{flow_id}",
        headers=g.auth_headers(token),
        timeout=60,
    )
    return g.ensure_ok(r, "Get flow")


def interactive_preview(preview_url: str, phone: str = "919812345678") -> str:
    """Meta preview in interactive mode: the endpoint's data_exchange runs live."""
    from kisna_chatbot.processors.store_visit_flow import SCREEN_DETAILS, details_screen_data

    # Exactly what send_store_visit_flow sends as the first screen.
    payload = {"screen": SCREEN_DETAILS, "data": details_screen_data("Preview", phone)}
    params = {
        "interactive": "true",
        "flow_action": "navigate",
        "flow_token": "sv:preview:0001",
        "flow_action_payload": json.dumps(payload, separators=(",", ":")),
        "phone_number": phone,
    }
    return preview_url + "&" + urllib.parse.urlencode(params)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="kisna_store_visit_draft_v1")
    ap.add_argument("--flow-id", help="existing DRAFT to re-upload the JSON to")
    ap.add_argument("--endpoint-uri")
    # OTHER mirrors the live kisna_*_droplet flows (callback, video call).
    ap.add_argument("--category", default="OTHER")
    args = ap.parse_args()

    app_id = g.require_env("GUPSHUP_APP_ID")
    token = g.get_app_token(app_id)

    flow_id = args.flow_id
    if flow_id:
        status = str(flow_details(app_id, token, flow_id).get("status", "")).upper()
        if status != "DRAFT":
            raise SystemExit(f"Flow {flow_id} is {status}, not DRAFT -- refusing to touch it.")
    else:
        existing = g.find_flow_by_name(g.list_flows(app_id, token), args.name)
        if existing:
            raise SystemExit(f"A flow named {args.name} exists (id {existing.get('id')}). Use --flow-id or a new --name.")
        flow_id = create_draft(app_id, token, args.name, args.endpoint_uri, args.category)
        print(f"created DRAFT {args.name}: {flow_id}")

    upload = g.upload_flow_json(app_id, token, flow_id, FLOW_JSON)
    errors = upload.get("validation_errors") or []
    print(f"upload: {len(errors)} validation error(s)")
    for e in errors:
        print(" -", json.dumps(e, ensure_ascii=False))

    details = flow_details(app_id, token, flow_id)
    preview = (details.get("preview") or {}).get("preview_url")
    print("status:", details.get("status"), "| json_version:", details.get("json_version"),
          "| data_api_version:", details.get("data_api_version"))
    print("preview (static):", preview)
    if preview:
        print("preview (interactive):", interactive_preview(preview))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
