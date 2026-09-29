from kisna_chatbot.database.database import db

# All collections include client_id field for multi-tenancy

users = db["users"]
complaints = db["complaints"]
callback_requests = db["callback_requests"]
store_visits = db["store_visits"]
# Bookable stores for the Store Visit Flow (kisna_chatbot/stores).
stores = db["stores"]
# One row per kisna.com store sync run (kisna_chatbot/stores/sync.py).
store_sync_runs = db["store_sync_runs"]
ratings = db["ratings"]
ai_usage_logs = db["ai_usage_logs"]
processed_inbound_messages = db["processed_inbound_messages"]
chat_messages = db["chat_messages"]
message_traces = db["message_traces"]
# Outbox for the real-time event push to the Clara backend (-> Salesforce).
clara_events = db["clara_events"]

# Dashboard login — not client-scoped, shared across all clients.
admin_users = db["admin_users"]
admin_sessions = db["admin_sessions"]

COLLECTIONS = (
    users,
    complaints,
    callback_requests,
    store_visits,
    stores,
    store_sync_runs,
    ratings,
    ai_usage_logs,
    processed_inbound_messages,
    chat_messages,
    message_traces,
    clara_events,
    admin_users,
    admin_sessions,
)
