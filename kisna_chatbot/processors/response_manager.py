from kisna_chatbot.whatsapp_functions.cta.send_cta import send_cta_url
from kisna_chatbot.whatsapp_functions.flow.send_site_visit import (
    send_site_visit_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_damage_complaint import (
    send_damage_complaint_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_store_locator import (
    send_store_locator_flow,
)
from kisna_chatbot.whatsapp_functions.flow.send_store_visit_datetime import (
    send_store_visit_datetime_flow,
)
from kisna_chatbot.whatsapp_functions.list.send_service_list import (
    send_service_list,
)
from kisna_chatbot.whatsapp_functions.media.send_audio_message import (
    send_audio_message,
)
from kisna_chatbot.whatsapp_functions.media.send_document_message import (
    send_file_message,
)
from kisna_chatbot.whatsapp_functions.media.send_image_message import (
    send_image_message,
)
from kisna_chatbot.whatsapp_functions.quick_reply.send_quick_reply import (
    send_quickreply,
)
from kisna_chatbot.whatsapp_functions.list.send_list import send_list
from kisna_chatbot.whatsapp_functions.send_text_message import (
    send_text_message_with_retry,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.utils.rate_limiter import outbound_rate_limiter
import time


class ResponseManager:
    """Singleton class to manage and send bot responses based on their type."""

    _instance = None

    def __new__(cls):
        """Ensures that only a single instance of the ResponseManager exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._handlers = {}
            cls._instance._register_default_handlers()
        return cls._instance

    def _register_default_handlers(self):
        """Registers default handlers for known response types.

        New types can be added dynamically using the `register_handler` method.
        """
        self.register_handler("text", self._handle_text)
        self.register_handler("media", self._handle_media)
        self.register_handler("flow", self._handle_flow)
        self.register_handler("list", self._handle_list)
        self.register_handler("quickreply", self._handle_quick_reply)
        self.register_handler("skip", self._handle_skip)
        self.register_handler("cta_url", self._handle_url)

    def register_handler(self, response_type, handler):
        """Registers a handler for a specific response type.

        This allows adding new response types without modifying existing code.

        :param response_type: The type of response to handle (e.g., "text", "flow").
        :param handler: The function that handles this response type.
        """
        self._handlers[response_type] = handler

    def handle_responses(self, data):
        """Iterate through the list of bot responses and routes to its appropriate handler."""
        bot_responses = data.get("bot_response", [])
        phone_number = data["phone_number"]
        for response in bot_responses:
            outbound_rate_limiter.wait_if_needed(phone_number)
            response_type = response.get("type")
            handler = self._handlers.get(response_type)

            if handler:
                result = handler(phone_number=phone_number, bot_response=response)
                if result:
                    if result.get("status") != "submitted":
                        logger.warning(f"Message not confirmed: {result}")
                    else:
                        logger.info("message submitted")
                        time.sleep(0.4)
            else:
                raise ValueError(
                    f"No handler registered for response type: {response_type}"
                )

    def _handle_text(self, phone_number, bot_response):
        """Processes text responses (e.g., sending cta urls).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return send_text_message_with_retry(
            phone_number=phone_number, bot_response=bot_response
        )

    def _handle_quick_reply(self, phone_number, bot_response):
        """Processes quick reply.

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return send_quickreply(phone_number=phone_number, bot_response=bot_response)

    def _handle_skip(self, phone_number, bot_response):
        """Processes text responses (e.g., sending cta urls).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return {"status": "submitted"}

    def _handle_url(self, phone_number, bot_response):
        """Processes text responses (e.g., sending cta urls).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        return send_cta_url(phone_number=phone_number, bot_response=bot_response)

    def _handle_list(self, phone_number, bot_response):
        """Processes list responses (e.g., sending lists).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        list_name = bot_response["list"]
        if list_name == "service_list":
            return send_service_list(phone_number=phone_number)
        elif list_name == "list":
            return send_list(phone_number=phone_number, bot_response=bot_response)
        else:
            raise ValueError(f"Unknown list: {list_name}")

    def _handle_flow(self, phone_number, bot_response):
        """Processes flow responses (e.g., sending registration flow).

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        flow_name = bot_response["flow"]

        if flow_name == "site_visit":
            return send_site_visit_flow(phone_number=phone_number)
        elif flow_name == "damage_complaint":
            return send_damage_complaint_flow(phone_number=phone_number)
        elif flow_name == "store_locator":
            return send_store_locator_flow(phone_number=phone_number, name=bot_response.get("name", "there"))
        elif flow_name == "store_visit_datetime":
            return send_store_visit_datetime_flow(phone_number=phone_number, bot_response=bot_response)
        else:
            raise ValueError(f"Unknown flow: {flow_name}")

    def _handle_media(self, phone_number, bot_response):
        """Processes media response.

        : phone_number: Contains the phone number of the user
        : bot_response: A dictionary containing the response details.
        """
        media_type = bot_response["media_type"]
        if media_type == "image":
            return send_image_message(
                phone_number=phone_number, bot_response=bot_response
            )
        elif media_type == "doc":
            return send_file_message(
                phone_number=phone_number, bot_response=bot_response
            )
        elif media_type == "audio":
            return send_audio_message(
                phone_number=phone_number, bot_response=bot_response
            )
        else:
            raise ValueError(f"Unknown media type: {media_type}")
