from kisna_chatbot.constants import GUPSHUP_SOURCE, GUPSHUP_URL
from kisna_chatbot.utils.env_load import gupshup_api_key, gupshup_app_name
from kisna_chatbot.utils.logger_config import logger
import json
import httpx

def send_quickreply(phone_number, bot_response):
    """Send quick reply to the user."""
    logger.info(
        "Sending postcall quick reply to phone number",
        extra={"phone_number": phone_number},
    )

    destination = f"{phone_number}"
    url = GUPSHUP_URL

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "apikey": gupshup_api_key,
    }

    data = {
        "message": json.dumps(
            {
                "type": "quick_reply",
                "content": {
                    "type": "text",
                    "text": bot_response["text"],
                    "caption": bot_response["caption"],
                },
                # "options": [
                #     {"title": bot_response["option"]}
                # ],
                "options": bot_response["options"],
                "msgid": bot_response["msgid"],
            }
        ),
        "source": GUPSHUP_SOURCE,
        "destination": destination,
        "src.name": gupshup_app_name,
    }

    try:
        response = httpx.post(url, headers=headers, data=data)
        logger.info(
            "Response",
            extra={
                "phone_number": phone_number,
                "response": response.json(),
            },
        )
        return response.json()
    except Exception as e:
        logger.error(
            "Error while sending postcall quick reply",
            extra={"phone_number": phone_number, "error": e},
        )
        raise e
