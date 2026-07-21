import json
import re
import time

from kisna_chatbot.utils.logger_config import logger

DEFAULT_HISTORY_WINDOW = 8

# URLs in ASSISTANT history turns are anchor poison for the LLM: collection
# slugs like .../jewellery/rings+0k-to-10k+diamond read as entities and get
# copied into later extractions ("stuck on diamond rings" loop). Users got the
# real links in their WhatsApp messages; the LLM never needs them.
_URL_RE = re.compile(r"https?://\S+")


def _strip_urls(content: str) -> str:
    return _URL_RE.sub("", content or "").strip()


def get_recent_history(
    user_profile: dict,
    n: int = DEFAULT_HISTORY_WINDOW,
) -> list[dict]:
    """Return the last n chat turns as [{role, content}, ...]."""
    history = user_profile.get("chat_history") or []
    return history[-n:]


def format_recent_history_str(
    user_profile: dict,
    n: int = DEFAULT_HISTORY_WINDOW,
) -> str:
    """Last n turns as a 'Role: content' string for LLM system prompts.

    Assistant turns are URL-stripped at read time so legacy histories that
    stored collection/product URLs stop anchoring the model.
    """
    turns = get_recent_history(user_profile, n)
    lines: list[str] = []
    for t in turns:
        role = (t.get("role") or "").capitalize()
        content = t.get("content", "")
        if role == "Assistant":
            content = _strip_urls(content)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def trim_chat_history(history: list, max_len: int) -> list:
    """Keep only the last max_len entries."""
    if not history or len(history) <= max_len:
        return history
    return history[-max_len:]


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

            elif message_type == "image_with_cta":
                caption = assistant.get("caption", "")
                # Store only product title (first line) — no URLs, no
                # material/karat/price lines. Collection/product URL slugs
                # (e.g. .../rings+0k-to-10k+diamond) read like entities and
                # anchor the LLM to stale filters on later turns.
                first_line = caption.split("\n")[0].strip("* \n") if caption else ""
                body += f"\n[Product: {first_line}]" if first_line else "\n[Product shown]"

            elif message_type == "cta_url":
                text = assistant.get("text", "")
                display_text = assistant.get("display_text", "Link")
                if text:
                    body += f"\n{text}"
                # Button label only — never the URL (slug bleeds filters into
                # the LLM context; the user got the real link in the message).
                body += f"\n[Button: {display_text}]"

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


def format_chat_history(user, assistant, phone_number, request_id: str | None = None):
    """Format chat history as user/assistant message pairs."""
    try:
        now = int(time.time())
        user_entry = {
            "role": "user",
            "content": format_user(user_message=user, phone_number=phone_number),
            "timestamp": now,
        }
        assistant_entry = {
            "role": "assistant",
            "content": format_assistant(
                assistant_message=assistant, phone_number=phone_number
            ),
            "timestamp": now,
        }
        if request_id:
            user_entry["request_id"] = request_id
            assistant_entry["request_id"] = request_id
        return [user_entry, assistant_entry]
    except Exception as e:
        logger.exception(
            "formatting chat history failed",
            extra={"exception": e, "phone_number": phone_number},
        )
        raise
