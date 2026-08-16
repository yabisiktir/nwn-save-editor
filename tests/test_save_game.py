"""Reading an NWN save game: its files, and the module state inside the .sav."""

from __future__ import annotations

from pathlib import Path

import pytest

from nwnsaveeditor.save_game import ModuleSaveInfo, SaveGame, scan_save_games

_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"


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


def _mk_item(name, base=0):
    from nwnfile.formats.bic_reader import InventoryItem

    return InventoryItem(
        name=name, base_item=base, tag="", resref="rr", stack_size=1,
        identified=True, stolen=False, description="",
    )


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_module_info_decodes():
    saves = scan_save_games(_SAVES)
    if not saves:
        pytest.skip("the real saves folder holds no saves")
    info = next((s.module_info() for s in saves if s.sav_path), None)
    assert info is not None
    assert info.name and info.areas  # module name + at least one named area
