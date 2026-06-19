#!/usr/bin/env python3
"""
Create (apply for) and list Gupshup WhatsApp templates for Kisna.

Reads .env from kisna-chatbot/ (project root).

Required:
  GUPSHUP_APP_ID

App token (same as scripts/setup_gupshup_webhook.py):
  GUPSHUP_PARTNER_APP_TOKEN | GUPSHUP_TOKEN | partner login + GET /token

Optional env for create (defaults match vendor_notification UTILITY example):
  GUPSHUP_TEMPLATE_ELEMENT_NAME   (default: vendor_notification)
  GUPSHUP_TEMPLATE_LANGUAGE_CODE  (default: en)
  GUPSHUP_TEMPLATE_CATEGORY       (default: UTILITY)
  GUPSHUP_TEMPLATE_TYPE           (default: TEXT)
  GUPSHUP_TEMPLATE_VERTICAL       (default: General)
  GUPSHUP_TEMPLATE_CONTENT
  GUPSHUP_TEMPLATE_EXAMPLE

Note: Meta approves templates asynchronously (minutes to 48h). This script
submits the template; use --list to poll status until APPROVED.

Usage:
  python scripts/setup_gupshup_template.py
  python scripts/setup_gupshup_template.py --list
  python scripts/setup_gupshup_template.py --list --element-name vendor_notification
  python scripts/setup_gupshup_template.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

PARTNER_BASE_URL = "https://partner.gupshup.io"

DEFAULT_CONTENT = "This is a notification for the vendor."
DEFAULT_EXAMPLE = "This is a notification for the vendor."


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


def template_headers(app_token: str) -> dict[str, str]:
    return {
        "Authorization": app_token,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def list_templates(
    app_id: str,
    app_token: str,
    *,
    element_name: str | None = None,
    status: str | None = None,
) -> Any:
    params: dict[str, str] = {"token": app_token}
    if element_name:
        params["elementName"] = element_name
    if status:
        params["status"] = status

    response = requests.get(
        f"{PARTNER_BASE_URL}/partner/app/{app_id}/templates",
        headers={"Authorization": app_token},
        params=params,
        timeout=60,
    )
    return ensure_ok(response, "List templates")


def apply_template(app_id: str, app_token: str, payload: dict[str, str]) -> Any:
    body = {**payload, "token": app_token, "enableSample": "true"}
    response = requests.post(
        f"{PARTNER_BASE_URL}/partner/app/{app_id}/templates",
        headers=template_headers(app_token),
        data=body,
        timeout=60,
    )
    return ensure_ok(response, "Apply for template")


def template_payload_from_env() -> dict[str, str]:
    return {
        "elementName": (
            os.environ.get("GUPSHUP_TEMPLATE_ELEMENT_NAME") or "vendor_notification"
        ).strip(),
        "languageCode": (
            os.environ.get("GUPSHUP_TEMPLATE_LANGUAGE_CODE") or "en"
        ).strip(),
        "category": (os.environ.get("GUPSHUP_TEMPLATE_CATEGORY") or "UTILITY").strip(),
        "templateType": (os.environ.get("GUPSHUP_TEMPLATE_TYPE") or "TEXT").strip(),
        "vertical": (os.environ.get("GUPSHUP_TEMPLATE_VERTICAL") or "General").strip(),
        "content": (os.environ.get("GUPSHUP_TEMPLATE_CONTENT") or DEFAULT_CONTENT).strip(),
        "example": (os.environ.get("GUPSHUP_TEMPLATE_EXAMPLE") or DEFAULT_EXAMPLE).strip(),
    }


def extract_template_list(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        templates = data.get("templates")
        if isinstance(templates, list):
            return [item for item in templates if isinstance(item, dict)]
    return []


def find_template_by_name(templates: Any, element_name: str) -> dict[str, Any] | None:
    for item in extract_template_list(templates):
        if item.get("elementName") == element_name:
            return item
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gupshup template setup for Kisna")
    parser.add_argument("--list", action="store_true", help="List templates for app")
    parser.add_argument("--element-name", help="Filter list by element name")
    parser.add_argument("--status", help="Filter list by status (PENDING, APPROVED, ...)")
    parser.add_argument("--dry-run", action="store_true", help="Print payload only")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    app_id = require_env("GUPSHUP_APP_ID")
    payload = template_payload_from_env()

    if args.dry_run:
        print(json.dumps({"appId": app_id, "payload": payload}, indent=2))
        return

    app_token = get_app_token(app_id)

    if args.list:
        templates = list_templates(
            app_id,
            app_token,
            element_name=(args.element_name or "").strip() or None,
            status=(args.status or "").strip() or None,
        )
        print(json.dumps(templates, indent=2))
        return

    existing = list_templates(app_id, app_token, element_name=payload["elementName"])
    match = find_template_by_name(existing, payload["elementName"])
    if match:
        status = str(match.get("status") or match.get("stage") or "unknown")
        template_id = match.get("id") or match.get("templateId")
        print(
            json.dumps(
                {
                    "status": "already_exists",
                    "elementName": payload["elementName"],
                    "approvalStatus": status,
                    "templateId": template_id,
                    "message": (
                        "Template already submitted. Meta/Gupshup approval is asynchronous; "
                        "re-run with --list --element-name to check status."
                    ),
                },
                indent=2,
            )
        )
        return

    result = apply_template(app_id, app_token, payload)
    template_id = None
    if isinstance(result, dict):
        template_id = result.get("template") or result.get("id")
        if isinstance(template_id, dict):
            template_id = template_id.get("id")

    print(
        json.dumps(
            {
                "status": "submitted",
                "elementName": payload["elementName"],
                "category": payload["category"],
                "templateId": template_id,
                "response": result,
                "nextSteps": [
                    f"python scripts/setup_gupshup_template.py --list --element-name {payload['elementName']}",
                    "Wait for APPROVED status (webhook template-event or Gupshup dashboard)",
                    f"Add to .env: {payload['elementName'].upper()}_TEMPLATE_ID=<id from --list>",
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
