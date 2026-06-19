#!/usr/bin/env python3
"""
Send vendor_notification and customer_notification templates to one or more numbers.

Reads .env from kisna-chatbot/ (project root).

Required:
  VENDOR_NOTIFICATION_TEMPLATE_ID
  CUSTOMER_NOTIFICATION_TEMPLATE_ID
  GUPSHUP_APP_ID, GUPSHUP_TOKEN, GUPSHUP_APP_NAME, GUPSHUP_SOURCE

Usage:
  python scripts/send_notification_templates.py +918696979791
  python scripts/send_notification_templates.py 919116914178 919306704311
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")

GUPSHUP_TEMPLATE_URL = "https://partner.gupshup.io/partner/app/{app_id}/template/msg"

TEMPLATES = (
    ("vendor_notification", "VENDOR_NOTIFICATION_TEMPLATE_ID"),
    ("customer_notification", "CUSTOMER_NOTIFICATION_TEMPLATE_ID"),
)


def require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def normalize_phone_number(phone_number: str) -> str:
    return phone_number.strip().replace("+", "").replace(" ", "")


def send_template(phone_number: str, template_id: str) -> dict:
    app_id = require_env("GUPSHUP_APP_ID")
    token = require_env("GUPSHUP_TOKEN")
    app_name = require_env("GUPSHUP_APP_NAME")
    source = require_env("GUPSHUP_SOURCE")
    destination = normalize_phone_number(phone_number)

    url = GUPSHUP_TEMPLATE_URL.format(app_id=app_id)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "token": token,
    }
    data = {
        "source": source,
        "destination": destination,
        "src.name": app_name,
        "template": json.dumps({"id": template_id, "params": []}),
    }

    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send vendor + customer notification templates via Gupshup"
    )
    parser.add_argument(
        "numbers",
        nargs="+",
        help="Recipient phone numbers (E.164, with or without +)",
    )
    args = parser.parse_args()

    results: list[dict] = []
    for number in args.numbers:
        for template_name, env_key in TEMPLATES:
            try:
                template_id = require_env(env_key)
                response = send_template(number, template_id)
                results.append(
                    {
                        "number": number,
                        "template": template_name,
                        "status": "sent",
                        "response": response,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "number": number,
                        "template": template_name,
                        "status": "error",
                        "error": str(exc),
                    }
                )

    print(json.dumps(results, indent=2))
    if any(item["status"] == "error" for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
