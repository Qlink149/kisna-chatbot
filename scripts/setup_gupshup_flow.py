#!/usr/bin/env python3
"""
Create, upload JSON, and publish a Gupshup WhatsApp Flow for Kisna.

Reads .env from kisna-chatbot/ (project root).

Required:
  GUPSHUP_APP_ID

App token (same as scripts/setup_gupshup_webhook.py):
  GUPSHUP_PARTNER_APP_TOKEN | GUPSHUP_TOKEN | partner login + GET /token

Optional:
  GUPSHUP_FLOW_NAME          (default: kisna_damage_complaint)
  GUPSHUP_FLOW_CATEGORIES    (default: OTHER) — comma-separated
  GUPSHUP_FLOW_JSON_PATH     (default: json/damage_complaint.json)

Usage:
  python scripts/setup_gupshup_flow.py
  python scripts/setup_gupshup_flow.py --list
  python scripts/setup_gupshup_flow.py --flow-id FLOW_ID --upload-only
  python scripts/setup_gupshup_flow.py --flow-id FLOW_ID --publish-only
  python scripts/setup_gupshup_flow.py --dry-run
  python scripts/setup_gupshup_flow.py --resume
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

import requests
from dotenv import load_dotenv
from requests.exceptions import ConnectionError, RequestException, Timeout

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

PARTNER_BASE_URL = "https://partner.gupshup.io"
STATE_FILE = ROOT_DIR / ".gupshup_flow_state.json"
DEFAULT_RETRIES = 4
RETRY_BACKOFF_SEC = 3.0


def require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def parse_json_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise SystemExit(
            f"Unexpected non-JSON from {response.request.method} {response.url}: "
            f"HTTP {response.status_code} {response.text[:500]}"
        ) from exc


def ensure_ok(response: requests.Response, context: str) -> Any:
    data = parse_json_response(response)
    if response.status_code >= 400:
        message = data.get("message") if isinstance(data, dict) else None
        if not message:
            message = (
                data.get("status") if isinstance(data, dict) else response.text[:500]
            )
        raise SystemExit(f"{context} failed: HTTP {response.status_code} - {message}")
    return data


def get_partner_token() -> str:
    explicit = (os.environ.get("GUPSHUP_PARTNER_TOKEN") or "").strip()
    if explicit:
        return explicit

    email = (os.environ.get("GUPSHUP_PARTNER_EMAIL") or "").strip()
    password = (
        os.environ.get("GUPSHUP_PARTNER_CLIENT_SECRET")
        or os.environ.get("GUPSHUP_PARTNER_PASSWORD")
        or ""
    ).strip()
    if not email or not password:
        raise SystemExit(
            "Missing partner auth. Set GUPSHUP_PARTNER_TOKEN, or "
            "GUPSHUP_PARTNER_EMAIL + GUPSHUP_PARTNER_CLIENT_SECRET "
            "(or GUPSHUP_PARTNER_PASSWORD)."
        )

    response = requests.post(
        f"{PARTNER_BASE_URL}/partner/account/login",
        data={"email": email, "password": password},
        timeout=30,
    )
    data = ensure_ok(response, "Partner login")
    token = (data.get("token") or "").strip()
    if not token:
        raise SystemExit("Partner login succeeded but no token returned.")
    return token


def get_app_token(app_id: str) -> str:
    for key in ("GUPSHUP_PARTNER_APP_TOKEN", "GUPSHUP_TOKEN"):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value

    partner_token = get_partner_token()
    response = requests.get(
        f"{PARTNER_BASE_URL}/partner/app/{app_id}/token",
        headers={"token": partner_token},
        timeout=30,
    )
    data = ensure_ok(response, "Fetch app token")
    token_data = data.get("token") or {}
    app_token = token_data.get("token") if isinstance(token_data, dict) else str(token_data)
    app_token = (app_token or "").strip()
    if not app_token:
        raise SystemExit("App token request succeeded but no app token returned.")
    return app_token


def auth_headers(app_token: str) -> dict[str, str]:
    return {"Authorization": app_token}


def request_with_retries(
    label: str,
    request_fn: Callable[[], requests.Response],
    *,
    retries: int = DEFAULT_RETRIES,
) -> requests.Response:
    """Retry transient network failures (common on Windows during large uploads)."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = request_fn()
            return response
        except (ConnectionError, Timeout, RequestException) as exc:
            last_error = exc
            if attempt >= retries:
                break
            wait = RETRY_BACKOFF_SEC * attempt
            print(
                f"{label}: network error ({exc!r}), retry {attempt}/{retries - 1} "
                f"in {wait:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(wait)
    raise SystemExit(
        f"{label} failed after {retries} attempts: {last_error!r}\n"
        "Check VPN/firewall/antivirus, then resume with --resume or --flow-id."
    ) from last_error


def save_flow_state(
    app_id: str, flow_id: str, flow_name: str, *, step: str
) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "appId": app_id,
                "flowId": flow_id,
                "flowName": flow_name,
                "lastStep": step,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_flow_state() -> dict[str, Any] | None:
    if not STATE_FILE.is_file():
        return None
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def clear_flow_state() -> None:
    if STATE_FILE.is_file():
        STATE_FILE.unlink()


def find_flow_by_name(
    flows: list[dict[str, Any]], flow_name: str
) -> dict[str, Any] | None:
    for flow in flows:
        if flow.get("name") == flow_name:
            return flow
    return None


def find_draft_flow_id(
    flows: list[dict[str, Any]], flow_name: str
) -> str | None:
    flow = find_flow_by_name(flows, flow_name)
    if not flow:
        return None
    if str(flow.get("status", "")).upper() in {"DRAFT", "PENDING"}:
        flow_id = str(flow.get("id") or "").strip()
        return flow_id or None
    return None


def list_flows(app_id: str, app_token: str) -> list[dict[str, Any]]:
    response = request_with_retries(
        "List flows",
        lambda: requests.get(
            f"{PARTNER_BASE_URL}/partner/app/{app_id}/flows",
            headers=auth_headers(app_token),
            timeout=60,
        ),
    )
    data = ensure_ok(response, "List flows")
    if not isinstance(data, list):
        raise SystemExit("Unexpected list flows response (expected JSON array).")
    return data


def create_flow(
    app_id: str, app_token: str, name: str, categories: list[str]
) -> str:
    response = request_with_retries(
        "Create flow",
        lambda: requests.post(
            f"{PARTNER_BASE_URL}/partner/app/{app_id}/flows",
            headers={**auth_headers(app_token), "Content-Type": "application/json"},
            json={"name": name, "categories": categories},
            timeout=60,
        ),
    )
    data = ensure_ok(response, "Create flow")
    flow_id = str(data.get("id") or "").strip()
    if not flow_id:
        raise SystemExit(f"Create flow succeeded but no id in response: {data}")
    return flow_id


def upload_flow_json(
    app_id: str, app_token: str, flow_id: str, json_path: Path
) -> dict[str, Any]:
    if not json_path.is_file():
        raise SystemExit(f"Flow JSON not found: {json_path}")

    file_bytes = json_path.read_bytes()
    url = f"{PARTNER_BASE_URL}/partner/app/{app_id}/flows/{flow_id}/assets"

    def do_upload() -> requests.Response:
        return requests.put(
            url,
            headers=auth_headers(app_token),
            files={"file": (json_path.name, file_bytes, "application/json")},
            timeout=180,
        )

    response = request_with_retries("Upload flow JSON", do_upload, retries=5)
    data = ensure_ok(response, "Upload flow JSON")
    errors = data.get("validation_errors") if isinstance(data, dict) else None
    if errors:
        print(json.dumps({"validation_errors": errors}, indent=2), file=sys.stderr)
    return data if isinstance(data, dict) else {"raw": data}


def publish_flow(app_id: str, app_token: str, flow_id: str) -> dict[str, Any]:
    response = request_with_retries(
        "Publish flow",
        lambda: requests.post(
            f"{PARTNER_BASE_URL}/partner/app/{app_id}/flows/{flow_id}/publish",
            headers=auth_headers(app_token),
            timeout=60,
        ),
    )
    data = ensure_ok(response, "Publish flow")
    return data if isinstance(data, dict) else {"raw": data}


def resolve_json_path() -> Path:
    raw = (
        os.environ.get("GUPSHUP_FLOW_JSON_PATH") or "json/damage_complaint.json"
    ).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def parse_categories() -> list[str]:
    raw = (os.environ.get("GUPSHUP_FLOW_CATEGORIES") or "OTHER").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def planned_steps(args: argparse.Namespace, flow_id: str) -> list[str]:
    if args.publish_only:
        return ["publish"]
    if args.upload_only:
        return ["upload_json"]
    steps: list[str] = []
    if not flow_id:
        steps.append("create_flow")
    steps.extend(["upload_json", "publish"])
    return steps


def print_resume_hint(flow_id: str) -> None:
    print(
        json.dumps(
            {
                "status": "incomplete",
                "flowId": flow_id,
                "resume": [
                    f"python scripts/setup_gupshup_flow.py --flow-id {flow_id} --upload-only",
                    f"python scripts/setup_gupshup_flow.py --flow-id {flow_id} --publish-only",
                    "python scripts/setup_gupshup_flow.py --resume",
                ],
            },
            indent=2,
        ),
        file=sys.stderr,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gupshup Flow setup for Kisna")
    parser.add_argument("--list", action="store_true", help="List flows for app")
    parser.add_argument("--flow-id", help="Existing flow id (upload/publish only)")
    parser.add_argument("--upload-only", action="store_true")
    parser.add_argument("--publish-only", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Upload + publish using .gupshup_flow_state.json or draft by name",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned steps only")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    app_id = require_env("GUPSHUP_APP_ID")

    if args.upload_only and args.publish_only:
        raise SystemExit("Use only one of --upload-only or --publish-only.")

    if args.dry_run:
        flow_id = (args.flow_id or "").strip()
        print(
            json.dumps(
                {
                    "appId": app_id,
                    "flowName": (
                        os.environ.get("GUPSHUP_FLOW_NAME") or "kisna_damage_complaint"
                    ).strip(),
                    "categories": parse_categories(),
                    "jsonPath": str(resolve_json_path()),
                    "flowId": flow_id or "(will create)",
                    "steps": planned_steps(args, flow_id),
                },
                indent=2,
            )
        )
        return

    app_token = get_app_token(app_id)

    if args.list:
        flows = list_flows(app_id, app_token)
        print(json.dumps(flows, indent=2))
        return

    flow_name = (os.environ.get("GUPSHUP_FLOW_NAME") or "kisna_damage_complaint").strip()
    categories = parse_categories()
    json_path = resolve_json_path()
    flow_id = (args.flow_id or "").strip()

    if args.publish_only:
        if not flow_id:
            raise SystemExit("--flow-id is required for --publish-only")
        publish_flow(app_id, app_token, flow_id)
        print(json.dumps({"status": "published", "flowId": flow_id}, indent=2))
        return

    if args.upload_only:
        if not flow_id:
            raise SystemExit("--flow-id is required for --upload-only")
        try:
            upload_flow_json(app_id, app_token, flow_id, json_path)
        except SystemExit:
            save_flow_state(app_id, flow_id, flow_name, step="upload_failed")
            print_resume_hint(flow_id)
            raise
        save_flow_state(app_id, flow_id, flow_name, step="uploaded")
        print(json.dumps({"status": "uploaded", "flowId": flow_id}, indent=2))
        return

    if args.resume:
        state = load_flow_state()
        if not flow_id and state:
            flow_id = str(state.get("flowId") or "").strip()
        if not flow_id:
            flows = list_flows(app_id, app_token)
            existing = find_flow_by_name(flows, flow_name)
            if existing and str(existing.get("status", "")).upper() == "PUBLISHED":
                published_id = str(existing.get("id") or "").strip()
                print(
                    json.dumps(
                        {
                            "status": "already_published",
                            "flowId": published_id,
                            "flowName": flow_name,
                            "message": "Nothing to resume — flow is already published.",
                            "nextSteps": [
                                f"KISNA_DAMAGE_COMPLAINT_FLOW_ID={published_id}",
                                "Add to Vercel, redeploy, test Raise a Complaint",
                            ],
                        },
                        indent=2,
                    )
                )
                return
            flow_id = find_draft_flow_id(flows, flow_name) or ""
        if not flow_id:
            raise SystemExit(
                "No draft flow to resume. Run --list to see status, or pass --flow-id. "
                "If already published, set KISNA_DAMAGE_COMPLAINT_FLOW_ID from --list."
            )
        print(f"Resuming flow {flow_id} (upload + publish)...", file=sys.stderr)
        try:
            upload_flow_json(app_id, app_token, flow_id, json_path)
            publish_flow(app_id, app_token, flow_id)
        except SystemExit:
            save_flow_state(app_id, flow_id, flow_name, step="resume_failed")
            print_resume_hint(flow_id)
            raise
        clear_flow_state()
        print(
            json.dumps(
                {
                    "status": "success",
                    "flowId": flow_id,
                    "flowName": flow_name,
                    "nextSteps": [
                        f"KISNA_DAMAGE_COMPLAINT_FLOW_ID={flow_id}",
                    ],
                },
                indent=2,
            )
        )
        return

    flow_id = ""
    try:
        flow_id = create_flow(app_id, app_token, flow_name, categories)
        save_flow_state(app_id, flow_id, flow_name, step="created")
        print(f"Created flow {flow_id}, uploading JSON...", file=sys.stderr)
        upload_flow_json(app_id, app_token, flow_id, json_path)
        save_flow_state(app_id, flow_id, flow_name, step="uploaded")
        print(f"Publishing flow {flow_id}...", file=sys.stderr)
        publish_flow(app_id, app_token, flow_id)
    except SystemExit:
        if flow_id:
            save_flow_state(app_id, flow_id, flow_name, step="failed")
            print_resume_hint(flow_id)
        raise
    except KeyboardInterrupt:
        if flow_id:
            save_flow_state(app_id, flow_id, flow_name, step="interrupted")
            print_resume_hint(flow_id)
        raise SystemExit("Interrupted.") from None

    clear_flow_state()
    print(
        json.dumps(
            {
                "status": "success",
                "flowId": flow_id,
                "flowName": flow_name,
                "nextSteps": [
                    f"Add to .env and Vercel: KISNA_DAMAGE_COMPLAINT_FLOW_ID={flow_id}",
                    "Redeploy and test menu: Raise a Complaint",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
