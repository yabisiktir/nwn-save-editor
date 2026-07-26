"""Tests for the save-game reader + Save Game Viewer."""

from __future__ import annotations

from pathlib import Path

import pytest

from vaultkeeper.game.save_game import ModuleSaveInfo, SaveGame, scan_save_games


def test_save_game_paths(tmp_path):
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    (folder / "Chapter Three.sav").write_bytes(b"sav")
    (folder / "player.bic").write_bytes(b"bic")
    (folder / "screen.tga").write_bytes(b"tga")
    save = SaveGame(folder=folder)
    assert save.name == "000000 - quicksave"
    assert save.sav_path is not None and save.sav_path.name == "Chapter Three.sav"
    assert save.player_bic is not None
    assert save.screenshot is not None and save.screenshot.name == "screen.tga"


def test_scan_save_games_skips_folders_without_a_sav(tmp_path):
    (tmp_path / "not-a-save").mkdir()  # no .sav inside
    real = tmp_path / "000000 - quicksave"
    real.mkdir()
    (real / "x.sav").write_bytes(b"sav")
    saves = scan_save_games(tmp_path)
    assert [s.name for s in saves] == ["000000 - quicksave"]
    assert scan_save_games(None) == []
    assert scan_save_games(tmp_path / "missing") == []


def test_module_save_info_game_time():
    info = ModuleSaveInfo(year=1372, month=10, day=1, hour=13, minute=5)
    assert info.game_time == "1372/10/01 13:05"
    assert ModuleSaveInfo().game_time == ""  # no year -> unknown


def test_save_game_viewer_lists_and_shows_detail(qtbot, tmp_path):
    from vaultkeeper.ui.dialogs.save_game_viewer import SaveGameViewer

    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    save = SaveGame(folder=folder, location="Aarin's Lodge")
    save.module_info = lambda: ModuleSaveInfo(  # type: ignore[method-assign]
        name="Chapter Three", tag="Chapter3", xp_scale=10,
        year=1372, month=10, day=1, hour=13, minute=0,
        areas=[("a1", "The Maze"), ("a2", "a2")], player_count=1,
    )
    view = SaveGameViewer([save])
    qtbot.addWidget(view)
    assert view._list.count() == 1
    view._list.setCurrentRow(0)

    text = view._detail.toPlainText()
    assert "Chapter Three" in text and "Aarin's Lodge" in text
    assert "1372/10/01 13:00" in text
    # The area contents tree lists each area as a top-level (lazy) node.
    assert view._areas.topLevelItemCount() == 2
    assert view._areas.topLevelItem(0).text(0) == "The Maze  (a1)"
    assert view._areas.topLevelItem(1).text(0) == "a2"  # name == resref -> resref only


def _mk_item(name, base=0):
    from vaultkeeper.core.formats.bic_reader import InventoryItem

    return InventoryItem(
        name=name, base_item=base, tag="", resref="rr", stack_size=1,
        identified=True, stolen=False, description="",
    )


def test_save_viewer_area_contents_tree(qtbot, tmp_path, monkeypatch):
    import vaultkeeper.ui.dialogs.save_game_viewer as sgv
    from vaultkeeper.core.formats.bic_reader import EquippedItem
    from vaultkeeper.game.save_area import (
        AreaContents,
        Container,
        CreatureRef,
        Faction,
        Store,
    )

    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    (folder / "x.sav").write_bytes(b"sav")
    save = SaveGame(folder=folder)
    save.module_info = lambda: ModuleSaveInfo(  # type: ignore[method-assign]
        name="M", areas=[("a1", "Town")]
    )

    area = AreaContents(
        resref="a1", name="Town", tileset="ttu01", width=8, height=8,
        stores=[Store(
            name="Nature Store", tag="NW_S", markup=200, markdown=35,
            items=[_mk_item("Hide Armor +2")],
        )],
        creatures=[CreatureRef(
            name="Guard", tag="g", gold=12,
            equipped=[EquippedItem(16, "Right Hand", _mk_item("Longsword"))],
            carried=[_mk_item("Torch")],
        )],
        containers=[Container(name="Chest", tag="c", items=[_mk_item("Gold Ring")])],
        counts={"placeables": 5},
    )
    monkeypatch.setattr(sgv, "read_area_contents", lambda *a, **k: area)
    monkeypatch.setattr(
        sgv, "read_factions", lambda *a, **k: [Faction(name="Commoner", reputation_to_pc=50)]
    )

    view = sgv.SaveGameViewer([save])
    qtbot.addWidget(view)
    tree = view._areas
    labels = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert labels == ["Town  (a1)", "Factions (1)"]

    area_node = tree.topLevelItem(0)
    area_node.setExpanded(True)  # triggers the lazy .git parse
    groups = [area_node.child(i).text(0) for i in range(area_node.childCount())]
    assert groups == ["Stores (1)", "Creatures (1)", "Containers (1)"]

    # Store -> its stock; selecting it shows the pricing detail.
    store_node = area_node.child(0).child(0)
    assert store_node.text(0) == "Nature Store  (1 items)"
    assert store_node.child(0).text(0) == "Hide Armor +2"
    tree.setCurrentItem(store_node)
    assert "markup: 200%" in view._content_detail.toPlainText()

    # Creature equipment carries a slot prefix.
    creature_node = area_node.child(1).child(0)
    assert creature_node.text(0) == "Guard  (2 items)"
    assert creature_node.child(0).text(0) == "[Right Hand] Longsword"

    # Area node (now loaded) shows its metadata.
    tree.setCurrentItem(area_node)
    assert "Tileset: ttu01" in view._content_detail.toPlainText()

    # Factions node shows the reputation band.
    tree.setCurrentItem(tree.topLevelItem(1))
    faction_text = view._content_detail.toPlainText()
    assert "Commoner" in faction_text and "neutral (50)" in faction_text


# Real saves on the developer's machine (skipped when absent).
_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_module_info_decodes():
    saves = scan_save_games(_SAVES)
    assert saves
    info = next((s.module_info() for s in saves if s.sav_path), None)
    assert info is not None
    assert info.name and info.areas  # module name + at least one named area
