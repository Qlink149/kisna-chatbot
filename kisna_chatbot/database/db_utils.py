import time
from datetime import datetime

from pymongo import ReturnDocument

from kisna_chatbot.database.collections import complaints, ratings, store_visits, users
from kisna_chatbot.utils.format_chathistory import format_chat_history
from kisna_chatbot.utils.logger_config import logger


def _user_filter(phone_number: str, client_id: str) -> dict:
    return {"phone_number": phone_number, "client_id": client_id}


def save_to_mongo(data: dict) -> dict | None:
    """Save user profile and append chat history."""
    phone_number = data["phone_number"]
    client_id = data.get("client_id", "kisna")
    try:
        logger.info(
            "Request received to save user profile",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        messages = data["messages"]
        assistant = data.get("bot_response")
        user_profile_data = data["user_profile"]

        new_chat = format_chat_history(
            user=messages, assistant=assistant, phone_number=phone_number
        )
        current_history = user_profile_data.get("chat_history", [])
        user_profile_data["chat_history"] = current_history + new_chat
        user_profile_data["updated_at"] = int(time.time())
        user_profile_data["last_message_at"] = int(time.time())
        user_profile_data["client_id"] = client_id
        if data.get("whatsapp_username"):
            user_profile_data["username"] = data["whatsapp_username"]

        response = users.find_one_and_update(
            _user_filter(phone_number, client_id),
            {"$set": user_profile_data},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        logger.info(
            "User profile saved successfully",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        if response:
            response.pop("_id", None)
        return response
    except Exception as e:
        logger.exception(
            "MongoDB save failed",
            extra={"exception": e, "phone_number": phone_number},
        )
        raise


def save_user_message_silent(
    phone_number: str, text: str, client_id: str = "kisna"
) -> None:
    """Append user message to chat_history without bot response (human takeover)."""
    try:
        now = int(time.time())
        users.update_one(
            _user_filter(phone_number, client_id),
            {
                "$push": {
                    "chat_history": {
                        "role": "user",
                        "content": text,
                        "timestamp": now,
                    }
                },
                "$set": {"updated_at": now},
            },
            upsert=True,
        )
        logger.info(
            "Silent user message saved",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to save silent message",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def touch_last_message_at(phone_number: str, client_id: str = "kisna") -> None:
    """Update last inbound message timestamp without a full profile save."""
    try:
        now = int(time.time())
        users.update_one(
            _user_filter(phone_number, client_id),
            {"$set": {"last_message_at": now, "updated_at": now}},
            upsert=True,
        )
    except Exception as e:
        logger.exception(
            "Failed to touch last_message_at",
            extra={"phone_number": phone_number, "client_id": client_id, "error": str(e)},
        )
        raise


def get_takeover_status(phone_number: str, client_id: str = "kisna") -> dict | None:
    """Fetch human_takeover subdocument for a user."""
    try:
        doc = users.find_one(
            _user_filter(phone_number, client_id),
            {"human_takeover": 1, "_id": 0},
        )
        return doc.get("human_takeover") if doc else None
    except Exception as e:
        logger.exception(
            "Failed to get takeover status",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def set_takeover(phone_number: str, active: bool, client_id: str = "kisna") -> None:
    """Set human takeover and live-agent flags on the user profile."""
    try:
        now = int(time.time())
        takeover = {
            "active": active,
            "taken_by": "agent" if active else None,
            "taken_at": now if active else None,
        }
        update_fields: dict = {
            "human_takeover": takeover,
            "live_agent_required": active,
        }
        if active:
            update_fields["live_agent_requested_at"] = now
        else:
            update_fields["live_agent_resolved_at"] = now

        users.update_one(
            _user_filter(phone_number, client_id),
            {"$set": update_fields},
            upsert=True,
        )
        logger.info(
            "Takeover status updated",
            extra={
                "phone_number": phone_number,
                "client_id": client_id,
                "active": active,
                "logged_at": datetime.utcnow().isoformat(),
            },
        )
    except Exception as e:
        logger.exception(
            "Failed to set takeover",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def save_complaint(
    phone_number: str,
    issue: str,
    complaint_type: str,
    case_id: str,
    client_id: str = "kisna",
    order_id: str = "",
    customer_name: str = "",
) -> None:
    """Insert a complaint record into the complaints collection."""
    try:
        doc = {
            "client_id": client_id,
            "phone_number": phone_number,
            "order_id": order_id,
            "issue": issue,
            "type": complaint_type,
            "case_id": case_id,
            "customer_name": customer_name,
            "created_at": int(time.time()),
            "status": "registered" if case_id else "crm_pending",
        }
        complaints.insert_one(doc)
        logger.info(
            "Complaint saved",
            extra={
                "phone_number": phone_number,
                "client_id": client_id,
                "case_id": case_id,
            },
        )
    except Exception as e:
        logger.exception(
            "Failed to save complaint",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def get_user_by_phone(phone_number: str, client_id: str = "kisna") -> dict | None:
    """Return full user profile for phone_number and client_id, or None."""
    try:
        user = users.find_one(_user_filter(phone_number, client_id), {"_id": 0})
        if not user:
            logger.info(
                "User not found",
                extra={"phone_number": phone_number, "client_id": client_id},
            )
            return None
        logger.info(
            "Fetched user by phone",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        return user
    except Exception as e:
        logger.exception(
            "Failed to fetch user by phone",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def get_all_users(
    page: int = 1,
    limit: int = 20,
    client_id: str = "kisna",
    agent_requested: bool | None = None,
) -> dict:
    """Paginated user list for a client, sorted by updated_at descending."""
    try:
        query: dict = {"client_id": client_id}
        if agent_requested:
            query["live_agent_required"] = True
        skip = (page - 1) * limit
        projection = {
            "phone_number": 1,
            "username": 1,
            "updated_at": 1,
            "live_agent_required": 1,
            "_id": 0,
        }
        cursor = (
            users.find(query, projection)
            .sort("updated_at", -1)
            .skip(skip)
            .limit(limit)
        )
        results = list(cursor)
        total = users.count_documents(query)
        logger.info(
            "Fetched users list",
            extra={
                "page": page,
                "limit": limit,
                "total": total,
                "client_id": client_id,
            },
        )
        return {"total": total, "page": page, "limit": limit, "results": results}
    except Exception as e:
        logger.exception(
            "Failed to fetch users list",
            extra={"client_id": client_id, "page": page},
        )
        raise


def search_users(q: str, client_id: str = "kisna", limit: int = 20) -> list:
    """Search users by phone_number or username (partial, case-insensitive)."""
    try:
        pattern = {"$regex": q, "$options": "i"}
        query = {
            "client_id": client_id,
            "$or": [{"phone_number": pattern}, {"username": pattern}],
        }
        projection = {
            "phone_number": 1,
            "username": 1,
            "updated_at": 1,
            "live_agent_required": 1,
            "_id": 0,
        }
        results = list(
            users.find(query, projection).sort("updated_at", -1).limit(limit)
        )
        logger.info(
            "User search executed",
            extra={"q": q, "client_id": client_id, "hits": len(results)},
        )
        return results
    except Exception as e:
        logger.exception(
            "Failed to search users",
            extra={"q": q, "client_id": client_id},
        )
        raise


def save_store_visit(
    phone_number: str,
    visit_date: str,
    visit_time: str,
    store_name: str,
    client_id: str = "kisna",
) -> None:
    """Save a store visit booking to the store_visits collection."""
    try:
        doc = {
            "client_id": client_id,
            "phone_number": phone_number,
            "visit_date": visit_date,
            "visit_time": visit_time,
            "store_name": store_name,
            "created_at": int(time.time()),
        }
        store_visits.insert_one(doc)
        logger.info(
            "Store visit saved",
            extra={
                "phone_number": phone_number,
                "client_id": client_id,
                "visit_date": visit_date,
                "visit_time": visit_time,
                "store_name": store_name,
            },
        )
    except Exception as e:
        logger.exception(
            "Failed to save store visit",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def request_live_agent(phone_number: str, client_id: str = "kisna") -> None:
    """Flag a user's conversation for live agent intervention."""
    try:
        users.update_one(
            _user_filter(phone_number, client_id),
            {
                "$set": {
                    "live_agent_required": True,
                    "live_agent_requested_at": int(time.time()),
                }
            },
        )
        logger.info(
            "Live agent requested",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to request live agent",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def save_response_time(
    phone_number: str, response_time_ms: int, client_id: str = "kisna"
) -> None:
    """Accumulate AI response time stats per user."""
    try:
        users.update_one(
            _user_filter(phone_number, client_id),
            {
                "$inc": {
                    "stats.total_response_time_ms": response_time_ms,
                    "stats.response_count": 1,
                }
            },
            upsert=True,
        )
        logger.info(
            "Response time saved",
            extra={
                "phone_number": phone_number,
                "client_id": client_id,
                "ms": response_time_ms,
            },
        )
    except Exception as e:
        logger.exception(
            "Failed to save response time",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def resolve_live_agent(phone_number: str, client_id: str = "kisna") -> None:
    """Mark a live agent request as resolved."""
    try:
        users.update_one(
            _user_filter(phone_number, client_id),
            {
                "$set": {
                    "live_agent_required": False,
                    "live_agent_resolved_at": int(time.time()),
                }
            },
        )
        logger.info(
            "Live agent request resolved",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to resolve live agent request",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def save_agent_message(
    phone_number: str, message: str, client_id: str = "kisna"
) -> None:
    """Append an agent message to chat_history."""
    try:
        now = int(time.time())
        users.update_one(
            _user_filter(phone_number, client_id),
            {
                "$push": {
                    "chat_history": {
                        "role": "assistant",
                        "content": message,
                        "timestamp": now,
                    }
                },
                "$set": {"updated_at": now},
            },
        )
        logger.info(
            "Agent message saved",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
    except Exception as e:
        logger.exception(
            "Failed to save agent message",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


def get_all_complaints(
    page: int = 1, limit: int = 20, client_id: str = "kisna"
) -> dict:
    """Paginated complaints for a client, sorted by created_at descending."""
    try:
        query = {"client_id": client_id}
        skip = (page - 1) * limit
        cursor = (
            complaints.find(query, {"_id": 0})
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )
        results = list(cursor)
        total = complaints.count_documents(query)
        logger.info(
            "Fetched complaints list",
            extra={"page": page, "limit": limit, "total": total, "client_id": client_id},
        )
        return {"total": total, "page": page, "limit": limit, "complaints": results}
    except Exception as e:
        logger.exception(
            "Failed to fetch complaints list",
            extra={"client_id": client_id},
        )
        raise


def get_complaints_by_phone(phone_number: str, client_id: str = "kisna") -> list:
    """All complaints for a phone number and client."""
    try:
        results = list(
            complaints.find(
                {"phone_number": phone_number, "client_id": client_id},
                {"_id": 0},
            ).sort("created_at", -1)
        )
        logger.info(
            "Fetched complaints by phone",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        return results
    except Exception as e:
        logger.exception(
            "Failed to fetch complaints by phone",
            extra={"phone_number": phone_number, "client_id": client_id},
        )
        raise


RATING_SCORES = {"😊 Excellent": 3, "😐 Average": 2, "😞 Poor": 1}
SCORE_LABELS = {3: "Excellent", 2: "Average", 1: "Poor"}

_PERIOD_FORMATS = {
    "year": "%Y",
    "month": "%Y-%m",
    "week": "%G-W%V",
}


def _growth_pipeline(field: str, period: str, match: dict | None = None) -> list:
    """Aggregation pipeline: group a Unix-timestamp field by period."""
    date_format = _PERIOD_FORMATS.get(period, "%Y-%m")
    stages: list = []
    if match:
        stages.append({"$match": match})
    stages.extend(
        [
            {"$match": {field: {"$exists": True, "$type": "number"}}},
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": date_format,
                            "date": {"$toDate": {"$multiply": [f"${field}", 1000]}},
                        }
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
            {"$project": {"_id": 0, "period": "$_id", "count": 1}},
        ]
    )
    return stages


def get_rating_stats(client_id: str | None = None) -> dict:
    """Return rating breakdown and average score."""
    try:
        match = {"client_id": client_id} if client_id else {}
        pipeline = [{"$group": {"_id": "$label", "count": {"$sum": 1}}}]
        if match:
            pipeline.insert(0, {"$match": match})
        breakdown_raw = list(ratings.aggregate(pipeline))
        breakdown = {row["_id"]: row["count"] for row in breakdown_raw}

        avg_pipeline = [{"$group": {"_id": None, "avg_score": {"$avg": "$score"}, "total": {"$sum": 1}}}]
        if match:
            avg_pipeline.insert(0, {"$match": match})
        avg_result = list(ratings.aggregate(avg_pipeline))
        if avg_result:
            raw_avg = avg_result[0]["avg_score"]
            avg_label = SCORE_LABELS.get(round(raw_avg)) if raw_avg is not None else None
            total = avg_result[0]["total"]
        else:
            avg_label = None
            total = 0

        return {
            "total_ratings": total,
            "avg_score": avg_label,
            "breakdown": {
                "excellent": breakdown.get("😊 Excellent", 0),
                "average": breakdown.get("😐 Average", 0),
                "poor": breakdown.get("😞 Poor", 0),
            },
        }
    except Exception as e:
        logger.exception("Failed to get rating stats", extra={"client_id": client_id})
        raise


def get_user_growth(period: str = "month", client_id: str = "kisna") -> list:
    """New-user counts grouped by period using created_at."""
    try:
        result = list(
            users.aggregate(
                _growth_pipeline("created_at", period, {"client_id": client_id})
            )
        )
        logger.info(
            "User growth fetched",
            extra={"period": period, "client_id": client_id, "buckets": len(result)},
        )
        return result
    except Exception as e:
        logger.exception(
            "Failed to get user growth",
            extra={"period": period, "client_id": client_id},
        )
        raise


def get_store_visit_growth(period: str = "month", client_id: str = "kisna") -> list:
    """Store visit counts grouped by period."""
    try:
        result = list(
            store_visits.aggregate(
                _growth_pipeline("created_at", period, {"client_id": client_id})
            )
        )
        logger.info(
            "Store visit growth fetched",
            extra={"period": period, "client_id": client_id, "buckets": len(result)},
        )
        return result
    except Exception as e:
        logger.exception(
            "Failed to get store visit growth",
            extra={"period": period, "client_id": client_id},
        )
        raise


def get_dashboard_stats(client_id: str = "kisna") -> dict:
    """Aggregate dashboard stats for a client."""
    try:
        match = {"client_id": client_id}
        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "total_users": {"$sum": 1},
                    "total_messages": {
                        "$sum": {"$size": {"$ifNull": ["$chat_history", []]}}
                    },
                    "avg_messages_per_user": {
                        "$avg": {"$size": {"$ifNull": ["$chat_history", []]}}
                    },
                    "total_response_time_ms": {"$sum": "$stats.total_response_time_ms"},
                    "total_response_count": {"$sum": "$stats.response_count"},
                }
            },
        ]
        result = list(users.aggregate(pipeline))

        if result:
            row = result[0]
            total_users = row["total_users"]
            total_messages = row["total_messages"]
            avg_messages = round(row["avg_messages_per_user"], 2)
            count = row["total_response_count"]
            avg_ms = round(row["total_response_time_ms"] / count, 2) if count else None
        else:
            total_users = 0
            total_messages = 0
            avg_messages = 0.0
            avg_ms = None

        total_store_visits = store_visits.count_documents(match)
        total_complaints_count = complaints.count_documents(match)
        rating_stats = get_rating_stats(client_id=client_id)

        return {
            "total_users": total_users,
            "total_messages": total_messages,
            "avg_messages_per_user": avg_messages,
            "avg_ai_response_time_ms": avg_ms,
            "total_store_visits": total_store_visits,
            "total_complaints": total_complaints_count,
            "ratings": rating_stats,
        }
    except Exception as e:
        logger.exception(
            "Failed to get dashboard stats",
            extra={"client_id": client_id},
        )
        raise
