"""Tests for the appearance/portrait table reader (game/look_tables.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

_GAME = (
    Path.home()
    / "Library" / "Application Support" / "Steam" / "steamapps" / "common"
    / "Neverwinter Nights"
)
_HAK = Path.home() / "Documents" / "Neverwinter Nights" / "hak"


@pytest.mark.skipif(not _GAME.is_dir(), reason="no local NWN install on this box")
def test_real_appearance_and_portraits():
    from nwnfile.look_tables import LookTables

    tables = LookTables.for_install(_GAME, _HAK if _HAK.is_dir() else None)
    assert tables.available

    appearances = tables.appearance_options()
    assert appearances and appearances.get(6) == "Human"  # row 6 is Human
    assert tables.appearance_name(6) == "Human"

    portraits = tables.portrait_resrefs()
    assert portraits and len(portraits) == len(set(p.lower() for p in portraits))  # deduped
    assert all(ref and ref != "****" for ref in portraits)
