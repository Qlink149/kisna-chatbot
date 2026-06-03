"""
Environment variable loader for the Kisna multi-client chatbot.

Copy .env.example to .env at the project root
before running the app so load_dotenv() can read it.
"""

import os

from dotenv import load_dotenv

load_dotenv()


def _log_warning(message: str) -> None:
    from kisna_chatbot.utils.logger_config import logger

    logger.warning(message, extra={"event": "env_validation"})

REQUIRED_IN_PROD = (
    "OPENAI_API_KEY",
    "MONGO_URI",
    "GUPSHUP_APP_ID",
    "GUPSHUP_TOKEN",
    "GUPSHUP_APP_NAME",
    "GUPSHUP_API_KEY",
    "GUPSHUP_WEBHOOK_SECRET",
    "JWT_SECRET_KEY",
    "SYSTEM_API_KEY",
    "KISNA_PRODUCT_API",
    "KISNA_OFFERS_API",
    "KISNA_STORE_API",
    "KISNA_VTIGER_BASE",
    "KISNA_VTIGER_TOKEN",
)

GUPSHUP_REQUIRED_KEYS = (
    "GUPSHUP_API_KEY",
    "GUPSHUP_APP_ID",
    "GUPSHUP_TOKEN",
    "GUPSHUP_APP_NAME",
)


def _getenv(key: str, default: str = "") -> str:
    """Read an environment variable, defaulting to empty string if unset."""
    return os.getenv(key, default)


openai_api_key = _getenv("OPENAI_API_KEY")
mongo_uri = _getenv("MONGO_URI")
mongo_db_name = _getenv("MONGO_DB_NAME", "Kisna_Chatbot")

chroma_api = _getenv("CHROMA_API_KEY")
chroma_tenant = _getenv("CHROMA_TENANT")

gupshup_app_id = _getenv("GUPSHUP_APP_ID")
gupshup_token = _getenv("GUPSHUP_TOKEN")
gupshup_app_name = _getenv("GUPSHUP_APP_NAME")
gupshup_api_key = _getenv("GUPSHUP_API_KEY")
gupshup_webhook_secret = _getenv("GUPSHUP_WEBHOOK_SECRET")
gupshup_phone_number = _getenv("GUPSHUP_PHONE_NUMBER")
gupshup_source = _getenv("GUPSHUP_SOURCE")

kisna_phone_number_id = _getenv("KISNA_PHONE_NUMBER_ID")
nkl_phone_number_id = _getenv("NKL_PHONE_NUMBER_ID")

super_admin_username = _getenv("SUPER_ADMIN_USERNAME")
super_admin_password = _getenv("SUPER_ADMIN_PASSWORD")
jwt_secret_key = _getenv("JWT_SECRET_KEY")
system_api_key = _getenv("SYSTEM_API_KEY")

kisna_product_api = _getenv("KISNA_PRODUCT_API")
kisna_offers_api = _getenv("KISNA_OFFERS_API")
kisna_store_api = _getenv("KISNA_STORE_API")
kisna_vtiger_base = _getenv("KISNA_VTIGER_BASE")
kisna_vtiger_token = _getenv("KISNA_VTIGER_TOKEN")

nkl_vtiger_base = _getenv("NKL_VTIGER_BASE")
nkl_vtiger_token = _getenv("NKL_VTIGER_TOKEN")

ai_provider = _getenv("AI_PROVIDER", "openai")
ai_provider_classifier = _getenv("AI_PROVIDER_CLASSIFIER")
ai_provider_general = _getenv("AI_PROVIDER_GENERAL", "openai")
groq_api_key = _getenv("GROQ_API_KEY")

is_production = _getenv("ENV_MODE", "dev").lower() == "prod"

_gupshup_startup_validated = False
_ai_startup_validated = False


def validate_env() -> None:
    """
    Validate required environment variables.

    Raises RuntimeError in production when any required key is missing.
    Logs warnings in non-production when keys are missing.
    """
    missing = [key for key in REQUIRED_IN_PROD if not _getenv(key)]
    if not missing:
        return
    message = f"Missing required environment variables: {', '.join(missing)}"
    if is_production:
        raise RuntimeError(message)
    _log_warning(message)


def validate_gupshup_config() -> None:
    """
    Validate Gupshup credentials and webhook settings.

    Called on FastAPI startup. Raises RuntimeError in production when required
    keys are missing. Logs warnings in development.
    """
    global _gupshup_startup_validated
    if _gupshup_startup_validated:
        return
    _gupshup_startup_validated = True

    missing = [key for key in GUPSHUP_REQUIRED_KEYS if not _getenv(key)]
    if is_production:
        prod_only = []
        if not _getenv("GUPSHUP_WEBHOOK_SECRET"):
            prod_only.append("GUPSHUP_WEBHOOK_SECRET")
        missing = list(dict.fromkeys(missing + prod_only))

    if missing:
        message = f"Missing Gupshup configuration: {', '.join(missing)}"
        if is_production:
            raise RuntimeError(message)
        _log_warning(message)

    if not _getenv("GUPSHUP_PHONE_NUMBER") and not _getenv("GUPSHUP_SOURCE"):
        message = (
            "Neither GUPSHUP_PHONE_NUMBER nor GUPSHUP_SOURCE is set; "
            "outbound WhatsApp sends may fail"
        )
        if is_production:
            raise RuntimeError(message)
        _log_warning(message)

    if not _getenv("GUPSHUP_WEBHOOK_SECRET"):
        if is_production:
            raise RuntimeError("GUPSHUP_WEBHOOK_SECRET is required in production")
        logger.warning("GUPSHUP_WEBHOOK_SECRET not set, skipping webhook verification")


def validate_ai_config() -> None:
    """
    Validate AI provider API keys for configured providers.

    Called on FastAPI startup after env is loaded.
    """
    global _ai_startup_validated
    if _ai_startup_validated:
        return
    _ai_startup_validated = True

    from kisna_chatbot.ai.config import get_ai_settings, refresh_ai_settings

    refresh_ai_settings()
    settings = get_ai_settings()

    providers_needed: set[str] = {settings["default_provider"].value}
    providers_needed.add(settings["classifier_provider"].value)
    providers_needed.add(settings["general_provider"].value)
    if settings["fallback_enabled"]:
        providers_needed.add(settings["fallback_provider"].value)

    missing: list[str] = []
    if "openai" in providers_needed and not settings["openai_api_key"]:
        missing.append("OPENAI_API_KEY")
    if "groq" in providers_needed and not settings["groq_api_key"]:
        missing.append("GROQ_API_KEY")

    if missing:
        message = f"Missing AI configuration: {', '.join(missing)}"
        if is_production:
            raise RuntimeError(message)
        _log_warning(message)


validate_env()
