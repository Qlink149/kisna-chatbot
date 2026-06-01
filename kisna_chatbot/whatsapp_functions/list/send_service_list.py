import json

import httpx

from kisna_chatbot.constants import GUPSHUP_SOURCE
from kisna_chatbot.models.enums import ListIds
from kisna_chatbot.utils.env_load import (
    gupshup_api_key,
    gupshup_app_name,
)
from kisna_chatbot.utils.logger_config import logger


def send_service_list(phone_number):
    """Send a list message to a phone number."""
    url = "https://api.gupshup.io/wa/api/v1/msg"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    messages = (
        "Hello 👋\n\n"
        "I’m Nilkamal AI, your smart sleep assistant.\n"
        "I’m here to help you explore Nilkamal Sleep products, answer your questions, and guide you to the right choice for better sleep.\n\n"
        "💳 *Save via UPI:* Pay using UPI and grab an Instant 5% Discount (up to ₹1,000 off).\n"
        "📅 *No-Cost EMI:* Split your bill with 0% interest and pocket-friendly monthly payments.\n\n"
        "You can select an option below or simply send me a message directly with whatever you need 😊"
    )

    message_json = json.dumps(
        {
            "type": "list",
            "title": "",
            "body": messages,
            "footer": "Managed by Nilkamal Sleep",
            "msgid": f"{ListIds.SERVICE_LIST_ID.value}",
            "globalButtons": [{"type": "text", "title": "Get Started"}],
            "items": [
                {
                    "title": "How can we help?",
                    "subtitle": "",
                    "options": [
                        {
                            "type": "text",
                            "title": "Explore Products",
                            "description": "Browse mattresses, pillows & sleep accessories",
                            "postbackText": "explore_products",
                        },
                        {
                            "type": "text",
                            "title": "Raise Complaint",
                            "description": "Report damage or any issue with your Nilkamal product",
                            "postbackText": "damage_complaint",
                        },
                        {
                            "type": "text",
                            "title": "Locate Store",
                            "description": "Find the nearest Nilkamal Sleep store",
                            "postbackText": "locate_store",
                        },
                    ],
                }
            ],
        }
    )

    data = {
        "source": GUPSHUP_SOURCE,
        "destination": f"{phone_number}",
        "src.name": gupshup_app_name,
        "message": message_json,
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        logger.info(
            "Response from Gupshup API for sending service list",
            extra={"response": response.json()},
        )
        return response.json()
    except Exception as e:
        logger.error("Error in sending list", extra={"error": e})
