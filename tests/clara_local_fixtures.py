"""Clara json/api dumps are gitignored; skip those tests when files are absent."""

from __future__ import annotations

import unittest
from pathlib import Path

CLARA_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "json" / "api" / "v1" / "clara"


def has_clara_file(*names: str) -> bool:
    return all((CLARA_FIXTURE_DIR / name).is_file() for name in names)


def skip_without_clara(*names: str):
    label = ", ".join(names)
    return unittest.skipUnless(
        has_clara_file(*names),
        f"json/api Clara fixtures not in checkout ({label} is gitignored)",
    )
