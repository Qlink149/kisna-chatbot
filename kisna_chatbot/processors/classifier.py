import json
import time
from zoneinfo import ZoneInfo

from kisna_chatbot.ai import complete_chat
from kisna_chatbot.ai.types import AgentName
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.models.service_list import ServiceList
from kisna_chatbot.processors.abstract_processor import Processor
from kisna_chatbot.processors.service_list import (
    build_complaint_flow_bot_response,
    build_greeting_welcome_bot_responses,
    is_new_session,
    is_pure_greeting,
)
from kisna_chatbot.prompts.classifier_kisna import kisna_classifier
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)

india_tz = ZoneInfo("Asia/Kolkata")

CONTEXT = kisna_classifier

_CATEGORY_TO_SERVICE = {
    "general": ServiceList.GENERAL,
    "product_search": ServiceList.PRODUCT_SEARCH,
    "offers": ServiceList.OFFERS,
    "pre_order": ServiceList.PRE_ORDER,
    "order_tracking": ServiceList.ORDER_TRACKING,
    "returns_refund": ServiceList.RETURNS_REFUND,
    "complaint": ServiceList.COMPLAINT,
}


class Classifier(Processor):
    """Classifies a query based on user intent."""

    def should_run(self, data: dict) -> bool:
        """Determine whether the processor should run based on the input data."""
        if "bot_response" in data:
            return False
        return True

    async def process(self, data: dict) -> dict:
        """Process the input data and return the processed data."""
        phone_number = data["phone_number"]
        user_profile = data["user_profile"]
        client_id = data.get("client_id", "kisna")

        if not self.should_run(data):
            logger.info(
                "Skipping processor",
                extra={
                    "processor": self.__class__.__name__,
                    "phone_number": phone_number,
                },
            )
            return data

        try:
            if "text" in data["messages"]:
                user_query = data["messages"]["text"]["body"]

                if user_query.strip().lower() == "stop":
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": "You've been successfully unsubscribed.",
                        }
                    ]
                    return data

                if user_query.lower() == "hi from ads":
                    user_profile["service_selected"] = ServiceList.AD_FLOW.value
                    return data

                chat_history = data["user_profile"].get("chat_history", [])
                if is_pure_greeting(user_query) and is_new_session(chat_history):
                    user_profile["service_selected"] = ""
                    data["classified_category"] = "greeting"
                    data["bot_response"] = build_greeting_welcome_bot_responses()
                    logger.info(
                        "Greeting on new session — welcome and main menu",
                        extra={"phone_number": phone_number},
                    )
                    return data

                logger.info(
                    "Request received to classify query",
                    extra={"phone_number": phone_number, "query": user_query},
                )

                recent_chats = chat_history[-8:]

                chat_history_str = ""
                for chat in recent_chats:
                    role = chat.get("role", "")
                    content = chat.get("content", "")
                    chat_history_str += f"{role.capitalize()}: {content}\n"

                classifier_response = await complete_chat(
                    agent=AgentName.CLASSIFIER,
                    agent_display_name="Classifier Agent",
                    instruction=CONTEXT,
                    messages=[
                        {
                            "role": "system",
                            "content": f"Chat history: {chat_history_str}",
                        },
                        {
                            "role": "user",
                            "content": f"User Query: {user_query}",
                        },
                    ],
                    phone_number=phone_number,
                    client_id=client_id,
                )

                logger.info(
                    "Classifier agent response",
                    extra={
                        "response": classifier_response,
                        "phone_number": phone_number,
                    },
                )

                classifier_response = json.loads(classifier_response)
                category = classifier_response["category"].strip().lower()
                data["classified_category"] = category

                logger.info(
                    "Classifier category",
                    extra={
                        "category": category,
                        "phone_number": phone_number,
                    },
                )

                if category == "human_handoff":
                    user_profile["live_agent_requested_at"] = int(time.time())
                    user_profile["live_agent_required"] = True
                    for admin in ADMINS:
                        send_customer_support_template(
                            phone_number=admin,
                            customer_name=user_profile.get("username", "Customer"),
                            customer_phone=phone_number,
                        )
                    data["bot_response"] = [
                        {
                            "type": "text",
                            "text": (
                                "Sure! I'm connecting you to a live designer right now. "
                                "Someone from our team will be with you shortly."
                            ),
                        }
                    ]
                    logger.info(
                        "Human handoff triggered",
                        extra={"phone_number": phone_number},
                    )
                    return data

                if category == "complaint":
                    user_profile["service_selected"] = ServiceList.COMPLAINT.value
                    data["bot_response"] = [build_complaint_flow_bot_response()]
                    logger.info(
                        "Complaint intent — launching damage complaint flow",
                        extra={"phone_number": phone_number},
                    )
                    return data

                service = _CATEGORY_TO_SERVICE.get(category)
                if service:
                    user_profile["service_selected"] = service.value
                else:
                    logger.warning(
                        "Unknown classifier category",
                        extra={
                            "category": category,
                            "phone_number": phone_number,
                        },
                    )

            return data
        except json.JSONDecodeError as e:
            logger.exception(
                "Classifier returned invalid JSON",
                extra={"exception": e, "phone_number": phone_number},
            )
            user_profile["service_selected"] = ""
            return data
        except Exception as e:
            logger.exception(
                "Exception occured while running classifier.",
                extra={"exception": e, "phone_number": phone_number},
            )
            user_profile["service_selected"] = ""
            return data
