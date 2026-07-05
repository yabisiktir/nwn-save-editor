"""Shared pytest fixtures."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture()
def temp_dir() -> Iterator[Path]:
    """A throwaway temp directory (used by the salvaged binary-reader tests)."""
    path = Path(tempfile.mkdtemp(prefix="vaultkeeper_test_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
