"""
Live smoke test for the Clara event push (chatbot -> client backend -> Salesforce).

Generates the three event payloads by running the REAL agents against real
Gupshup-shaped `nfm_reply` submissions -- the exact code path a WhatsApp user
triggers -- then POSTs each one to the configured events endpoint.

Side effects are deliberately fenced off so this is safe to run against a live
environment:

  * MongoDB writes are mocked      (no rows in complaints / callback_requests)
  * admin WhatsApp alerts mocked   (no messages to the ADMINS list)
  * VTiger case creation mocked    (no CRM tickets)
  * the outbox is bypassed         (each payload is POSTed exactly once, here)

Usage:
    python scripts/smoke_clara_events.py                # dry run, prints payloads
    python scripts/smoke_clara_events.py --send         # actually POST
    python scripts/smoke_clara_events.py --send --replay-idempotency
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("KISNA_CLARA_EVENTS_ENABLED", "true")

from kisna_chatbot.integrations import clara_events as ce  # noqa: E402
from kisna_chatbot.models.enums import FLowId  # noqa: E402
from kisna_chatbot.processors.callback_agent import CallbackAgent  # noqa: E402
from kisna_chatbot.processors.complaint_agent import ComplaintAgent  # noqa: E402
from kisna_chatbot.utils.support_slots import (  # noqa: E402
    clear_capacity_overrides,
    set_capacity_overrides,
)

_IST = timezone(timedelta(hours=5, minutes=30))

# Their own curl examples used this number/name, so it is already a recognisable
# test identity on the receiving side.
TEST_NUMBER = "919812345678"
TEST_NAME = "Clara Test User"

_ENQUEUE_CB = "kisna_chatbot.processors.callback_agent.enqueue_clara_event"
_ENQUEUE_CMP = "kisna_chatbot.processors.complaint_agent.enqueue_clara_event"


def _nfm(payload: dict) -> dict:
    """A Gupshup interactive nfm_reply, exactly as it arrives from WhatsApp."""
    return {
        "interactive": {
            "type": "nfm_reply",
            "nfm_reply": {
                "name": "flow",
                "body": "Sent",
                "response_json": json.dumps(payload),
            },
        }
    }


def _base_data(messages: dict) -> dict:
    return {
        "phone_number": TEST_NUMBER,
        "client_id": "kisna",
        "client_config": MagicMock(client_id="kisna"),
        "whatsapp_username": TEST_NAME,
        "user_profile": {"username": TEST_NAME, "service_selected": "callback"},
        "messages": messages,
    }


def _next_working_day() -> str:
    """First non-Sunday at least one day out, in IST."""
    day = datetime.now(_IST).date() + timedelta(days=1)
    while day.weekday() == 6:  # Sunday: closed
        day += timedelta(days=1)
    return day.isoformat()


async def _capture_complaint() -> dict:
    """Run the real ComplaintAgent and capture the event it would enqueue."""
    with patch(_ENQUEUE_CMP, new_callable=AsyncMock) as enqueue, patch(
        "kisna_chatbot.processors.complaint_agent.complaints"
    ) as coll, patch(
        "kisna_chatbot.processors.complaint_agent.CRMAdapter"
    ) as crm_cls:
        crm = MagicMock()
        crm.create_case = AsyncMock(return_value={})
        crm.aclose = AsyncMock()
        crm_cls.return_value = crm
        coll.insert_one = MagicMock()

        data = _base_data(
            _nfm(
                {
                    "flow_token": FLowId.DAMAGE_COMPLAINT.value,
                    "order_id": "ORD-SMOKE-001",
                    "complaint_type": "4_Returns_Related",
                    "issue_description": (
                        "TEST EVENT from Clara chatbot integration smoke test - "
                        "please ignore. Ring arrived damaged; stone is loose."
                    ),
                }
            )
        )
        data["user_profile"] = {"username": TEST_NAME}
        await ComplaintAgent().process(data)

        assert enqueue.await_count == 1, "complaint agent did not enqueue an event"
        return enqueue.await_args[0][0]


async def _capture_support(request_type: str) -> dict:
    """Run the real CallbackAgent and capture the event it would enqueue."""
    flow_token = (
        os.getenv("KISNA_VIDEOCALL_FLOW_ID")
        if request_type == "video_call"
        else os.getenv("KISNA_CALLBACK_FLOW_ID")
    )
    submission = {
        "flow_token": flow_token,
        "request_type": request_type,
        "preferred_date": _next_working_day(),
        "preferred_time": "10-13",
    }
    if request_type == "callback":
        # A customer who typed a different number to be called on.
        submission["mobile"] = "9876543210"
        submission["reason"] = "product_enquiry"
    else:
        # A customer who skipped the field: falls back to their WhatsApp number.
        submission["mobile"] = ""

    with patch(_ENQUEUE_CB, new_callable=AsyncMock) as enqueue, patch(
        "kisna_chatbot.processors.callback_agent.callback_requests"
    ) as coll, patch(
        "kisna_chatbot.processors.callback_agent.send_customer_support_template"
    ):
        coll.insert_one = MagicMock()
        data = _base_data(_nfm(submission))
        result = await CallbackAgent().process(data)

        assert enqueue.await_count == 1, (
            f"{request_type} agent did not enqueue an event; "
            f"bot said: {result.get('bot_response')}"
        )
        return enqueue.await_args[0][0]


async def _send(label: str, payload: dict) -> tuple[int | None, object, str | None]:
    status, body, error = await ce._post(payload)
    verdict = ce._classify(status, error)
    print(f"  status   : {status}")
    print(f"  response : {body}")
    if error:
        print(f"  error    : {error}")
    print(f"  verdict  : {verdict}")
    return status, body, error


async def main(send: bool, replay: bool) -> int:
    # Capacity lookups would otherwise hit Mongo; force an empty schedule so the
    # real slot-resolution logic still runs against a clean calendar.
    set_capacity_overrides(lambda _d: 0, lambda _d, _s: 0)
    try:
        events = [
            ("complaint_submitted", await _capture_complaint()),
            ("callback_requested", await _capture_support("callback")),
            ("video_call_requested", await _capture_support("video_call")),
        ]
    finally:
        clear_capacity_overrides()

    print("=" * 72)
    print("Endpoint :", f"{ce._base_url()}{ce._PATH}")
    print("Auth     : x-clara-api-key", "(set)" if ce._api_key() else "(MISSING)")
    print("Mode     :", "SEND" if send else "DRY RUN")
    print("=" * 72)

    results = []
    for label, payload in events:
        print(f"\n--- {label} ---")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        if send:
            results.append((label, payload, await _send(label, payload)))

    if send and replay and events:
        label, payload = events[1]  # the callback
        print(f"\n--- IDEMPOTENCY REPLAY: re-sending {payload['event_id']} ---")
        print("  (same event_id, byte-identical body)")
        await _send(label, payload)

    if send:
        print("\n" + "=" * 72)
        print("SUMMARY -- event ids to look up on the receiving side:")
        for label, payload, (status, _body, _err) in results:
            print(f"  {label:<22} {payload['event_id']:<26} HTTP {status}")
        print("=" * 72)
    else:
        print("\nDry run only. Re-run with --send to POST these.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="actually POST the events")
    ap.add_argument(
        "--replay-idempotency",
        action="store_true",
        help="re-send one event with the same event_id to test dedupe",
    )
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.send, args.replay_idempotency)))
