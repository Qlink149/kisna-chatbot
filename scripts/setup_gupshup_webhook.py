#!/usr/bin/env python3
"""
Register or update the Gupshup Partner webhook subscription for Kisna.

Reads configuration from .env in the project root (kisna-chatbot/.env).

Required:
  GUPSHUP_APP_ID
  GUPSHUP_TOKEN
  WEBHOOK_URL   e.g. https://your-app.vercel.app/gupshup/message/kisna

Optional:
  GUPSHUP_WEBHOOK_TAG=kisna-chatbot
  GUPSHUP_WEBHOOK_VERSION=3
  GUPSHUP_WEBHOOK_MODES=MESSAGE
  GUPSHUP_WEBHOOK_SHOW_ON_UI=true

Usage (from kisna-chatbot/):
  python scripts/setup_gupshup_webhook.py
  python scripts/setup_gupshup_webhook.py --list
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

PARTNER_BASE_URL = "https://partner.gupshup.io"
DEFAULT_MODES = "MESSAGE"


def require_env(name: str) -> str:
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def get_app_token(app_id: str) -> str:
    """Fetch short-lived app token using partner GUPSHUP_TOKEN."""
    partner_token = require_env("GUPSHUP_TOKEN")
    response = requests.get(
        f"{PARTNER_BASE_URL}/partner/app/{app_id}/token",
        headers={
            "Authorization": partner_token,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise SystemExit(
            f"Failed to get app token ({response.status_code}): {response.text}"
        )
    data = response.json()
    token = data.get("token") or data.get("access_token") or ""
    if not token:
        raise SystemExit(f"App token response had no token field: {data}")
    return str(token)


def ensure_ok(response: requests.Response, action: str) -> dict:
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text}
    if response.status_code not in (200, 201):
        raise SystemExit(
            f"{action} failed ({response.status_code}): "
            f"{json.dumps(data, indent=2) if isinstance(data, dict) else data}"
        )
    return data if isinstance(data, dict) else {"raw": data}


def _parse_subscriptions_payload(data: dict | list) -> list[dict]:
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    subscriptions = data.get("subscription") or data.get("subscriptions") or data
    if isinstance(subscriptions, list):
        return subscriptions
    if isinstance(subscriptions, dict):
        return [subscriptions]
    return []


def get_existing_subscriptions(app_id: str, app_token: str) -> list[dict]:
    for auth in (app_token, os.environ.get("GUPSHUP_TOKEN", "").strip()):
        if not auth:
            continue
        response = requests.get(
            f"{PARTNER_BASE_URL}/partner/app/{app_id}/subscription",
            headers={"Authorization": auth, "accept": "application/json"},
            timeout=30,
        )
        if response.status_code == 200:
            try:
                return _parse_subscriptions_payload(response.json())
            except ValueError:
                return []
    return []


def upsert_subscription(app_id: str, app_token: str, webhook_url: str) -> dict:
    tag = (os.environ.get("GUPSHUP_WEBHOOK_TAG") or "kisna-chatbot").strip()
    version = (os.environ.get("GUPSHUP_WEBHOOK_VERSION") or "3").strip()
    modes = (os.environ.get("GUPSHUP_WEBHOOK_MODES") or DEFAULT_MODES).strip()
    show_on_ui = (os.environ.get("GUPSHUP_WEBHOOK_SHOW_ON_UI") or "true").strip().lower()

    payload = {
        "url": webhook_url,
        "tag": tag,
        "version": version,
        "modes": modes,
        "showOnUI": "true" if show_on_ui in {"1", "true", "yes"} else "false",
        "active": "true",
        "doCheck": "false",
    }

    subscriptions = get_existing_subscriptions(app_id, app_token)
    existing = next(
        (
            subscription
            for subscription in subscriptions
            if subscription.get("tag") == tag or subscription.get("url") == webhook_url
        ),
        None,
    )

    headers = {
        "Authorization": app_token,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    if existing:
        subscription_id = str(existing.get("id") or "").strip()
        if not subscription_id:
            raise SystemExit("Found matching subscription but it has no subscription id.")
        response = requests.put(
            f"{PARTNER_BASE_URL}/partner/app/{app_id}/subscription/{subscription_id}",
            headers=headers,
            data=payload,
            timeout=30,
        )
        data = ensure_ok(response, "Update subscription")
        return {"action": "updated", "subscription": data.get("subscription") or {}}

    response = requests.post(
        f"{PARTNER_BASE_URL}/partner/app/{app_id}/subscription",
        headers=headers,
        data=payload,
        timeout=30,
    )
    data = ensure_ok(response, "Create subscription")
    return {"action": "created", "subscription": data.get("subscription") or {}}


def main() -> None:
    app_id = require_env("GUPSHUP_APP_ID")

    if "--list" in sys.argv:
        app_token = get_app_token(app_id)
        subs = get_existing_subscriptions(app_id, app_token)
        if not subs:
            print(json.dumps({"subscriptions": [], "note": "none or list API failed"}, indent=2))
        else:
            print(json.dumps({"subscriptions": subs}, indent=2))
        return

    webhook_url = require_env("WEBHOOK_URL")
    app_token = get_app_token(app_id)
    result = upsert_subscription(app_id, app_token, webhook_url)
    subscription = result["subscription"]
    print(
        json.dumps(
            {
                "status": "success",
                "action": result["action"],
                "appId": app_id,
                "subscriptionId": subscription.get("id"),
                "url": subscription.get("url") or webhook_url,
                "tag": subscription.get("tag"),
                "version": subscription.get("version"),
                "modes": subscription.get("modes"),
                "active": subscription.get("active"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
