"""nwnfile is a layer nwnsaveeditor sits on, not the other way round.

Split out of Vaultkeeper's repo, where these also guarded against importing the
application. That half is gone with the application; what remains is the boundary
inside this repo, which is the one that has to keep holding.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import pytest

import nwnfile

_SRC = Path(__file__).resolve().parents[1] / "src"


def _modules(package: str) -> list[Path]:
    return [p for p in (_SRC / package).rglob("*.py") if "__pycache__" not in p.parts]


def test_the_file_layer_never_reaches_up_to_the_editor():
    offenders = [
        f"{path.relative_to(_SRC)}"
        for path in _modules("nwnfile")
        if re.search(r"^\s*(from|import)\s+nwnsaveeditor", path.read_text(encoding="utf-8"), re.M)
    ]
    assert not offenders, f"nwnfile must not import nwnsaveeditor: {offenders}"


def test_the_file_layer_does_not_even_name_the_editor():
    """A layer that advertises its consumers invites the reverse import later."""
    named = [
        f"{path.relative_to(_SRC)}"
        for path in _modules("nwnfile")
        if "nwnsaveeditor" in path.read_text(encoding="utf-8")
    ]
    assert not named, f"nwnfile mentions nwnsaveeditor: {named}"


def test_the_file_layer_is_qt_free():
    """It decodes files into plain buffers, so it installs and tests headless.

    An import, not a mention: the readers carry comments explaining that the
    QPixmap step is deliberately elsewhere, and those are worth keeping.
    """
    for path in _modules("nwnfile"):
        assert not re.search(
            r"^\s*(from|import)\s+PySide6", path.read_text(encoding="utf-8"), re.M
        ), f"{path.name} imports Qt"


def test_the_qt_conversions_live_with_the_editor():
    from nwnsaveeditor.ui.icons import item_icon_source, load_item_icon, tga_to_pixmap

    assert all(callable(f) for f in (item_icon_source, load_item_icon, tga_to_pixmap))


def test_every_file_layer_module_imports_on_its_own():
    """Catches a stale intra-package import that tests happen not to exercise."""
    for info in pkgutil.walk_packages(nwnfile.__path__, prefix="nwnfile."):
        importlib.import_module(info.name)


def test_the_bundled_game_data_travelled_with_the_code_that_reads_it():
    from nwnfile.character_reference import default_reference
    from nwnfile.item_names import base_item_type

    assert (_SRC / "nwnfile" / "data").is_dir()
    assert default_reference().feat_names, "PRC/base feat names are bundled here"
    assert base_item_type(0), "and base item names too"


def test_the_readers_log_under_their_own_name():
    """Not an application's, or the package could not be used without one."""
    from nwnfile.log import LOG_NAME, get_logger

    assert LOG_NAME == "nwnfile"
    assert get_logger("formats.test").name == "nwnfile.formats.test"


@pytest.mark.parametrize(
    "module",
    ["formats.gff", "formats.erf_reader", "formats.bic_reader", "formats.tlk_reader",
     "character", "character_reference", "item_names", "item_properties",
     "item_property_tables", "item_icons", "look_tables", "win_sort"],
)
def test_the_expected_modules_live_in_the_file_layer(module):
    assert importlib.import_module(f"nwnfile.{module}") is not None


def test_both_packages_are_built_and_the_entry_point_points_here():
    import tomllib

    data = tomllib.loads((_SRC.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/nwnfile", "src/nwnsaveeditor",
    ]
    assert data["project"]["gui-scripts"]["nwn-save-editor"].startswith("nwnsaveeditor.")
    assert data["project"]["name"] == "nwn-save-editor"
