"""OpenAI Responses API for GeneralAgent (web search + tools)."""

import json
import time

from kisna_chatbot.ai.config import get_ai_settings
from kisna_chatbot.ai.types import AgentName, GeneralAgentResult, ProviderName
from kisna_chatbot.ai.usage import build_usage_record, record_usage
from kisna_chatbot.constants import ADMINS
from kisna_chatbot.database.db_utils import request_live_agent
from kisna_chatbot.prompts.general_agent_kisna import (
    build_general_agent_prompt,
    output_schema,
    request_live_agent_tool,
    web_search_tool,
)
from kisna_chatbot.utils.get_openai_client import get_openai_client
from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.template.send_customer_support_template import (
    send_customer_support_template,
)


async def run_openai_general_agent(
    *,
    phone_number: str,
    client_id: str,
    username: str,
    user_query: str,
    chat_history_str: str,
) -> GeneralAgentResult:
    """
    Run GeneralAgent via OpenAI Responses API with web search and live-agent tool.
    """
    start = time.perf_counter()
    settings = get_ai_settings()
    model = settings["openai_chat_model"]

    input_messages = [
        {"role": "system", "content": f"Username: {username}"},
        {"role": "system", "content": f"Recent chat history:\n{chat_history_str}"},
        {"role": "user", "content": user_query},
    ]

    live_agent_requested = False
    response = None
    prompt_tokens = 0
    completion_tokens = 0

    try:
        for iteration in range(3):
            response = await get_openai_client().responses.create(
                model=model,
                instructions=build_general_agent_prompt(),
                input=input_messages,
                tools=[web_search_tool, request_live_agent_tool],
                text=output_schema,
                max_output_tokens=settings["max_tokens_general"],
                include=["web_search_call.action.sources"],
            )

            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens += getattr(usage, "input_tokens", 0) or 0
                completion_tokens += getattr(usage, "output_tokens", 0) or 0

            for item in response.output:
                if item.type == "web_search_call":
                    action = getattr(item, "action", None)
                    logger.info(
                        "GeneralAgent web search",
                        extra={
                            "queries": getattr(action, "queries", []) if action else [],
                            "phone_number": phone_number,
                        },
                    )

            logger.info(
                "GeneralAgent iteration",
                extra={
                    "iteration": iteration + 1,
                    "output_types": [item.type for item in response.output],
                    "phone_number": phone_number,
                },
            )

            function_calls = [
                item for item in response.output if item.type == "function_call"
            ]

            if not function_calls:
                break

            for fc in function_calls:
                input_messages.append(
                    {
                        "type": "function_call",
                        "call_id": fc.call_id,
                        "name": fc.name,
                        "arguments": fc.arguments,
                    }
                )

            for fc in function_calls:
                if fc.name == "request_live_agent":
                    request_live_agent(phone_number, client_id)
                    for admin in ADMINS:
                        send_customer_support_template(
                            phone_number=admin,
                            customer_name=username,
                            customer_phone=phone_number,
                        )
                    result = {"success": True}
                    live_agent_requested = True
                    logger.info(
                        "Live agent requested",
                        extra={"phone_number": phone_number},
                    )
                else:
                    result = {"error": f"Unknown tool: {fc.name}"}

                input_messages.append(
                    {
                        "type": "function_call_output",
                        "call_id": fc.call_id,
                        "output": json.dumps(result),
                    }
                )

            for item in response.output:
                if item.type in ("reasoning", "web_search_call"):
                    input_messages.append(item)

        message_item = next(
            (item for item in response.output if item.type == "message"), None
        )
        if not message_item:
            response = await get_openai_client().responses.create(
                model=model,
                instructions=build_general_agent_prompt(),
                input=input_messages,
                tools=[],
                text=output_schema,
                max_output_tokens=settings["max_tokens_general"],
            )
            usage = getattr(response, "usage", None)
            if usage:
                prompt_tokens += getattr(usage, "input_tokens", 0) or 0
                completion_tokens += getattr(usage, "output_tokens", 0) or 0
            message_item = next(
                (item for item in response.output if item.type == "message"), None
            )

        message_text: str | None = None
        if not live_agent_requested and message_item and message_item.content:
            output = json.loads(message_item.content[0].text)
            message_text = output.get("message", "")

        latency_ms = int((time.perf_counter() - start) * 1000)

        record_usage(
            build_usage_record(
                client_id=client_id,
                agent=AgentName.GENERAL.value,
                provider=ProviderName.OPENAI.value,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=True,
                phone_number=phone_number,
            )
        )

        return GeneralAgentResult(
            message_text=message_text,
            live_agent_requested=live_agent_requested,
            provider=ProviderName.OPENAI,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
        )

    except Exception as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        record_usage(
            build_usage_record(
                client_id=client_id,
                agent=AgentName.GENERAL.value,
                provider=ProviderName.OPENAI.value,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                success=False,
                phone_number=phone_number,
                error=str(e),
            )
        )
        raise
