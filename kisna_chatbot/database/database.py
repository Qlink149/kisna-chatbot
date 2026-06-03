"""
Primary MongoDB connection for the Kisna multi-client chatbot.

Uses MONGO_URI and MONGO_DB_NAME from environment (see utils.env_load).
"""

from pymongo import MongoClient

from kisna_chatbot.utils.env_load import mongo_db_name, mongo_uri

client = MongoClient(mongo_uri)
db = client[mongo_db_name]


def ping_database() -> None:
    """Verify MongoDB connectivity (used on startup)."""
    from kisna_chatbot.utils.logger_config import log_event

    client.admin.command("ping")
    log_event("database_ping", "MongoDB ping ok", db_name=mongo_db_name)


def _log_database_init() -> None:
    from kisna_chatbot.utils.logger_config import log_event

    log_event("database_init", "MongoDB client initialized", db_name=mongo_db_name)


_log_database_init()
