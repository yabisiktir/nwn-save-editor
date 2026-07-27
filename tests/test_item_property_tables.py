"""Tests for the iprp_* table reader (game/item_property_tables.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vaultkeeper.game.item_property_tables import ItemPropertyTables, parse_2da


def test_parse_2da_basic():
    text = "2DA V2.0\n\n     Name    Label\n0    135     Str\n1    133     Dex\n"
    header, rows = parse_2da(text)
    assert header == ["Name", "Label"]
    assert rows == {0: {"Name": "135", "Label": "Str"}, 1: {"Name": "133", "Label": "Dex"}}


def test_parse_2da_handles_quotes_and_stars():
    text = '2DA V2.0\n\n     Name    Label       Cost\n0    ****    "Big Name"  0.5\n'
    _header, rows = parse_2da(text)
    assert rows[0]["Name"] == "****" and rows[0]["Label"] == "Big Name"


# -- real game data (skipped when absent) ------------------------------------ #
_GAME = (
    Path.home()
    / "Library" / "Application Support" / "Steam" / "steamapps" / "common"
    / "Neverwinter Nights"
)
_HAK = Path.home() / "Documents" / "Neverwinter Nights" / "hak"


@pytest.mark.skipif(not _GAME.is_dir(), reason="no local NWN install on this box")
def test_real_iprp_options():
    tables = ItemPropertyTables.for_install(_GAME, _HAK if _HAK.is_dir() else None)
    assert tables.available

    # Ability Bonus (0): 6 ability subtypes, +N cost rows.
    abilities = tables.subtype_options(0)
    assert abilities is not None and abilities.get(0) == "Strength"
    costs = tables.cost_options(1)  # iprp_bonuscost
    assert costs.get(1) == "+1" and costs.get(5) == "+5"

    # AC Bonus / "Armor" (1) has no subtype.
    assert tables.subtype_options(1) is None

    # Damage Bonus (16): damage-type subtypes + a dice cost table.
    damage = tables.subtype_options(16)
    assert damage is not None and any("Fire" in name for name in damage.values())
    dice = tables.cost_options(4)  # iprp_damagecost
    assert len(dice) > 20

    # Cast Spell (15): the bundled (huge) spell subtype map + charge cost rows.
    spells = tables.subtype_options(15)
    assert spells is not None and len(spells) > 500
    charges = tables.cost_options(3)  # iprp_chargecost
    assert any("Charges" in name or "Single" in name for name in charges.values())
