from kisna_chatbot.database.database import db

# All collections include client_id field for multi-tenancy

users = db["users"]
complaints = db["complaints"]
store_visits = db["store_visits"]
ratings = db["ratings"]
ai_usage_logs = db["ai_usage_logs"]

COLLECTIONS = (users, complaints, store_visits, ratings, ai_usage_logs)
