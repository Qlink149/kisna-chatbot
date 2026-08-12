"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def disable_kisna_utms_in_tests(monkeypatch):
    """Keep legacy URL assertions stable; UTM behavior tested separately."""
    monkeypatch.setenv("KISNA_UTM_ENABLED", "false")


@pytest.fixture(autouse=True)
def disable_search_confirmation_in_tests(monkeypatch):
    """Legacy suites assert products on the first turn; recap tested separately."""
    monkeypatch.setenv("KISNA_SEARCH_CONFIRM_ENABLED", "false")
