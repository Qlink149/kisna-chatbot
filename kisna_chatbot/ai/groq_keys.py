"""Parse and rotate multiple Groq API keys for rate-limit handling."""

import os
from threading import Lock


def parse_groq_api_keys(
    *,
    groq_api_keys: str | None = None,
    groq_api_key: str | None = None,
) -> list[str]:
    """
    Load Groq keys from GROQ_API_KEYS (comma-separated) or single GROQ_API_KEY.
    """
    keys_raw = (groq_api_keys if groq_api_keys is not None else os.getenv("GROQ_API_KEYS", "")).strip()
    if keys_raw:
        return [k.strip() for k in keys_raw.split(",") if k.strip()]

    single = (groq_api_key if groq_api_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
    return [single] if single else []


class GroqKeyPool:
    """Round-robin Groq API keys; advance on rate limit."""

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("At least one Groq API key is required")
        self._keys = keys
        self._index = 0
        self._lock = Lock()

    @property
    def size(self) -> int:
        return len(self._keys)

    @property
    def current_index(self) -> int:
        return self._index

    def current_key(self) -> str:
        return self._keys[self._index]

    def rotate(self) -> tuple[int, int]:
        """
        Advance to the next key.

        Returns (new_index, total_keys). If only one key, index unchanged.
        """
        with self._lock:
            if len(self._keys) <= 1:
                return self._index, len(self._keys)
            self._index = (self._index + 1) % len(self._keys)
            return self._index, len(self._keys)
