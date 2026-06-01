"""
Migration 001: Add client_id field and multi-tenant indexes.

Backfills client_id='kisna' on documents missing the field and creates
a compound index on (client_id, phone_number) for each collection.
"""

from pymongo.collection import Collection
from pymongo.errors import OperationFailure

from kisna_chatbot.database.collections import (
    complaints,
    ratings,
    store_visits,
    users,
)
from kisna_chatbot.utils.env_load import mongo_uri
from kisna_chatbot.utils.logger_config import logger

DEFAULT_CLIENT_ID = "kisna"
INDEX_NAME = "client_id_phone_number"

MISSING_CLIENT_ID_FILTER = {
    "$or": [
        {"client_id": {"$exists": False}},
        {"client_id": None},
    ]
}


def _migrate_collection(collection: Collection, collection_name: str) -> None:
    """Backfill client_id and create compound index for one collection."""
    try:
        update_result = collection.update_many(
            MISSING_CLIENT_ID_FILTER,
            {"$set": {"client_id": DEFAULT_CLIENT_ID}},
        )
        index_name = collection.create_index(
            [("client_id", 1), ("phone_number", 1)],
            unique=False,
            name=INDEX_NAME,
        )
        status = (
            f"{collection_name}: matched={update_result.matched_count}, "
            f"modified={update_result.modified_count}, index={index_name}"
        )
        print(status)
        logger.info(
            "Migration 001 collection updated",
            extra={
                "collection": collection_name,
                "matched_count": update_result.matched_count,
                "modified_count": update_result.modified_count,
                "index": index_name,
            },
        )
    except OperationFailure as e:
        if e.code == 85 or "already exists" in str(e).lower():
            update_result = collection.update_many(
                MISSING_CLIENT_ID_FILTER,
                {"$set": {"client_id": DEFAULT_CLIENT_ID}},
            )
            status = (
                f"{collection_name}: matched={update_result.matched_count}, "
                f"modified={update_result.modified_count}, index={INDEX_NAME} (exists)"
            )
            print(status)
            logger.info(
                "Migration 001 collection updated (index already exists)",
                extra={
                    "collection": collection_name,
                    "matched_count": update_result.matched_count,
                    "modified_count": update_result.modified_count,
                    "index": INDEX_NAME,
                },
            )
            return
        logger.exception(
            "Migration 001 failed for collection",
            extra={"collection": collection_name, "error": str(e)},
        )
        print(f"{collection_name}: ERROR - {e}")
        raise
    except Exception as e:
        logger.exception(
            "Migration 001 failed for collection",
            extra={"collection": collection_name, "error": str(e)},
        )
        print(f"{collection_name}: ERROR - {e}")
        raise


def migrate() -> None:
    """Run migration 001 on all collections."""
    if not mongo_uri:
        raise RuntimeError("MONGO_URI is not set")

    collections = [
        (users, "users"),
        (complaints, "complaints"),
        (store_visits, "store_visits"),
        (ratings, "ratings"),
    ]

    for collection, collection_name in collections:
        _migrate_collection(collection, collection_name)


if __name__ == "__main__":
    try:
        migrate()
        print("Migration 001_add_client_id completed successfully.")
    except Exception as e:
        logger.exception(
            "Migration 001_add_client_id failed",
            extra={"error": str(e)},
        )
        raise
