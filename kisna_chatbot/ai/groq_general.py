"""GeneralAgent via Groq chat completions (no hosted web search)."""

import json
import time

from kisna_chatbot.ai.config import get_ai_settings
from kisna_chatbot.ai.factory import get_chat_provider
from kisna_chatbot.ai.types import AgentName, CompletionRequest, GeneralAgentResult, ProviderName
from kisna_chatbot.ai.usage import build_usage_record, record_usage
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.database.db_utils import request_live_agent
from kisna_chatbot.prompts.general_agent_kisna import (
    REQUEST_LIVE_AGENT_DESCRIPTION,
    build_general_agent_prompt,
)
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)

_LIVE_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "request_live_agent",
        "description": REQUEST_LIVE_AGENT_DESCRIPTION,
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def _live_agent_tool_requested(tool_calls: list | None) -> bool:
    if not tool_calls:
        return False
    for call in tool_calls:
        fn = getattr(call, "function", None)
        if fn and getattr(fn, "name", None) == "request_live_agent":
            return True
    return False


async def run_groq_general_agent(
    *,
    phone_number: str,
    client_id: str,
    username: str,
    user_query: str,
    chat_history_str: str,
) -> GeneralAgentResult:
    """
    GeneralAgent on Groq: chat completions + request_live_agent tool only.

    Web search is not available; the knowledge base in the prompt is the sole
    grounding for policy/FAQ answers.
    """
    start = time.perf_counter()
    settings = get_ai_settings()
    model = settings["groq_chat_model"]
    provider = get_chat_provider(AgentName.GENERAL)

    instruction = (
        build_general_agent_prompt()
        + "\n\nNote: Live web search is unavailable in this mode. "
        "Use the KNOWLEDGE BASE above for all policy answers. "
        "Respond with JSON only: {\"message\": \"your WhatsApp reply\"} "
        "unless you are calling request_live_agent."
    )

    messages = [
        {"role": "system", "content": f"Username: {username}"},
        {"role": "system", "content": f"Recent chat history:\n{chat_history_str}"},
        {"role": "user", "content": user_query},
    ]

    live_agent_requested = False
    message_text: str | None = None

    try:
        result = await provider.complete(
            CompletionRequest(
                agent=AgentName.GENERAL,
                agent_display_name="General Agent",
                instruction=instruction,
                messages=messages,
                tools=[_LIVE_AGENT_TOOL],
                max_output_tokens=settings["max_tokens_general"],
                phone_number=phone_number,
                client_id=client_id,
            )
        )

        text = result.text
        if text:
            try:
                parsed = json.loads(text)
                message_text = parsed.get("message", text)
            except json.JSONDecodeError:
                message_text = text

        if _live_agent_tool_requested(result.tool_calls):
            request_live_agent(phone_number, client_id)
            for admin in ADMINS:
                send_customer_support_template(
                    phone_number=admin,
                    customer_name=username,
                    customer_phone=phone_number,
                )
            live_agent_requested = True
            logger.info(
                "Live agent requested via Groq tool call",
                extra={"phone_number": phone_number},
            )

        latency_ms = int((time.perf_counter() - start) * 1000)

        record_usage(
            build_usage_record(
                client_id=client_id,
                agent=AgentName.GENERAL.value,
                provider=ProviderName.GROQ.value,
                model=result.model,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                latency_ms=latency_ms,
                success=True,
                phone_number=phone_number,
            )
        )

        logger.warning(
            "GeneralAgent running on Groq without hosted web search",
            extra={"phone_number": phone_number, "capability_degraded": "web_search"},
        )

        return GeneralAgentResult(
            message_text=message_text,
            live_agent_requested=live_agent_requested,
            provider=ProviderName.GROQ,
            model=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=latency_ms,
            capability_degraded=["hosted_web_search"],
        )

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        record_usage(
            build_usage_record(
                client_id=client_id,
                agent=AgentName.GENERAL.value,
                provider=ProviderName.GROQ.value,
                model=model,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=latency_ms,
                success=False,
                phone_number=phone_number,
                error=str(e),
            )
        )
        raise
