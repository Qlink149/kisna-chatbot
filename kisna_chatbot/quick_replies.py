"""Quick replies: saved messages an agent inserts into the dashboard composer,
edits, then sends as normal. Nothing here sends anything.

One document per reply in `quick_replies`. Deletes are soft (`active: False`),
and the unique index on (client_id, title_lower) only covers active replies, so
a deleted title can be reused. Every change appends to `history` with who made
it and which fields changed.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pymongo import ASCENDING
from pymongo.errors import DuplicateKeyError

MAX_TITLE = 40
MAX_BODY = 1024
MAX_ACTIVE = 50
DEFAULT_CLIENT_ID = "kisna"

_PUBLIC_FIELDS = ("id", "title", "body", "sort_order", "created_by", "updated_by", "created_at", "updated_at")


class QuickReplyError(Exception):
    """A request the caller must fix. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.message = message
        self.status = status


def _collection(collection=None):
    if collection is not None:
        return collection
    from kisna_chatbot.database.collections import quick_replies

    return quick_replies


def public(doc: dict) -> dict:
    return {k: doc.get(k) for k in _PUBLIC_FIELDS}


def validate(title: Any, body: Any, *, partial: bool = False) -> dict:
    """Trimmed {title, body} (only the ones given when partial) or QuickReplyError
    listing every problem."""
    errors: list[str] = []
    out: dict[str, str] = {}
    for field, value, label, limit in (("title", title, "Title", MAX_TITLE), ("body", body, "Message", MAX_BODY)):
        if partial and value is None:
            continue
        text = value.strip() if isinstance(value, str) else ""
        if not text:
            errors.append(f"{label} is required")
        elif len(text) > limit:
            errors.append(f"{label} must be {limit:,} characters or fewer (got {len(text):,})")
        else:
            out[field] = text
    if errors:
        raise QuickReplyError("; ".join(errors))
    return out


def _duplicate(title: str) -> QuickReplyError:
    return QuickReplyError(f"A quick reply titled “{title}” already exists")


def _title_taken(col, client_id: str, title: str, exclude_id: str | None = None) -> bool:
    q: dict[str, Any] = {"client_id": client_id, "title_lower": title.lower(), "active": True}
    if exclude_id:
        q["id"] = {"$ne": exclude_id}
    return col.find_one(q) is not None


def list_active(client_id: str = DEFAULT_CLIENT_ID, *, collection=None) -> list[dict]:
    col = _collection(collection)
    rows = col.find({"client_id": client_id, "active": True}).sort([("sort_order", ASCENDING), ("created_at", ASCENDING)])
    return [public(d) for d in rows]


def create(title: Any, body: Any, *, by: str, client_id: str = DEFAULT_CLIENT_ID, collection=None) -> dict:
    col = _collection(collection)
    clean = validate(title, body)
    active = col.count_documents({"client_id": client_id, "active": True})
    if active >= MAX_ACTIVE:
        raise QuickReplyError(f"You can have at most {MAX_ACTIVE} quick replies — delete one first")
    if _title_taken(col, client_id, clean["title"]):
        raise _duplicate(clean["title"])
    last = col.find_one({"client_id": client_id, "active": True}, sort=[("sort_order", -1)])
    now = int(time.time())
    doc = {
        "id": uuid.uuid4().hex,
        "client_id": client_id,
        "title": clean["title"],
        "title_lower": clean["title"].lower(),
        "body": clean["body"],
        "sort_order": (last.get("sort_order", -1) + 1) if last else 0,
        "active": True,
        "created_by": by,
        "updated_by": by,
        "created_at": now,
        "updated_at": now,
        "history": [{"action": "create", "by": by, "at": now, "fields": ["title", "body"]}],
    }
    try:
        col.insert_one(doc)
    except DuplicateKeyError:
        raise _duplicate(clean["title"])
    return public(doc)


def _get_active(col, client_id: str, reply_id: str) -> dict:
    doc = col.find_one({"client_id": client_id, "id": reply_id, "active": True})
    if doc is None:
        raise QuickReplyError("Quick reply not found", status=404)
    return doc


def update(reply_id: str, *, title: Any = None, body: Any = None, by: str,
           client_id: str = DEFAULT_CLIENT_ID, collection=None) -> dict:
    col = _collection(collection)
    current = _get_active(col, client_id, reply_id)
    if title is None and body is None:
        raise QuickReplyError("Nothing to update")
    clean = validate(title, body, partial=True)
    changed = {k: v for k, v in clean.items() if v != current.get(k)}
    if not changed:
        return public(current)
    if "title" in changed and _title_taken(col, client_id, changed["title"], exclude_id=reply_id):
        raise _duplicate(changed["title"])
    now = int(time.time())
    update_set: dict[str, Any] = {**changed, "updated_by": by, "updated_at": now}
    if "title" in changed:
        update_set["title_lower"] = changed["title"].lower()
    try:
        col.update_one(
            {"client_id": client_id, "id": reply_id},
            {"$set": update_set, "$push": {"history": {"action": "update", "by": by, "at": now, "fields": sorted(changed)}}},
        )
    except DuplicateKeyError:
        raise _duplicate(changed.get("title", current["title"]))
    return public({**current, **update_set})


def delete(reply_id: str, *, by: str, client_id: str = DEFAULT_CLIENT_ID, collection=None) -> None:
    col = _collection(collection)
    _get_active(col, client_id, reply_id)
    now = int(time.time())
    col.update_one(
        {"client_id": client_id, "id": reply_id},
        {
            "$set": {"active": False, "deleted_by": by, "deleted_at": now, "updated_by": by, "updated_at": now},
            "$push": {"history": {"action": "delete", "by": by, "at": now, "fields": []}},
        },
    )


def reorder(ids: list[str], *, by: str, client_id: str = DEFAULT_CLIENT_ID, collection=None) -> list[dict]:
    col = _collection(collection)
    current = {d["id"] for d in col.find({"client_id": client_id, "active": True}, {"id": 1})}
    if len(ids) != len(set(ids)) or set(ids) != current:
        raise QuickReplyError("The order must list every quick reply exactly once — reload and try again")
    now = int(time.time())
    for position, reply_id in enumerate(ids):
        col.update_one(
            {"client_id": client_id, "id": reply_id, "sort_order": {"$ne": position}},
            {
                "$set": {"sort_order": position, "updated_by": by, "updated_at": now},
                "$push": {"history": {"action": "reorder", "by": by, "at": now, "fields": ["sort_order"]}},
            },
        )
    return list_active(client_id, collection=col)
