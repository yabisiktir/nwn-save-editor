"""Tests for save-area content decoding (game/save_area.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nwnfile.item_names import resolver_for
from nwnsaveeditor.save_area import (
    AreaContents,
    Container,
    CreatureRef,
    Store,
    read_area_contents,
    read_factions,
)
from nwnsaveeditor.save_game import scan_save_games


def test_area_contents_helpers():
    area = AreaContents(width=11, height=8, interior=True, underground=True)
    assert area.dimensions == "11×8"
    assert area.terrain == "interior, underground"
    assert AreaContents().dimensions == ""  # no size known
    assert AreaContents().terrain == "exterior"  # no flags -> exterior


def test_creature_item_count():
    cre = CreatureRef(name="Goblin", carried=[object(), object()], equipped=[object()])  # type: ignore[list-item]
    assert cre.item_count == 3


def test_store_and_container_defaults():
    assert Store().items == [] and Store().name == ""
    assert Container().items == []


# Real saves on the developer's machine (skipped when absent).
_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"
_GAME = (
    Path.home()
    / "Library" / "Application Support" / "Steam" / "steamapps" / "common"
    / "Neverwinter Nights"
)


def _first_sav():
    saves = scan_save_games(_SAVES)
    return next((s for s in saves if s.sav_path is not None), None)


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_area_contents_decode():
    save = _first_sav()
    assert save is not None
    info = save.module_info()
    assert info is not None and info.areas
    resolver = resolver_for(_GAME if _GAME.is_dir() else None)

    total_creatures = 0
    store_with_named_items = False
    any_area = False
    for resref, _name in info.areas:
        area = read_area_contents(save.sav_path, resref, resolver=resolver)
        if area is None:
            continue
        any_area = True
        total_creatures += len(area.creatures)
        for store in area.stores:
            # A store has stock, and (with the install's dialog.tlk) real item names.
            assert isinstance(store, Store)
            if store.items and any(
                not it.name.startswith("(unnamed") for it in store.items
            ):
                store_with_named_items = True
        # Filtered utility creatures never leak into the listing.
        assert all(c.name != "prc_2da_cache" for c in area.creatures)
    assert any_area
    assert total_creatures > 0  # a populated module always has creatures somewhere
    # If the install's dialog.tlk is present, store items should resolve real names.
    if _GAME.is_dir():
        assert store_with_named_items


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_factions_decode():
    save = _first_sav()
    assert save is not None
    factions = read_factions(save.sav_path)
    assert factions  # every module ships the standard faction table
    assert any(f.name == "Commoner" for f in factions)


# -- faction standings ------------------------------------------------------ #
def test_a_faction_the_module_never_customised_reads_as_neutral(tmp_path):
    """``RepList`` stores only the pairs a module changed.

    One of the owner's saves lists rows (0,1) and (0,5)..(0,17) but omits (0,2),
    (0,3) and (0,4) — Commoner, Merchant, Defender. Absent is not "unknown": the
    engine treats an unlisted pair as neutral, and rendering a blank said less
    than the game does.
    """
    from tests.test_save_editor import _make_erf

    from nwnfile.formats.gff import Gff, GffField, GffList, GffStruct, GffType, write_gff
    from nwnsaveeditor.save_area import DEFAULT_REPUTATION

    def _faction(name):
        return GffStruct(struct_type=0, fields={
            "FactionName": GffField(GffType.CEXOSTRING, name),
            "FactionGlobal": GffField(GffType.BYTE, 0),
        })

    def _rep(f1, f2, value):
        return GffStruct(struct_type=0, fields={
            "FactionID1": GffField(GffType.DWORD, f1),
            "FactionID2": GffField(GffType.DWORD, f2),
            "FactionRep": GffField(GffType.DWORD, value),
        })

    fac = Gff("FAC ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "FactionList": GffField(GffType.LIST, GffList(
            [_faction("PC"), _faction("Hostile"), _faction("Commoner")]
        )),
        # Only the Hostile pair is stored; Commoner is left to the default.
        "RepList": GffField(GffType.LIST, GffList([_rep(0, 1, 0)])),
    }))
    path = tmp_path / "x.sav"
    path.write_bytes(_make_erf([("repute", 2038, write_gff(fac))]))

    factions = {f.name: f for f in read_factions(path)}
    assert factions["Hostile"].reputation_to_pc == 0
    assert not factions["Hostile"].reputation_is_default
    # The one nobody customised: neutral, and flagged as the default rather than
    # presented as something the module chose.
    assert factions["Commoner"].reputation_to_pc == DEFAULT_REPUTATION
    assert factions["Commoner"].reputation_is_default
