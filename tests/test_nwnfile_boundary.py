"""The nwnfile package is a layer Vaultkeeper sits on, not part of it.

These guard the direction of the arrow. A single import pointing the wrong way
turns two packages back into one, and it is the kind of thing that slips in
without anyone deciding to do it.
"""

from __future__ import annotations

import logging
import pkgutil
import re
from pathlib import Path

import pytest

import nwnfile

_SRC = Path(__file__).resolve().parents[1] / "src"


def _modules(package: str) -> list[Path]:
    root = _SRC / package
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def test_nwnfile_never_imports_vaultkeeper():
    """The whole point of the split: the file layer must not know the app.

    Imports, not mentions — a docstring naming a consumer is untidy but it is not
    a dependency, and asserting on prose would fail for the wrong reasons.
    """
    offenders = [
        f"{path.relative_to(_SRC)}"
        for path in _modules("nwnfile")
        if re.search(r"^\s*(from|import)\s+vaultkeeper", path.read_text(encoding="utf-8"), re.M)
    ]
    assert not offenders, f"nwnfile must not import vaultkeeper: {offenders}"


def test_nwnfile_does_not_even_name_vaultkeeper():
    """A layer that advertises its consumers by module path invites the reverse
    import later. Kept separate from the import check so a stray mention reads as
    the tidiness problem it is, not as a broken boundary."""
    named = [
        f"{path.relative_to(_SRC)}"
        for path in _modules("nwnfile")
        if "vaultkeeper" in path.read_text(encoding="utf-8")
    ]
    assert not named, f"nwnfile mentions vaultkeeper: {named}"


def test_nwnfile_needs_nothing_but_the_standard_library():
    """No Qt, no app config — it reads files, so it should install anywhere."""
    banned = ("PySide6", "vaultkeeper")
    for path in _modules("nwnfile"):
        text = path.read_text(encoding="utf-8")
        for name in banned:
            assert f"import {name}" not in text, f"{path.name} imports {name}"


def test_every_nwnfile_module_imports_on_its_own():
    """Catches a stale intra-package import that tests happen not to exercise."""
    import importlib

    for info in pkgutil.walk_packages(nwnfile.__path__, prefix="nwnfile."):
        importlib.import_module(info.name)


def test_the_bundled_game_data_moved_with_the_code_that_reads_it():
    from nwnfile.character_reference import default_reference
    from nwnfile.item_names import base_item_type

    assert (_SRC / "nwnfile" / "data").is_dir()
    assert default_reference().feat_names, "PRC/base feat names are bundled here now"
    assert base_item_type(0), "and base item names too"


def test_the_readers_log_under_their_own_name(caplog):
    """Not Vaultkeeper's, or the package could not be used without it."""
    from nwnfile.log import LOG_NAME, get_logger

    assert LOG_NAME == "nwnfile"
    logger = get_logger("formats.test")
    assert logger.name == "nwnfile.formats.test"


def test_vaultkeeper_still_collects_those_lines_in_its_own_log(tmp_path):
    """Naming them separately must not mean losing them from the app's log."""
    import vaultkeeper.core.log as vklog

    monkeyed = vklog._CONFIGURED
    vklog._CONFIGURED = False
    try:
        vklog.configure_logging(to_console=False, log_path=tmp_path / "v.log")
        adopted = logging.getLogger("nwnfile")
        assert adopted.handlers, "the app adopts the nwnfile logger"
        get = logging.getLogger("vaultkeeper")
        assert {type(h) for h in adopted.handlers} <= {type(h) for h in get.handlers}
    finally:
        for handler in list(logging.getLogger("nwnfile").handlers):
            logging.getLogger("nwnfile").removeHandler(handler)
        for handler in list(logging.getLogger("vaultkeeper").handlers):
            logging.getLogger("vaultkeeper").removeHandler(handler)
        vklog._CONFIGURED = monkeyed


@pytest.mark.parametrize(
    "module",
    ["formats.gff", "formats.erf_reader", "formats.bic_reader", "formats.tlk_reader",
     "character", "character_reference", "item_names", "item_properties",
     "item_property_tables", "item_icons", "look_tables", "win_sort"],
)
def test_the_expected_modules_live_here(module):
    import importlib

    assert importlib.import_module(f"nwnfile.{module}") is not None


def test_both_packages_are_built_into_the_wheel():
    import tomllib

    data = tomllib.loads((_SRC.parent / "pyproject.toml").read_text(encoding="utf-8"))
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert "src/nwnfile" in packages
    assert "src/vaultkeeper" in packages


# -- nwnsaveeditor ----------------------------------------------------------- #
def test_the_save_editor_never_imports_vaultkeeper():
    """It is a save editor Vaultkeeper opens, not a part of Vaultkeeper. One
    import the other way and the two are a single package again."""
    offenders = [
        f"{path.relative_to(_SRC)}"
        for path in _modules("nwnsaveeditor")
        if re.search(r"^\s*(from|import)\s+vaultkeeper", path.read_text(encoding="utf-8"), re.M)
    ]
    assert not offenders, f"nwnsaveeditor must not import vaultkeeper: {offenders}"


def test_the_layers_stack_one_way():
    """nwnfile knows neither of the others; the editor knows only nwnfile."""
    for path in _modules("nwnfile"):
        text = path.read_text(encoding="utf-8")
        assert "nwnsaveeditor" not in text, f"{path.name} reaches up to the editor"


def test_the_save_editor_runs_without_a_vaultkeeper_import(tmp_path):
    """Imported in a fresh interpreter, so a module another test already loaded
    cannot mask a missing dependency."""
    import subprocess
    import sys

    code = (
        "import sys;"
        "import nwnsaveeditor.ui.editor.window;"
        "import nwnsaveeditor.ui.editor.__main__;"
        "print('vaultkeeper' in ','.join(sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "importing the editor pulled in vaultkeeper"


def test_the_qt_conversions_are_not_in_the_file_layer():
    """nwnfile decodes images into plain buffers and must stay Qt-free, so the
    QPixmap/QIcon step lives with the editor and Vaultkeeper reuses it."""
    from nwnsaveeditor.ui.icons import item_icon_source, load_item_icon, tga_to_pixmap

    assert all(callable(f) for f in (item_icon_source, load_item_icon, tga_to_pixmap))
    for path in _modules("nwnfile"):
        # An import, not a mention: the readers carry comments explaining that the
        # QPixmap step is deliberately elsewhere, and those are worth keeping.
        assert not re.search(r"^\s*(from|import)\s+PySide6",
                             path.read_text(encoding="utf-8"), re.M)


def test_vaultkeeper_reuses_those_rather_than_keeping_a_second_copy():
    from nwnsaveeditor.ui import icons
    from vaultkeeper.ui.dialogs import character_viewer, inventory_view

    assert character_viewer.tga_to_pixmap is icons.tga_to_pixmap
    assert character_viewer.item_icon_source is icons.item_icon_source
    assert inventory_view._load_icon is icons.load_item_icon


def test_reading_a_save_folders_location_lives_with_the_save_package():
    from nwnsaveeditor.save_game import get_location_in_game_save
    from vaultkeeper.game import game_saves

    assert game_saves.get_location_in_game_save is get_location_in_game_save


def test_all_three_packages_are_built():
    import tomllib

    data = tomllib.loads((_SRC.parent / "pyproject.toml").read_text(encoding="utf-8"))
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages == ["src/nwnfile", "src/nwnsaveeditor", "src/vaultkeeper"]
    assert data["project"]["gui-scripts"]["nwn-save-editor"].startswith("nwnsaveeditor.")
