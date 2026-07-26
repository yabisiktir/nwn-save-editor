"""Tests for the save editor (game/save_editor.py) — store settings, save-as-new."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_erf_writer import _make_erf
from vaultkeeper.core.formats.gff import (
    Gff,
    GffField,
    GffList,
    GffStruct,
    GffType,
    write_gff,
)
from vaultkeeper.game.save_area import read_area_contents
from vaultkeeper.game.save_editor import SaveEditError, SaveEditor
from vaultkeeper.game.save_game import SaveGame


def _store_struct(markup=200, markdown=35, gold=-1, black=0):
    return GffStruct(
        struct_type=0xFFFFFFFF,
        fields={
            "MarkUp": GffField(GffType.INT, markup),
            "MarkDown": GffField(GffType.INT, markdown),
            "StoreGold": GffField(GffType.INT, gold),
            "IdentifyPrice": GffField(GffType.INT, 100),
            "MaxBuyPrice": GffField(GffType.INT, -1),
            "BlackMarket": GffField(GffType.BYTE, black),
            "Tag": GffField(GffType.CEXOSTRING, "MYSTORE"),
        },
    )


def _make_save(tmp_path: Path, git_bytes: bytes, name="000000 - test") -> SaveGame:
    folder = tmp_path / name
    folder.mkdir()
    (folder / "x.sav").write_bytes(
        _make_erf([("area1", 2023, git_bytes), ("module", 2014, b"IFO-DATA")])
    )
    (folder / "player.bic").write_bytes(b"BICDATA")
    (folder / "savenfo.txt").write_bytes(b"info")
    return SaveGame(folder=folder)


def _git_with_store(store) -> bytes:
    tree = Gff(
        "GIT ", "V3.2",
        GffStruct(
            struct_type=0xFFFFFFFF,
            fields={"StoreList": GffField(GffType.LIST, GffList([store]))},
        ),
    )
    return write_gff(tree)


def test_edit_store_fields_and_save_as(tmp_path):
    save = _make_save(tmp_path, _git_with_store(_store_struct()))
    editor = SaveEditor(save)
    assert not editor.has_edits
    editor.set_store_fields(
        "area1", 0, markup=120, markdown=50, store_gold=99999, black_market=True
    )
    assert editor.has_edits

    dest = tmp_path / "000001 - edited"
    new_save = editor.save_as(dest)

    # re-read the edited store through the full stack
    area = read_area_contents(new_save.sav_path, "area1")
    store = area.stores[0]
    assert store.markup == 120
    assert store.markdown == 50
    assert store.store_gold == 99999
    assert store.black_market is True
    # untouched resource + sibling files preserved
    assert (dest / "player.bic").read_bytes() == b"BICDATA"
    assert (dest / "savenfo.txt").read_bytes() == b"info"


def test_scalar_edit_is_minimal_diff(tmp_path):
    # A same-size scalar edit changes only that field — the .sav length is unchanged.
    save = _make_save(tmp_path, _git_with_store(_store_struct(markup=200)))
    editor = SaveEditor(save)
    editor.set_store_fields("area1", 0, markup=150)
    dest = tmp_path / "000001 - edited"
    new_save = editor.save_as(dest)
    assert new_save.sav_path.stat().st_size == save.sav_path.stat().st_size


def test_none_values_are_ignored(tmp_path):
    save = _make_save(tmp_path, _git_with_store(_store_struct(markup=200, markdown=35)))
    editor = SaveEditor(save)
    editor.set_store_fields("area1", 0, markup=None, markdown=99)
    assert editor.has_edits
    new_save = editor.save_as(tmp_path / "out")
    store = read_area_contents(new_save.sav_path, "area1").stores[0]
    assert store.markup == 200 and store.markdown == 99


def test_save_as_refuses_existing_destination(tmp_path):
    save = _make_save(tmp_path, _git_with_store(_store_struct()))
    editor = SaveEditor(save)
    editor.set_store_fields("area1", 0, markup=1)
    (tmp_path / "exists").mkdir()
    with pytest.raises(SaveEditError, match="already exists"):
        editor.save_as(tmp_path / "exists")


def test_save_as_without_edits_errors(tmp_path):
    save = _make_save(tmp_path, _git_with_store(_store_struct()))
    with pytest.raises(SaveEditError, match="no edits"):
        SaveEditor(save).save_as(tmp_path / "out")


def test_unknown_field_and_bad_index_error(tmp_path):
    save = _make_save(tmp_path, _git_with_store(_store_struct()))
    editor = SaveEditor(save)
    with pytest.raises(SaveEditError, match="unknown store field"):
        editor.set_store_fields("area1", 0, bogus=1)
    with pytest.raises(SaveEditError, match="out of range"):
        editor.set_store_fields("area1", 5, markup=1)
    with pytest.raises(SaveEditError, match="not in this save"):
        editor.set_store_fields("no_such_area", 0, markup=1)


def test_failed_save_leaves_no_partial_folder(tmp_path, monkeypatch):
    save = _make_save(tmp_path, _git_with_store(_store_struct()))
    editor = SaveEditor(save)
    editor.set_store_fields("area1", 0, markup=1)
    # force verification to fail; the half-written folder must be cleaned up
    monkeypatch.setattr(editor, "_verify", lambda _s: (_ for _ in ()).throw(SaveEditError("boom")))
    dest = tmp_path / "000001 - edited"
    with pytest.raises(SaveEditError):
        editor.save_as(dest)
    assert not dest.exists()


# -- real save (skipped when absent) ----------------------------------------- #
_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_store_edit_roundtrips(tmp_path):
    from vaultkeeper.game.save_game import scan_save_games

    hit = None
    for save in scan_save_games(_SAVES):
        if save.sav_path is None:
            continue
        info = save.module_info()
        for resref, _name in (info.areas if info else []):
            area = read_area_contents(save.sav_path, resref)
            if area and area.stores:
                hit = (save, resref, area.stores[0])
                break
        if hit:
            break
    if hit is None:
        pytest.skip("no save with a store found")

    save, area_resref, before = hit
    editor = SaveEditor(save)
    editor.set_store_fields(area_resref, 0, markup=before.markup + 7)
    new_save = editor.save_as(tmp_path / "edited")
    after = read_area_contents(new_save.sav_path, area_resref).stores[0]
    assert after.markup == before.markup + 7  # edit landed + verified
    assert len(after.items) == len(before.items)  # stock preserved
