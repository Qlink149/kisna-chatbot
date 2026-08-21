"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def disable_kisna_utms_in_tests(monkeypatch):
    """Keep legacy URL assertions stable; UTM behavior tested separately."""
    monkeypatch.setenv("KISNA_UTM_ENABLED", "false")


@pytest.fixture(autouse=True)
def match_production_search_confirmation(request, monkeypatch):
    """Run the suite with the PRODUCTION default (audit P2-2).

    This used to force the recap OFF for the whole suite, so every test
    exercised a configuration no user ever sees — which is how the
    search-confirmation correction loop reached production untested.

    The recap gates the FIRST turn of a search. Tests of what happens AFTER
    that gate (Clara call shape, client-side filtering, fallback strategies)
    opt out explicitly with @pytest.mark.no_search_recap, so the bypass is
    visible in the test rather than hidden in a global default.
    """
    enabled = "false" if request.node.get_closest_marker("no_search_recap") else "true"
    monkeypatch.setenv("KISNA_SEARCH_CONFIRM_ENABLED", enabled)


# ── No live LLM calls in pytest ────────────────────────────────────────────
#
# The suite was making real API calls: complete_chat succeeded because real
# credentials could reach tests from the
# developer's ambient environment. Results were environment-dependent and not
# reproducible on a clean machine or in CI, and some tests were quietly
# asserting against live model output.
#
# The guard patches the NETWORK BOUNDARY, not the callers. Every route to a
# provider — complete_chat, the escape gate, extract_entities_with_llm, the
# reply composer, GeneralAgent, the Responses API, Chroma embeddings — ends at
# one of these, so a new caller cannot slip past the guard by being added
# later. Tests that legitimately need a live call use @pytest.mark.live.

_LIVE_CALL_MESSAGE = (
    "Live LLM call attempted in tests. "
    "Mark the test with @pytest.mark.live, or use a mock/fixture."
)

_PROVIDER_KEY_VARS = (
    "OPENAI_API_KEY",
)

def _raise_live_call(*_args, **_kwargs):
    raise RuntimeError(_LIVE_CALL_MESSAGE)


async def _raise_live_call_async(*_args, **_kwargs):
    raise RuntimeError(_LIVE_CALL_MESSAGE)


class _BlockedAsyncOpenAI:
    """Stands in for a real SDK client: constructs fine, never reaches the wire.

    Deliberately blocks at the CLIENT, not at ChatProvider.complete. Provider
    unit tests (key rotation on 429) legitimately call complete() against a
    client they stub themselves; blocking the method would make those tests
    untestable while blocking the client still stops every real request.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    @property
    def responses(self):
        return self

    @property
    def embeddings(self):
        return self

    async def create(self, *_args, **_kwargs):
        raise RuntimeError(_LIVE_CALL_MESSAGE)


# (module path, attribute, replacement) reaching a provider over the network.
_NETWORK_BOUNDARY = (
    ("kisna_chatbot.ai.base", "AsyncOpenAI", _BlockedAsyncOpenAI),
    ("kisna_chatbot.utils.get_openai_client", "AsyncOpenAI", _BlockedAsyncOpenAI),
    ("kisna_chatbot.ai.openai_responses", "get_openai_client", _raise_live_call),
    ("kisna_chatbot.utils.get_openai_client", "get_openai_client", _raise_live_call),
)


@pytest.fixture(autouse=True)
def block_live_llm_calls(request, monkeypatch):
    """Fail loudly on any real provider call. Autouse for the whole suite."""
    if request.node.get_closest_marker("live"):
        # Generator fixture — a bare `return` here exits before the `yield`
        # below ever runs, which pytest's fixture machinery treats as an
        # error ("did not yield a value") rather than a valid skip. This
        # path was never exercised before (the default `-m "not live"`
        # addopts excludes @pytest.mark.live tests at collection, so the
        # fixture body never ran for them) until a test actually opted in.
        yield
        return

    # A key on the developer's machine must never leak into a test run.
    for var in _PROVIDER_KEY_VARS:
        monkeypatch.setenv(var, "test-sentinel-do-not-use")

    # Provider settings are lru_cached, so a cache warmed with real keys
    # before this fixture ran would defeat the sentinels.
    from kisna_chatbot.ai.config import refresh_ai_settings

    refresh_ai_settings()

    import importlib

    for module_path, attr, replacement in _NETWORK_BOUNDARY:
        try:
            module = importlib.import_module(module_path)
        except Exception:  # optional dependency (e.g. chromadb) not installed
            continue
        if not hasattr(module, attr):
            continue
        monkeypatch.setattr(module, attr, replacement, raising=False)

    yield
    refresh_ai_settings()
