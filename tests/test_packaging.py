"""The frozen-app build: that its inputs exist and its promises are kept.

Freezing itself is not run here — it takes half a minute and needs PyInstaller —
but everything the spec depends on is checked, because a missing data file shows
up as raw ids in a shipped app rather than as a build failure.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = _ROOT / "packaging" / "nwn-save-editor.spec"


def test_the_spec_and_its_driver_exist():
    assert _SPEC.is_file()
    assert (_ROOT / "scripts" / "build_app.py").is_file()


def test_the_entry_point_the_spec_freezes_is_the_real_one():
    """If these drift, the build succeeds and ships the wrong program."""
    spec = _SPEC.read_text(encoding="utf-8")
    assert '"nwnsaveeditor" / "ui" / "editor" / "__main__.py"' in spec

    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    console = data["project"]["gui-scripts"]["nwn-save-editor"]
    assert console == "nwnsaveeditor.ui.editor.__main__:main"


def test_the_game_tables_are_bundled_where_the_code_looks_for_them():
    """nwnfile reads these as files relative to its own module, not as package
    resources, so they must land at nwnfile/data or every name shows as an id."""
    spec = _SPEC.read_text(encoding="utf-8")
    assert '"nwnfile/data"' in spec
    assert (_ROOT / "src" / "nwnfile" / "data").is_dir()


def test_the_icons_are_bundled_where_appicon_looks():
    spec = _SPEC.read_text(encoding="utf-8")
    assert '"assets/icons"' in spec
    for name in ("icon.icns", "icon.ico"):
        assert (_ROOT / "assets" / "icons" / name).is_file(), f"{name} not built"


def test_the_screens_are_named_as_hidden_imports():
    """They are imported lazily by section key, which static analysis misses."""
    spec = _SPEC.read_text(encoding="utf-8")
    assert "nwnsaveeditor.ui.editor.screens" in spec
    assert "nwnsaveeditor.ui.dialogs" in spec


@pytest.mark.parametrize("module", ["QtWebEngineCore", "Qt3DCore", "QtQuick", "QtMultimedia"])
def test_the_qt_we_never_use_is_excluded(module):
    """PySide6 is large; left whole it roughly triples the download."""
    assert module in _SPEC.read_text(encoding="utf-8")


def test_nothing_we_actually_import_is_excluded():
    """An over-eager exclude is the classic way to ship a build that dies on
    first use rather than failing to build."""
    spec = _SPEC.read_text(encoding="utf-8")
    for needed in ("PySide6.QtWidgets", "PySide6.QtGui", "PySide6.QtCore", "PySide6.QtSvg"):
        assert f'"{needed}"' not in spec, f"{needed} is used and must not be excluded"


def test_the_artifact_is_named_after_the_version_in_pyproject():
    driver = (_ROOT / "scripts" / "build_app.py").read_text(encoding="utf-8")
    assert 'data["project"]["version"]' in driver


def test_a_macos_artifact_says_which_cpu_it_is_for():
    """PySide6 wheels are per-arch, so an Apple Silicon build will not launch on
    an Intel Mac. The filename has to say so."""
    driver = (_ROOT / "scripts" / "build_app.py").read_text(encoding="utf-8")
    assert "macos-{mac_arch()}" in driver


def test_build_output_is_not_committed():
    ignored = (_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/dist/" in ignored and "/build/" in ignored
