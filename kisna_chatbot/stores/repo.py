"""The Mongo ``stores`` collection: indexes, the seed upsert, the dashboard's
override edits and CSV import, and the CSV download.

Stores themselves come from the kisna.com sync (stores/sync.py). The
dashboard edits only OVERRIDE_FIELDS; the CSV import enforces the same rule.
"""

from __future__ import annotations

import csv
import io
import time
from typing import Any, Iterable

from pymongo import ASCENDING, UpdateOne

from kisna_chatbot.database.collections import stores as _stores
from kisna_chatbot.stores import cache
from kisna_chatbot.stores.model import (
    OVERRIDE_FIELDS,
    STORE_FIELDS,
    clean_text,
    synced_field_conflicts,
    to_csv_row,
    validate_overrides,
)
from kisna_chatbot.utils.logger_config import logger

# A CSV bigger than this is almost certainly the wrong file.
MAX_CSV_ROWS = 5000

CSV_REQUIRED_COLUMNS = ("store_id",)


def ensure_indexes(collection=None) -> None:
    col = collection if collection is not None else _stores
    col.create_index([("store_id", ASCENDING)], unique=True, name="uniq_store_id")
    col.create_index([("state", ASCENDING)], name="stores_state")
    col.create_index([("state", ASCENDING), ("city", ASCENDING)], name="stores_state_city")


def upsert_many(stores: Iterable[dict], *, collection=None) -> dict[str, int]:
    """Seed-script upsert on store_id (local / dev only). Busts the cache."""
    col = collection if collection is not None else _stores
    ops = []
    for s in stores:
        doc = {k: v for k, v in s.items() if k != "_id"}
        created_at = doc.pop("created_at", None) or int(time.time())
        ops.append(
            UpdateOne(
                {"store_id": doc["store_id"]},
                {"$set": doc, "$setOnInsert": {"created_at": created_at}},
                upsert=True,
            )
        )
    if not ops:
        return {"inserted": 0, "updated": 0}
    result = col.bulk_write(ops, ordered=False)
    cache.bust()
    return {"inserted": result.upserted_count, "updated": result.modified_count}


def _decode(content: bytes | str) -> str | None:
    if isinstance(content, bytes):
        try:
            return content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
    return content.lstrip("﻿")


def parse_csv(content: bytes | str, current_by_id: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Validate a whole overrides file against the stored stores.

    Returns (updates, errors). ``updates`` is [{"store_id", <override fields>}];
    ``errors`` is [{"row": n, "error": "..."}] with n the 1-based line number
    (header = line 1). Nothing is written here."""
    text = _decode(content)
    if text is None:
        return [], [{"row": 0, "error": "file is not UTF-8 text"}]
    reader = csv.DictReader(io.StringIO(text))
    header = [clean_text(h).lower() for h in (reader.fieldnames or [])]
    if "store_id" not in header:
        return [], [{"row": 1, "error": "missing column: store_id"}]
    override_cols = [f for f in OVERRIDE_FIELDS if f in header]
    if not override_cols:
        return [], [{"row": 1, "error": f"no override column ({', '.join(OVERRIDE_FIELDS)})"}]
    known = set(STORE_FIELDS) | {"store_id"}
    unknown = [h for h in header if h and h not in known]
    if unknown:
        return [], [{"row": 1, "error": f"unknown column(s): {', '.join(unknown)}"}]

    updates: list[dict] = []
    errors: list[dict] = []
    seen: dict[str, int] = {}
    for line_no, raw in enumerate(reader, start=2):
        if line_no - 1 > MAX_CSV_ROWS:
            errors.append({"row": line_no, "error": f"more than {MAX_CSV_ROWS} rows"})
            break
        row = {clean_text(k).lower(): v for k, v in raw.items() if k is not None}
        if not any(clean_text(v) for v in row.values() if isinstance(v, str)):
            continue  # blank line
        store_id = clean_text(row.get("store_id"))
        if not store_id:
            errors.append({"row": line_no, "error": "store_id is required"})
            continue
        if store_id in seen:
            errors.append({"row": line_no, "error": f"store_id {store_id!r} repeats line {seen[store_id]}"})
            continue
        seen[store_id] = line_no
        current = current_by_id.get(store_id)
        if current is None:
            errors.append(
                {"row": line_no, "error": f"store_id {store_id!r} not found (stores are added by the kisna.com sync)"}
            )
            continue
        problems = synced_field_conflicts(row, current)
        update, override_errors = validate_overrides({f: row.get(f) for f in override_cols}, current)
        problems += override_errors
        if problems:
            errors.append({"row": line_no, "error": "; ".join(problems)})
            continue
        updates.append({"store_id": store_id, **update})
    if not updates and not errors:
        errors.append({"row": 1, "error": "file has no store rows"})
    return updates, errors


def import_csv(content: bytes | str, *, collection=None) -> dict[str, Any]:
    """All-or-nothing overrides import: any row error rejects the whole file."""
    col = collection if collection is not None else _stores
    current = {s["store_id"]: s for s in col.find({}, {"_id": 0})}
    updates, errors = parse_csv(content, current)
    if errors:
        return {"ok": False, "errors": errors, "rows": len(updates) + len(errors)}
    now = int(time.time())
    ops = []
    changed = 0
    for u in updates:
        sid = u.pop("store_id")
        diff = {k: v for k, v in u.items() if current[sid].get(k) != v}
        if diff:
            changed += 1
            ops.append(UpdateOne({"store_id": sid}, {"$set": {**diff, "overrides_updated_at": now}}))
    if ops:
        col.bulk_write(ops, ordered=False)
    cache.bust()
    logger.info("Store overrides CSV imported", extra={"rows": len(updates), "changed": changed})
    return {"ok": True, "errors": [], "rows": len(updates), "updated": changed, "inserted": 0}


def list_all(*, collection=None) -> list[dict]:
    col = collection if collection is not None else _stores
    return list(
        col.find({}, {"_id": 0}).sort([("state", ASCENDING), ("city", ASCENDING), ("name", ASCENDING)])
    )


def set_overrides(store_id: str, values: dict, *, by: str = "", collection=None) -> tuple[dict | None, list[str]]:
    """Dashboard edit of OVERRIDE_FIELDS only. Returns (doc, errors)."""
    col = collection if collection is not None else _stores
    current = col.find_one({"store_id": store_id}, {"_id": 0})
    if current is None:
        return None, []
    update, errors = validate_overrides(values, current)
    if errors:
        return current, errors
    if update:
        update.update(overrides_updated_at=int(time.time()), overrides_updated_by=by)
        current = col.find_one_and_update(
            {"store_id": store_id},
            {"$set": update},
            projection={"_id": 0},
            return_document=True,
        )
        cache.bust()
    return current, []


def to_csv(stores: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(STORE_FIELDS))
    writer.writeheader()
    for s in stores:
        writer.writerow(to_csv_row(s))
    return buf.getvalue()
