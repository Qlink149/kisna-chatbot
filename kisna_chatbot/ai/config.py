"""AI provider configuration from environment."""

import os
from functools import lru_cache

from kisna_chatbot.ai.types import AgentName, ProviderName

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# Translating canned copy into low-resource Indic languages is a different job
# from the rest of the pipeline, and the default model is not good enough at it.
# Benchmarked live over pa/te/ta/bn/kn/ml, 2 runs each, scored 0-3 by a judge
# plus a deterministic foreign-script count:
#
#   gpt-4o-mini    1.25  2/12 foreign   (production before this)
#   gpt-4.1-mini   1.75  1/12
#   gpt-4.1        2.33  3/12
#   gpt-5.6-luna   2.92  0/12
#
# The default model's errors were not cosmetic: Telugu "diamond rings" came
# back as "bangles" and "emerald pearls", Kannada "gold" as "silver" (twice),
# Punjabi "necklaces" as a horse-cart. A better prompt alone only moved it to
# 1.67, so the model is the binding constraint.
#
# Scoped to the languages that need it: Hindi, Marathi and every romanized
# variant stay on the default, which is genuinely fine there and ~0.5s faster.
#
# Do NOT point this at a reasoning model without re-checking: gpt-5-mini
# returned EMPTY output 12/12 under this call shape, its budget consumed by
# reasoning tokens.
DEFAULT_COMPOSE_WEAK_MODEL = "gpt-5.6-luna"
# Membership is decided per language by measurement, not by script family.
# Gujarati: the default rendered "gold rings" as "golden nation" / "gold map".
# Marathi: it left "रिंग्स" untranslated and produced "सोने च्या" (broken
# genitive) where the stronger model gives "सोन्याच्या अंगठ्यांच्या", 2/2.
# Hindi is genuinely good on the default and ~0.5s faster, so it stays off.
COMPOSE_WEAK_LANGUAGES = frozenset(
    {"ta", "te", "bn", "pa", "kn", "ml", "or", "as", "gu", "mr"}
)

MAX_OUTPUT_TOKENS_CLASSIFIER = 512
MAX_OUTPUT_TOKENS_GENERAL = 1024


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _parse_provider(value: str) -> ProviderName:
    normalized = (value or "openai").lower()
    if normalized == "openai":
        return ProviderName.OPENAI
    raise ValueError(
        f"Unsupported AI provider '{normalized}'. Only 'openai' is supported."
    )


@lru_cache(maxsize=1)
def get_ai_settings() -> dict:
    """Load AI settings from environment (cached until process restart)."""
    # OpenAI is the default for EVERY agent.
    default_provider = _parse_provider(_env("AI_PROVIDER", "openai"))
    classifier_override = _env("AI_PROVIDER_CLASSIFIER")
    general_override = _env("AI_PROVIDER_GENERAL")

    return {
        "default_provider": default_provider,
        "classifier_provider": _parse_provider(classifier_override)
        if classifier_override
        else default_provider,
        "general_provider": _parse_provider(general_override)
        if general_override
        else default_provider,
        "openai_api_key": _env("OPENAI_API_KEY"),
        "openai_chat_model": _env("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_MODEL),
        "compose_weak_model": _env(
            "AI_MODEL_COMPOSE_WEAK", DEFAULT_COMPOSE_WEAK_MODEL
        ),
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
    if provider != ProviderName.OPENAI:
        raise ValueError(
            f"Unsupported AI provider '{provider.value}'. Only 'openai' is supported."
        )
    return settings["openai_chat_model"]


def resolve_compose_model(language: str | None) -> str | None:
    """Model for reply_composer, or None to use the agent's normal model.

    Only the native-script low-resource languages are routed away; "ta-Latn"
    and friends are romanized and handled fine by the default model.
    """
    lang = (language or "").strip()
    if not lang or lang.endswith("-Latn") or lang not in COMPOSE_WEAK_LANGUAGES:
        return None
    configured = get_ai_settings()["compose_weak_model"]
    return configured or None


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
        },
    }
