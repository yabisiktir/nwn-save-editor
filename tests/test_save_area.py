"""Tests for save-area content decoding (game/save_area.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

from vaultkeeper.game.item_names import resolver_for
from vaultkeeper.game.save_area import (
    AreaContents,
    Container,
    CreatureRef,
    Store,
    read_area_contents,
    read_factions,
)
from vaultkeeper.game.save_game import scan_save_games


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
