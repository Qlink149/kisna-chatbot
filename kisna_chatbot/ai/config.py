"""AI provider configuration from environment."""

import os
from functools import lru_cache

from kisna_chatbot.ai.groq_keys import parse_groq_api_keys
from kisna_chatbot.ai.types import AgentName, ProviderName

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_GROQ_BASE_URL = "https://api.groq.com/openai/v1"

MAX_OUTPUT_TOKENS_CLASSIFIER = 512
MAX_OUTPUT_TOKENS_GENERAL = 1024


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _parse_provider(value: str) -> ProviderName:
    normalized = (value or "openai").lower()
    if normalized == "groq":
        return ProviderName.GROQ
    return ProviderName.OPENAI


@lru_cache(maxsize=1)
def get_ai_settings() -> dict:
    """Load AI settings from environment (cached until process restart)."""
    default_provider = _parse_provider(_env("AI_PROVIDER", "groq"))
    classifier_override = _env("AI_PROVIDER_CLASSIFIER")
    general_override = _env("AI_PROVIDER_GENERAL", "groq")
    groq_api_keys = parse_groq_api_keys()

    return {
        "default_provider": default_provider,
        "classifier_provider": _parse_provider(classifier_override)
        if classifier_override
        else default_provider,
        "general_provider": _parse_provider(general_override),
        "fallback_enabled": _env("AI_FALLBACK_ENABLED", "false").lower()
        in ("1", "true", "yes"),
        "fallback_provider": _parse_provider(
            _env("AI_FALLBACK_PROVIDER", "groq")
        ),
        "openai_api_key": _env("OPENAI_API_KEY"),
        "openai_chat_model": _env("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL),
        "groq_api_keys": groq_api_keys,
        "groq_api_key": groq_api_keys[0] if groq_api_keys else "",
        "groq_chat_model": _env("GROQ_CHAT_MODEL", DEFAULT_GROQ_MODEL),
        "groq_base_url": _env("GROQ_BASE_URL", DEFAULT_GROQ_BASE_URL),
        "groq_rate_limit_retry_keys": _env("GROQ_RATE_LIMIT_RETRY_KEYS", "true").lower()
        in ("1", "true", "yes"),
        "max_tokens_classifier": int(
            _env("AI_MAX_TOKENS_CLASSIFIER", str(MAX_OUTPUT_TOKENS_CLASSIFIER))
        ),
        "max_tokens_general": int(
            _env("AI_MAX_TOKENS_GENERAL", str(MAX_OUTPUT_TOKENS_GENERAL))
        ),
    }


def refresh_ai_settings() -> None:
    """Clear cached AI settings (for tests)."""
    get_ai_settings.cache_clear()


def resolve_provider(agent: AgentName) -> ProviderName:
    settings = get_ai_settings()
    if agent == AgentName.CLASSIFIER:
        return settings["classifier_provider"]
    if agent == AgentName.GENERAL:
        return settings["general_provider"]
    return settings["default_provider"]


def resolve_model(provider: ProviderName) -> str:
    settings = get_ai_settings()
    if provider == ProviderName.GROQ:
        return settings["groq_chat_model"]
    return settings["openai_chat_model"]


def resolve_max_tokens(agent: AgentName) -> int:
    settings = get_ai_settings()
    if agent == AgentName.CLASSIFIER:
        return settings["max_tokens_classifier"]
    return settings["max_tokens_general"]


def agent_capabilities(agent: AgentName, provider: ProviderName) -> set[str]:
    caps = {"chat_completion"}
    if agent == AgentName.GENERAL and provider == ProviderName.OPENAI:
        caps.add("responses_api")
        caps.add("hosted_web_search")
    return caps


def get_public_config() -> dict:
    """Effective provider/model per agent for admin API."""
    settings = get_ai_settings()
    return {
        "default_provider": settings["default_provider"].value,
        "fallback_enabled": settings["fallback_enabled"],
        "fallback_provider": settings["fallback_provider"].value,
        "agents": {
            AgentName.CLASSIFIER.value: {
                "provider": resolve_provider(AgentName.CLASSIFIER).value,
                "model": resolve_model(resolve_provider(AgentName.CLASSIFIER)),
                "capabilities": list(
                    agent_capabilities(
                        AgentName.CLASSIFIER,
                        resolve_provider(AgentName.CLASSIFIER),
                    )
                ),
            },
            AgentName.GENERAL.value: {
                "provider": resolve_provider(AgentName.GENERAL).value,
                "model": resolve_model(resolve_provider(AgentName.GENERAL)),
                "capabilities": list(
                    agent_capabilities(
                        AgentName.GENERAL,
                        resolve_provider(AgentName.GENERAL),
                    )
                ),
            },
        },
        "models": {
            "openai": settings["openai_chat_model"],
            "groq": settings["groq_chat_model"],
        },
    }
