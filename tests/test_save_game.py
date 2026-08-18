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


def _sav_with_areas(folder: Path, area_count: int = 3) -> None:
    """Write a .sav whose module.ifo lists (and names) ``area_count`` areas."""
    import struct

    from nwnfile.formats.gff import (
        Gff,
        GffField,
        GffList,
        GffStruct,
        GffType,
        LocString,
        write_gff,
    )

    names = [f"area{i:02d}" for i in range(area_count)]
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_Name": GffField(
            GffType.CEXOLOCSTRING, LocString(substrings=[(0, "Test Module")])
        ),
        "Mod_Area_list": GffField(GffType.LIST, GffList([
            GffStruct(struct_type=6, fields={
                "Area_Name": GffField(GffType.CRESREF, name),
            }) for name in names
        ])),
    }))
    resources = [("module", 2014, write_gff(ifo))]
    for name in names:
        are = Gff("ARE ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
            "Name": GffField(
                GffType.CEXOLOCSTRING,
                LocString(substrings=[(0, f"The {name} Room")]),
            ),
        }))
        resources.append((name, 2012, write_gff(are)))

    entry_count = len(resources)
    keys_offset = 160
    res_offset = keys_offset + entry_count * 24
    cursor = res_offset + entry_count * 8
    header = b"SAV " + b"V1.0" + struct.pack(
        "<9i", 0, 0, entry_count, 160, keys_offset, res_offset, 0, 0, -1
    ) + b"\x00" * 116
    keys = reslist = data = b""
    for i, (ref, rtype, blob) in enumerate(resources):
        keys += ref.encode().ljust(16, b"\x00") + struct.pack("<iH", i, rtype) + b"\x00\x00"
        reslist += struct.pack("<Ii", cursor, len(blob))
        data += blob
        cursor += len(blob)
    (folder / "x.sav").write_bytes(header + keys + reslist + data)


def test_module_info_can_skip_area_names(tmp_path):
    """Naming areas costs a lookup each; a caller wanting only the module's own
    fields (the Open dialog) can decline to pay for it."""
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    _sav_with_areas(folder)
    save = SaveGame(folder=folder)

    full = save.module_info()
    assert full.name == "Test Module"
    assert [name for _resref, name in full.areas] == [
        "The area00 Room", "The area01 Room", "The area02 Room"
    ]

    lean = SaveGame(folder=folder).module_info(read_area_names=False)
    assert lean.name == "Test Module"  # what the Open dialog shows, still there
    # The areas are still listed, they are just not named.
    assert [resref for resref, _name in lean.areas] == ["area00", "area01", "area02"]
    assert [name for _resref, name in lean.areas] == ["area00", "area01", "area02"]


def test_module_info_is_memoized_until_the_sav_changes(tmp_path):
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    _sav_with_areas(folder)
    save = SaveGame(folder=folder)

    first = save.module_info()
    assert save.module_info() is first  # re-read costs nothing

    # A name-only read is answered from the fuller entry rather than re-reading.
    assert save.module_info(read_area_names=False) is first

    import os

    _sav_with_areas(folder, area_count=1)
    stat = save.sav_path.stat()
    os.utime(save.sav_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))

    again = save.module_info()
    assert again is not first and len(again.areas) == 1


def test_a_name_only_read_does_not_satisfy_a_later_full_one(tmp_path):
    """The memo must not answer a caller wanting area names with an entry that
    was read without them."""
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    _sav_with_areas(folder)
    save = SaveGame(folder=folder)

    lean = save.module_info(read_area_names=False)
    assert [name for _r, name in lean.areas] == ["area00", "area01", "area02"]

    full = save.module_info()
    assert full is not lean
    assert [name for _r, name in full.areas] == [
        "The area00 Room", "The area01 Room", "The area02 Room"
    ]


def test_the_memo_does_not_change_a_saves_identity(tmp_path):
    """The cache slot is bookkeeping, not part of what a save *is* — two saves
    for the same folder stay equal once one of them has read its module."""
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    _sav_with_areas(folder)

    one, two = SaveGame(folder=folder), SaveGame(folder=folder)
    assert one == two
    one.module_info()  # populates the memo on `one` only
    assert one == two, "reading a save must not make it unequal to its twin"
    assert "_info_cache" not in repr(one)


def test_module_info_without_a_sav_is_none(tmp_path):
    folder = tmp_path / "000000 - empty"
    folder.mkdir()
    save = SaveGame(folder=folder)
    assert save.sav_path is None
    assert save.module_info() is None
    assert save.module_info(read_area_names=False) is None


def test_an_undecodable_sav_is_none_and_recovers_when_repaired(tmp_path):
    """A corrupt save memoizes its failure without raising, and is re-read if the
    file on disk is later replaced with a good one."""
    folder = tmp_path / "000000 - quicksave"
    folder.mkdir()
    (folder / "x.sav").write_bytes(b"not an ERF at all")
    save = SaveGame(folder=folder)

    assert save.module_info() is None
    assert save.module_info() is None  # memoized failure, still no exception

    _sav_with_areas(folder)
    _bump_sav_mtime(save)
    info = save.module_info()
    assert info is not None and info.name == "Test Module"


def _bump_sav_mtime(save: SaveGame) -> None:
    """Ensure a rewritten .sav is unambiguously newer than the memoized read."""
    import os

    stat = save.sav_path.stat()
    os.utime(save.sav_path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
