"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def disable_kisna_utms_in_tests(monkeypatch):
    """Keep legacy URL assertions stable; UTM behavior tested separately."""
    monkeypatch.setenv("KISNA_UTM_ENABLED", "false")
