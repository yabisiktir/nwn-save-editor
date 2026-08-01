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
