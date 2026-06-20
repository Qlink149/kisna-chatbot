# ruff:noqa:E501
import os

from kisna_chatbot.utils import env_load as _env_load  # noqa: F401
from kisna_chatbot.config.gupshup import build_phone_number_id_map, get_gupshup_source

OPENAI_MODEL = "gpt-4o-mini"

DEFAULT_CLIENT_ID = "kisna"


def phone_number_id_to_client() -> dict[str, str]:
    """Lazy map from webhook phone_number_id to client_id (reads env at call time)."""
    return build_phone_number_id_map()


# Backward-compatible alias; prefer phone_number_id_to_client() for fresh env reads.
PHONE_NUMBER_ID_TO_CLIENT = phone_number_id_to_client()

GUPSHUP_SOURCE = get_gupshup_source() or os.getenv("GUPSHUP_SOURCE", "919909047798")
GUPSHUP_URL = "https://api.gupshup.io/wa/api/v1/msg"
GUPSHUP_TEMPLATE_URL = "https://partner.gupshup.io/partner/app/{app_id}/template/msg"
EMBEDDING_MODEL = "text-embedding-3-small"
SKIP_FIELDS_LOGGER = (
    "args",
    "exc_info",
    "exc_text",
    "stack_info",
    "msg",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "name",
    "lineno",
    "funcName",
)

AWAZ_ROUTE = "https://api.awaz.ai/v1"
AWAZ_SOURCE = "+12315005708"
CALLCHIMP_ROUTE = "https://api.callchimp.ai/v1"

TEXT_EMBEDDING_MODEL = "text-embedding-3-small"

RAZORPAY_REDIRECT = "https://wa.me/919909047798"

ADMINS = [
    "919876543210",
    "919876543211",
]

TECH_ADMINS = ["919876543210"]

KIA_HANDOFF_MESSAGE = (
    "I'm connecting you with a Kisna representative who'll assist "
    "you further. Thank you for your patience. 🙏"
)
