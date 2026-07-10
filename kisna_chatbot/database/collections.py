from kisna_chatbot.database.database import db

# All collections include client_id field for multi-tenancy

users = db["users"]
complaints = db["complaints"]
callback_requests = db["callback_requests"]
store_visits = db["store_visits"]
ratings = db["ratings"]
ai_usage_logs = db["ai_usage_logs"]
processed_inbound_messages = db["processed_inbound_messages"]

COLLECTIONS = (
    users,
    complaints,
    callback_requests,
    store_visits,
    ratings,
    ai_usage_logs,
    processed_inbound_messages,
)
