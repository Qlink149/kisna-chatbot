from pydantic import BaseModel


class Request(BaseModel):
    """Base model for all requests."""

    phone_number: str
    query: str
