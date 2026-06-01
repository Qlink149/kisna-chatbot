from datetime import datetime

from bson import ObjectId
from pydantic import BaseModel


class UserProfile(BaseModel):
    """User profile model."""

    name: str
    whatsapp_username: str
    age: int
    location: str
    phone_number: str
    email_id: str
    chat_history: list
    service_selected: str
    created_at: datetime
    updated_at: datetime
    client_id: str
    pre_orders: list
    shown_product_ids: list

    class Config:
        json_encoders = {ObjectId: str}
