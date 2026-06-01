"""Shared types for multi-provider AI."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ProviderName(str, Enum):
    OPENAI = "openai"
    GROQ = "groq"


class AgentName(str, Enum):
    CLASSIFIER = "classifier"
    GENERAL = "general"


class AgentCapability(str, Enum):
    CHAT_COMPLETION = "chat_completion"
    RESPONSES_API = "responses_api"
    HOSTED_WEB_SEARCH = "hosted_web_search"


@dataclass
class CompletionRequest:
    agent: AgentName
    agent_display_name: str
    instruction: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    max_output_tokens: int = 1024
    phone_number: str | None = None
    client_id: str | None = None


@dataclass
class CompletionResult:
    text: str
    provider: ProviderName
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    fallback_used: bool = False


@dataclass
class GeneralAgentResult:
    message_text: str | None
    live_agent_requested: bool
    provider: ProviderName
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    capability_degraded: list[str] = field(default_factory=list)


@dataclass
class UsageRecord:
    client_id: str
    agent: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    latency_ms: int
    success: bool
    phone_number: str | None = None
    error: str | None = None
    fallback_used: bool = False
