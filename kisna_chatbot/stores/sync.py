"""Nightly store sync from the kisna.com store API, with dashboard overrides.

Field ownership (enforced here, in the CSV import and in the dashboard API):
- SYNCED_FIELDS come from kisna.com and are overwritten on every run, and so
  is presence: a store missing from the API is deactivated (never deleted --
  bookings reference it), and reactivated if it comes back.
- OVERRIDE_FIELDS belong to the dashboard and are never written by a sync of
  an existing store. A NEW store gets them once, from the same normalisation
  as the seed (hours from kisna.com, bookable from
  KISNA_NEW_STORE_BOOKABLE_DEFAULT). The kisna.com hours are kept for
  reference only: visit slots use the client's default until the dashboard
  sets hours (stores.model.effective_hours).

Safety: nothing is written unless the fetch succeeded, the response parsed,
and it holds at least MIN_ACTIVE_RATIO of the currently active stores. Every
run -- ok, aborted or failed -- is recorded in `store_sync_runs`.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timedelta
from typing import Any, Callable

import httpx
from pymongo import UpdateOne

from kisna_chatbot.stores import cache
from kisna_chatbot.stores.model import OVERRIDE_FIELDS, SYNCED_FIELDS, from_kisna_record  # noqa: F401
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.support_hours import IST

DEFAULT_URL = "https://kisna-web-backend-6v55l.ondigitalocean.app/prod/admin/allStores"
PAGE_SIZE = 1000
MIN_ACTIVE_RATIO = 0.8
CATCH_UP_AFTER = timedelta(hours=26)
RUN_AT_IST = (2, 0)  # 02:00 IST
_CHANGE_LIST_CAP = 50

_lock = asyncio.Lock()


class SyncAbort(Exception):
    """A run that must not write anything."""


def sync_url() -> str:
    return (os.getenv("KISNA_STORE_SYNC_URL") or DEFAULT_URL).strip()


def new_store_bookable_default() -> bool:
    return os.getenv("KISNA_NEW_STORE_BOOKABLE_DEFAULT", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _collections():
    from kisna_chatbot.database.collections import store_sync_runs, stores

    return stores, store_sync_runs


# ----------------------------------------------------------------- fetch
async def fetch_raw() -> list[dict]:
    """GET the store list; raises SyncAbort on any transport / shape problem."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                sync_url(),
                params={"pageNo": 1, "pageSize": PAGE_SIZE},
                headers={"User-Agent": "KisnaChatbot-StoreSync/1.0", "Origin": "https://www.kisna.com"},
            )
    except httpx.HTTPError as e:
        raise SyncAbort(f"fetch failed: {type(e).__name__}: {e}") from e
    if resp.status_code != 200:
        raise SyncAbort(f"fetch failed: HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise SyncAbort("response is not JSON") from e
    return parse_response(body)


def parse_response(body: Any) -> list[dict]:
    """The API's {"data": {"data": [...], "totalCount": n}} shape, checked."""
    try:
        data = body["data"]
        rows = data["data"]
        total = int(data.get("totalCount", len(rows)))
    except (KeyError, TypeError, ValueError) as e:
        raise SyncAbort("response shape is not {data: {data: [...], totalCount}}") from e
    if not isinstance(rows, list):
        raise SyncAbort("response data.data is not a list")
    if len(rows) < total:
        raise SyncAbort(f"response is paged: got {len(rows)} of {total}")
    return rows


def normalise(rows: list[dict]) -> list[dict]:
    """Same normalisation as the seed. Records without an id are skipped;
    a duplicate id keeps the first."""
    out: dict[str, dict] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        store = from_kisna_record(raw)
        if not store["store_id"] or not store["name"]:
            continue
        if not raw.get("active", True) or str(raw.get("status", "active")).lower() != "active":
            continue  # kisna.com lists it as closed -> treated as absent
        out.setdefault(store["store_id"], store)
    return list(out.values())


# ------------------------------------------------------------------ plan
def plan(fetched: list[dict], existing: list[dict], *, bookable_default: bool, now: int) -> dict:
    """Pure diff: what the sync would write. No I/O."""
    by_id = {s["store_id"]: s for s in existing}
    seen: set[str] = set()
    ops: list[UpdateOne] = []
    changes: dict[str, list[str]] = {"added": [], "updated": [], "deactivated": [], "reactivated": []}

    for s in fetched:
        sid = s["store_id"]
        seen.add(sid)
        synced = {f: s.get(f, "") for f in SYNCED_FIELDS}
        old = by_id.get(sid)
        if old is None:
            doc = {
                "store_id": sid,
                **synced,
                "open_time": s["open_time"],
                "close_time": s["close_time"],
                "weekly_off": s["weekly_off"],
                "bookable": bookable_default,
                "active": True,
                "source": "kisna.com",
                "created_at": now,
                "updated_at": now,
                "synced_at": now,
            }
            ops.append(UpdateOne({"store_id": sid}, {"$setOnInsert": doc}, upsert=True))
            changes["added"].append(sid)
            continue
        diff = {f: v for f, v in synced.items() if old.get(f) != v}
        was_inactive = not old.get("active", False)
        update: dict[str, Any] = {"synced_at": now, **diff}
        if was_inactive:
            update["active"] = True
            changes["reactivated"].append(sid)
        if diff:
            update["updated_at"] = now
            changes["updated"].append(sid)
        ops.append(UpdateOne({"store_id": sid}, {"$set": update}))

    for sid, old in by_id.items():
        if sid not in seen and old.get("active", False):
            ops.append(
                UpdateOne({"store_id": sid}, {"$set": {"active": False, "updated_at": now, "deactivated_at": now}})
            )
            changes["deactivated"].append(sid)
    return {"ops": ops, "changes": changes}


# ------------------------------------------------------------------- run
async def run_sync(
    *,
    trigger: str,
    fetch: Callable[[], Any] | None = None,
    now: int | None = None,
) -> dict:
    """One sync run. Returns the recorded run document (without _id)."""
    stores, runs = _collections()
    started = int(now if now is not None else time.time())
    run: dict[str, Any] = {
        "started_at": started,
        "trigger": trigger,
        "source": sync_url(),
        "status": "running",
    }
    async with _lock:
        try:
            rows = await (fetch or fetch_raw)()
            fetched = normalise(rows)
            existing = list(stores.find({}, {"_id": 0}))
            active_now = sum(1 for s in existing if s.get("active"))
            if active_now and len(fetched) < MIN_ACTIVE_RATIO * active_now:
                raise SyncAbort(
                    f"only {len(fetched)} stores in the response vs {active_now} active "
                    f"(< {int(MIN_ACTIVE_RATIO * 100)}%)"
                )
            if not fetched:
                raise SyncAbort("response has no stores")
            result = plan(fetched, existing, bookable_default=new_store_bookable_default(), now=started)
            if result["ops"]:
                stores.bulk_write(result["ops"], ordered=False)
            cache.bust()
            changes = result["changes"]
            run.update(
                status="ok",
                fetched=len(fetched),
                active_before=active_now,
                counts={k: len(v) for k, v in changes.items()},
                changes={k: v[:_CHANGE_LIST_CAP] for k, v in changes.items()},
            )
            logger.info("Store sync ok", extra={"trigger": trigger, **run["counts"]})
        except SyncAbort as e:
            run.update(status="aborted", reason=str(e))
            logger.error("Store sync aborted; nothing written", extra={"trigger": trigger, "reason": str(e)})
        except Exception as e:  # noqa: BLE001 -- recorded, never raised into the loop
            run.update(status="failed", reason=f"{type(e).__name__}: {e}")
            logger.exception("Store sync failed", extra={"trigger": trigger})
        run["finished_at"] = int(time.time())
        try:
            runs.insert_one(dict(run))
        except Exception:
            logger.exception("Could not record the store sync run")
    return run


def last_run(status: str | None = None) -> dict | None:
    _, runs = _collections()
    query = {"status": status} if status else {}
    return runs.find_one(query, {"_id": 0}, sort=[("started_at", -1)])


def catch_up_due(now: float | None = None) -> bool:
    """True when the last SUCCESSFUL sync is older than 26 h (or never ran)."""
    last = last_run("ok")
    if not last:
        return True
    current = now if now is not None else time.time()
    return current - float(last.get("started_at", 0)) > CATCH_UP_AFTER.total_seconds()


def seconds_until_next_run(now: datetime | None = None) -> float:
    current = (now or datetime.now(IST)).astimezone(IST)
    target = current.replace(hour=RUN_AT_IST[0], minute=RUN_AT_IST[1], second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return (target - current).total_seconds()


async def sync_loop() -> None:
    """Runs forever inside the app lifespan: catch up at startup if the last
    good sync is > 26 h old, then every day at 02:00 IST."""
    try:
        if catch_up_due():
            await run_sync(trigger="startup_catch_up")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Store sync catch-up check failed")
    while True:
        await asyncio.sleep(seconds_until_next_run())
        try:
            await run_sync(trigger="nightly")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Nightly store sync failed")
