"""
OpenAI async client for Responses API (GeneralAgent on OpenAI only).

Deprecated for new code: use kisna_chatbot.ai.openai_responses or run_general_agent.
"""

from openai import AsyncOpenAI

from kisna_chatbot.utils.env_load import openai_api_key

openai_client = AsyncOpenAI(api_key=openai_api_key)
