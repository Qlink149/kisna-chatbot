"""The Mongo ``stores`` collection: indexes, upserts and the CSV import."""

from __future__ import annotations

import csv
import io
import time
from typing import Any, Iterable

from pymongo import ASCENDING, UpdateOne

from kisna_chatbot.database.collections import stores as _stores
from kisna_chatbot.stores import cache
from kisna_chatbot.stores.model import STORE_FIELDS, from_csv_row, to_csv_row
from kisna_chatbot.utils.logger_config import logger

# A CSV bigger than this is almost certainly the wrong file.
MAX_CSV_ROWS = 5000


def ensure_indexes(collection=None) -> None:
    col = collection if collection is not None else _stores
    col.create_index([("store_id", ASCENDING)], unique=True, name="uniq_store_id")
    col.create_index([("state", ASCENDING)], name="stores_state")
    col.create_index([("state", ASCENDING), ("city", ASCENDING)], name="stores_state_city")


def upsert_many(stores: Iterable[dict], *, collection=None) -> dict[str, int]:
    """Upsert on store_id. Returns counts; busts the read cache."""
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


def parse_csv(content: bytes | str) -> tuple[list[dict], list[dict]]:
    """Parse and validate a whole file. Returns (stores, errors); ``errors`` is
    a list of {"row": n, "error": "..."} with n the 1-based line number
    (header = line 1). Nothing is written here."""
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return [], [{"row": 0, "error": "file is not UTF-8 text"}]
    else:
        text = content.lstrip("﻿")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [f for f in ("store_id", "name", "city", "state") if f not in header]
    if missing:
        return [], [{"row": 1, "error": f"missing column(s): {', '.join(missing)}"}]

    stores: list[dict] = []
    errors: list[dict] = []
    seen: dict[str, int] = {}
    for line_no, row in enumerate(reader, start=2):
        if line_no - 1 > MAX_CSV_ROWS:
            errors.append({"row": line_no, "error": f"more than {MAX_CSV_ROWS} rows"})
            break
        if not any((v or "").strip() for v in row.values() if isinstance(v, str)):
            continue  # blank line
        try:
            store = from_csv_row(row)
        except ValueError as e:
            errors.append({"row": line_no, "error": str(e)})
            continue
        if store["store_id"] in seen:
            errors.append(
                {
                    "row": line_no,
                    "error": f"store_id {store['store_id']!r} repeats line {seen[store['store_id']]}",
                }
            )
            continue
        seen[store["store_id"]] = line_no
        stores.append(store)
    if not stores and not errors:
        errors.append({"row": 1, "error": "file has no store rows"})
    return stores, errors


def import_csv(content: bytes | str, *, collection=None) -> dict[str, Any]:
    """All-or-nothing: any row error rejects the whole file, nothing written."""
    stores, errors = parse_csv(content)
    if errors:
        return {"ok": False, "errors": errors, "rows": len(stores) + len(errors)}
    counts = upsert_many(stores, collection=collection)
    logger.info("Stores CSV imported", extra={"rows": len(stores), **counts})
    return {"ok": True, "errors": [], "rows": len(stores), **counts}


def list_all(*, collection=None) -> list[dict]:
    col = collection if collection is not None else _stores
    return list(
        col.find({}, {"_id": 0}).sort([("state", ASCENDING), ("city", ASCENDING), ("name", ASCENDING)])
    )


def set_flags(store_id: str, *, bookable: bool | None = None, active: bool | None = None, collection=None) -> dict | None:
    col = collection if collection is not None else _stores
    update: dict[str, Any] = {"updated_at": int(time.time())}
    if bookable is not None:
        update["bookable"] = bool(bookable)
    if active is not None:
        update["active"] = bool(active)
    doc = col.find_one_and_update(
        {"store_id": store_id},
        {"$set": update},
        projection={"_id": 0},
        return_document=True,
    )
    cache.bust()
    return doc


def to_csv(stores: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(STORE_FIELDS))
    writer.writeheader()
    for s in stores:
        writer.writerow(to_csv_row(s))
    return buf.getvalue()
