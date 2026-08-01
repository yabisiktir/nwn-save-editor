"""Shared pytest fixtures."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

# Run all Qt-based tests headlessly (no display needed). Set before any Qt import.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path_factory, monkeypatch) -> Iterator[None]:
    """Point the editor's own settings file at a per-test temp directory.

    ``StandaloneHost`` remembers the light/dark choice on disk. Without this, a
    test that constructs one with no explicit ``settings_dir`` would write the
    developer's real settings file and leak state between tests. The equivalent
    fixture in the repo this was split from guarded the application's store for
    the same reason, after it once ate live user data.
    """
    home = tmp_path_factory.mktemp("settings")
    monkeypatch.setattr(
        "nwnsaveeditor.ui.editor.host.default_settings_dir", lambda: home
    )
    yield


@pytest.fixture(autouse=True)
def _fresh_install_caches() -> Iterator[None]:
    """Empty the install-keyed caches between tests.

    They are keyed on the game folder, so a test that writes different 2DA
    content to a path another test already used would otherwise be answered from
    that other test's data.
    """
    from nwnfile import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture()
def temp_dir() -> Iterator[Path]:
    """A throwaway temp directory (used by the salvaged binary-reader tests)."""
    path = Path(tempfile.mkdtemp(prefix="nwn_save_editor_test_"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
