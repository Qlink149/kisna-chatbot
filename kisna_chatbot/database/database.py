"""
Primary MongoDB connection for the Kisna multi-client chatbot.

Uses MONGO_URI and MONGO_DB_NAME from environment (see utils.env_load).
"""

from pymongo import MongoClient

from kisna_chatbot.utils.env_load import mongo_db_name, mongo_uri

client = MongoClient(mongo_uri)
db = client[mongo_db_name]
