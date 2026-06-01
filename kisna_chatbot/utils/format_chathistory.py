import json
import time

from kisna_chatbot.utils.logger_config import logger


def format_assistant(assistant_message, phone_number):
    """Format the assistant message for chat history storage."""
    body = ""
    try:
        for assistant in assistant_message:
            message_type = assistant["type"]

            if message_type == "list":
                body += f"\nSent list - [{assistant.get('list', '')}]"

            elif message_type == "flow":
                body += f"\nSent flow - [{assistant.get('flow', '')}]"

            elif message_type in ("quick_reply", "quickreply"):
                option_titles = ", ".join(
                    opt["title"] for opt in assistant.get("options", [])
                )
                body += f"{assistant.get('text', '')}"
                if option_titles:
                    body += f"\n[Options: {option_titles}]"

            elif message_type == "media":
                captions = [
                    u["caption"]
                    for u in assistant.get("urls", [])
                    if u.get("caption")
                ]
                if captions:
                    body += f"\nShowed product images - {', '.join(captions)}"
                else:
                    body += "\nShowed product images"

            elif message_type == "cta_url":
                text = assistant.get("text", "")
                display_text = assistant.get("display_text", "Link")
                url = assistant.get("url", "")
                if text:
                    body += f"\n{text}"
                if url:
                    body += f"\n[Button: {display_text} -> {url}]"

            elif message_type == "text":
                body += f"{assistant.get('text', '')}"

            elif message_type == "skip":
                continue

            else:
                body += f"\nSent {message_type} message"

        return body
    except Exception as e:
        logger.exception(
            "formatting assistant message failed",
            extra={"exception": e, "phone_number": phone_number},
        )
        raise


def format_user(user_message, phone_number):
    """Format the user message for chat history storage."""
    try:
        msg_type = user_message.get("type", "")
        if msg_type == "text":
            return user_message["text"]["body"]

        if msg_type == "interactive":
            interactive_type = user_message["interactive"]["type"]
            if interactive_type == "list_reply":
                title = user_message["interactive"]["list_reply"]["title"]
                return f"User Selected - [{title}] from list"
            if interactive_type == "nfm_reply":
                response_json = json.loads(
                    user_message["interactive"]["nfm_reply"]["response_json"]
                )
                body = "Flow Reply - "
                for key, value in response_json.items():
                    body += f"\n{key}: {value}"
                return body
            if interactive_type == "button_reply":
                title = user_message["interactive"]["button_reply"]["title"]
                return f"User Selected - [{title}] from quick reply"

        return str(user_message)
    except Exception as e:
        logger.exception(
            "formatting user message failed",
            extra={"exception": e, "phone_number": phone_number},
        )
        raise


def format_chat_history(user, assistant, phone_number):
    """Format chat history as user/assistant message pairs."""
    try:
        now = int(time.time())
        return [
            {
                "role": "user",
                "content": format_user(user_message=user, phone_number=phone_number),
                "timestamp": now,
            },
            {
                "role": "assistant",
                "content": format_assistant(
                    assistant_message=assistant, phone_number=phone_number
                ),
                "timestamp": now,
            },
        ]
    except Exception as e:
        logger.exception(
            "formatting chat history failed",
            extra={"exception": e, "phone_number": phone_number},
        )
        raise
