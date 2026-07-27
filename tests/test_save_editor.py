"""Tests for the save editor (game/save_editor.py) — store settings, save-as-new."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_erf_writer import _make_erf
from vaultkeeper.core.formats.erf_reader import ErfReader
from vaultkeeper.core.formats.gff import (
    Gff,
    GffField,
    GffList,
    GffStruct,
    GffType,
    LocString,
    read_gff,
    write_gff,
)
from vaultkeeper.game.item_properties import editable_magnitude, is_cast_spell
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


def test_overwrite_in_place_with_backup(tmp_path):
    # editing a save and overwriting it: the same folder ends up edited, and the
    # original is preserved (timestamped) in the backup dir.
    save = _make_save(tmp_path, _git_with_store(_store_struct(markup=200)))
    editor = SaveEditor(save)
    editor.set_store_fields("area1", 0, markup=150)
    backup_dir = tmp_path / "backups"
    editor.save_as(save.folder, overwrite=True, backup_dir=backup_dir)

    assert read_area_contents(save.sav_path, "area1").stores[0].markup == 150  # in place
    backups = list(backup_dir.iterdir())
    assert len(backups) == 1
    backed = SaveGame(folder=backups[0])
    assert read_area_contents(backed.sav_path, "area1").stores[0].markup == 200  # original
    # siblings survived + no staging left behind
    assert (save.folder / "player.bic").is_file()
    assert not any(p.name.endswith(".vk-staging") for p in save.folder.parent.iterdir())


def test_overwrite_without_backup_deletes_old(tmp_path):
    save = _make_save(tmp_path, _git_with_store(_store_struct(markup=200)))
    editor = SaveEditor(save)
    editor.set_store_fields("area1", 0, markup=150)
    editor.save_as(save.folder, overwrite=True)  # no backup_dir
    assert read_area_contents(save.sav_path, "area1").stores[0].markup == 150
    assert not (tmp_path / "backups").exists()


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


# --------------------------------------------------------------------------- #
# player-item property editing
# --------------------------------------------------------------------------- #
def _loc(text: str) -> GffField:
    return GffField(GffType.CEXOLOCSTRING, LocString(strref=-1, substrings=[(0, text)]))


def _prop(pid: int, subtype: int, cost: int, uses: int = 255) -> GffStruct:
    return GffStruct(struct_type=0, fields={
        "PropertyName": GffField(GffType.WORD, pid),
        "Subtype": GffField(GffType.WORD, subtype),
        "CostTable": GffField(GffType.BYTE, 1),
        "CostValue": GffField(GffType.WORD, cost),
        "Param1": GffField(GffType.BYTE, 255),
        "Param1Value": GffField(GffType.BYTE, 0),
        "ChanceAppear": GffField(GffType.BYTE, 100),
        "UsesPerDay": GffField(GffType.BYTE, uses),
        "Useable": GffField(GffType.BYTE, 1),
    })


def _item(name: str, slot: int, props: list[GffStruct], oid: int = 100) -> GffStruct:
    return GffStruct(struct_type=slot, fields={
        "ObjectId": GffField(GffType.DWORD, oid),
        "LocalizedName": _loc(name),
        "TemplateResRef": GffField(GffType.CRESREF, name.lower()),
        "BaseItem": GffField(GffType.INT, 16),
        "PropertiesList": GffField(GffType.LIST, GffList(props)),
    })


def _character() -> GffStruct:
    """A fresh player character: a helm (Ability Bonus Str +2, Cast Spell) + a bag."""
    helm = _item("Helm", 1, [_prop(0, 0, 2), _prop(15, 100, 3, uses=1)], oid=100)
    bag = GffStruct(struct_type=0, fields={
        "ObjectId": GffField(GffType.DWORD, 101),
        "LocalizedName": _loc("Bag"),
        "TemplateResRef": GffField(GffType.CRESREF, "bag"),
        "BaseItem": GffField(GffType.INT, 60),
        "ItemList": GffField(GffType.LIST, GffList([_item("Ring", 0, [_prop(1, 0, 4)], oid=102)])),
    })
    skills = [
        GffStruct(struct_type=0, fields={"Rank": GffField(GffType.BYTE, r)})
        for r in (0, 2, 5, 43, 0)  # id 3 == Discipline
    ]
    feats = [  # ids 1, 2 are base; 9000 is a PRC-range id
        GffStruct(struct_type=1, fields={"Feat": GffField(GffType.WORD, fid)})
        for fid in (1, 2, 9000)
    ]

    def _spell(sid):
        return GffStruct(struct_type=3, fields={"Spell": GffField(GffType.WORD, sid)})

    classes = [
        GffStruct(struct_type=2, fields={  # Bard (base caster)
            "Class": GffField(GffType.INT, 1),
            "ClassLevel": GffField(GffType.SHORT, 8),
            "KnownList0": GffField(GffType.LIST, GffList([_spell(100), _spell(101)])),
            "KnownList1": GffField(GffType.LIST, GffList([])),  # empty level
        }),
        GffStruct(struct_type=2, fields={  # a PRC class id
            "Class": GffField(GffType.INT, 500),
            "ClassLevel": GffField(GffType.SHORT, 5),
            "KnownList0": GffField(GffType.LIST, GffList([_spell(200)])),
        }),
    ]
    return GffStruct(struct_type=0xFFFFFFFF, fields={
        "FirstName": _loc("Hero"),
        "Equip_ItemList": GffField(GffType.LIST, GffList([helm])),
        "ItemList": GffField(GffType.LIST, GffList([bag])),
        "SkillList": GffField(GffType.LIST, GffList(skills)),
        "FeatList": GffField(GffType.LIST, GffList(feats)),
        "ClassList": GffField(GffType.LIST, GffList(classes)),
    })


def _make_char_save(tmp_path: Path, name="000000 - test") -> SaveGame:
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(GffType.LIST, GffList([_character()])),
    }))
    bic = Gff("BIC ", "V3.2", _character())  # a separate, identical mirror
    folder = tmp_path / name
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([("module", 2014, write_gff(ifo))]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    return SaveGame(folder=folder)


def _cost_at(root, path, prop_index):
    struct = root
    for label, index in path:
        struct = struct.fields[label].value.structs[index]
    return struct.fields["PropertiesList"].value.structs[prop_index].fields["CostValue"].value


def _ifo_char(sav_path):
    """The player character struct from a save's module.ifo Mod_PlayerList[0]."""
    er = ErfReader()
    res = er.find_resource(sav_path, "module", res_type=2014)
    ifo = read_gff(er.read_resource_bytes(sav_path, res))
    return ifo.root.fields["Mod_PlayerList"].value.structs[0]


def test_player_items_walks_equipped_carried_and_bags(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    items = editor.player_items()
    names = {it.name for it in items}
    assert {"Helm", "Bag", "Ring"} <= names
    helm = next(it for it in items if it.name == "Helm")
    assert helm.slot == 1 and helm.path == (("Equip_ItemList", 0),)
    ring = next(it for it in items if it.name == "Ring")
    assert ring.slot is None and ring.path == (("ItemList", 0), ("ItemList", 0))  # in the bag


def test_edit_property_magnitude_syncs_ifo_and_bic(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    helm = next(it for it in editor.player_items() if it.name == "Helm")
    ability = helm.properties[0]
    assert editable_magnitude(ability.prop) and ability.prop.cost_value == 2
    editor.set_property_cost(
        helm.path, 0, cost_value=8, where="Helm", prop_label="Ability Bonus: Str"
    )
    assert editor.has_edits
    assert "Ability Bonus: Str" in editor.pending_changes()[0].summary

    new_save = editor.save_as(tmp_path / "out")
    assert _cost_at(_ifo_char(new_save.sav_path), helm.path, 0) == 8
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert _cost_at(bic.root, helm.path, 0) == 8  # mirror kept in sync
    assert _cost_at(_ifo_char(save.sav_path), helm.path, 0) == 2  # original untouched


def test_edit_property_in_a_bag(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    ring = next(it for it in editor.player_items() if it.name == "Ring")
    editor.set_property_cost(ring.path, 0, cost_value=9, where="Ring", prop_label="AC Bonus")
    new_save = editor.save_as(editor._save.folder.parent / "out")
    assert _cost_at(_ifo_char(new_save.sav_path), ring.path, 0) == 9


def test_reverting_property_removes_pending(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    helm = next(it for it in editor.player_items() if it.name == "Helm")
    editor.set_property_cost(helm.path, 0, cost_value=8, prop_label="x")
    assert editor.has_edits
    editor.set_property_cost(helm.path, 0, cost_value=2, prop_label="x")  # back to original
    assert not editor.has_edits


def test_cast_spell_property_is_uses_editable_not_magnitude(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    helm = next(it for it in editor.player_items() if it.name == "Helm")
    cast = helm.properties[1]
    assert is_cast_spell(cast.prop) and not editable_magnitude(cast.prop)
    editor.set_property_cost(
        helm.path, 1, uses_per_day=5, where="Helm", prop_label="Cast Spell"
    )
    new_save = editor.save_as(tmp_path / "out")
    item = _ifo_char(new_save.sav_path).fields["Equip_ItemList"].value.structs[0]
    assert item.fields["PropertiesList"].value.structs[1].fields["UsesPerDay"].value == 5


def test_bad_path_and_index_raise(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    with pytest.raises(SaveEditError, match="does not resolve"):
        editor.set_property_cost((("Equip_ItemList", 9),), 0, cost_value=1)
    with pytest.raises(SaveEditError, match="out of range"):
        editor.set_property_cost((("Equip_ItemList", 0),), 9, cost_value=1)


def test_add_item_copy_appends_clone_with_fresh_id(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    bag = next(it for it in editor.player_items() if it.name == "Bag")
    editor.add_item_copy(bag.path, where="Bag")
    assert editor.has_edits
    assert "added a copy" in editor.pending_changes()[0].summary

    new_save = editor.save_as(tmp_path / "out")
    carried = _ifo_char(new_save.sav_path).fields["ItemList"].value.structs
    assert len(carried) == 2  # original bag + its clone
    clone = carried[-1]
    assert clone.struct_type == 0 and clone.fields["TemplateResRef"].value == "bag"
    assert clone.fields["ObjectId"].value == 103  # max existing (102) + 1
    # player.bic mirror also grew
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert len(bic.root.fields["ItemList"].value.structs) == 2
    # original save untouched
    assert len(_ifo_char(save.sav_path).fields["ItemList"].value.structs) == 1


def test_edit_skill_rank_syncs_ifo_and_bic(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    skills = editor.player_skills()
    assert len(skills) == 5
    discipline = skills[3]
    assert discipline.name == "Discipline" and discipline.rank == 43
    editor.set_skill_rank(3, 48, where=discipline.name)
    assert editor.has_edits and "43→48" in editor.pending_changes()[0].summary

    new_save = editor.save_as(tmp_path / "out")
    char = _ifo_char(new_save.sav_path)
    assert char.fields["SkillList"].value.structs[3].fields["Rank"].value == 48
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert bic.root.fields["SkillList"].value.structs[3].fields["Rank"].value == 48
    assert _ifo_char(save.sav_path).fields["SkillList"].value.structs[3].fields["Rank"].value == 43


def test_reverting_skill_removes_pending(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    editor.set_skill_rank(3, 48)
    assert editor.has_edits
    editor.set_skill_rank(3, 43)  # back to original
    assert not editor.has_edits


def _feat_ids(char) -> set[int]:
    return {s.fields["Feat"].value for s in char.fields["FeatList"].value.structs}


def test_player_feats_flags_base_vs_prc(tmp_path):
    feats = SaveEditor(_make_char_save(tmp_path)).player_feats()
    by_id = {fid: is_base for fid, _name, is_base in feats}
    assert by_id[1] is True and by_id[2] is True  # base
    assert by_id[9000] is False  # PRC-range id


def test_add_and_remove_feat_syncs_ifo_and_bic(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    editor.add_feat(5)  # a base feat not present
    editor.remove_feat(1)  # a base feat present
    summaries = {c.where: c.summary for c in editor.pending_changes()}
    assert any("add feat" in s for s in summaries.values())
    assert any("remove feat" in s for s in summaries.values())

    new_save = editor.save_as(tmp_path / "out")
    ids = _feat_ids(_ifo_char(new_save.sav_path))
    assert 5 in ids and 1 not in ids
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    bic_ids = {s.fields["Feat"].value for s in bic.root.fields["FeatList"].value.structs}
    assert 5 in bic_ids and 1 not in bic_ids
    assert 1 in _feat_ids(_ifo_char(save.sav_path))  # original untouched


def test_add_then_remove_feat_nets_to_nothing(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    editor.add_feat(5)
    assert editor.has_edits
    editor.remove_feat(5)  # back to original set
    assert not editor.has_edits


def test_prc_feat_change_is_flagged(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    editor.remove_feat(9000)  # a PRC feat
    assert "PRC" in editor.pending_changes()[0].summary


def _kl(char, class_index, field):
    structs = char.fields["ClassList"].value.structs[class_index].fields[field].value.structs
    return {s.fields["Spell"].value for s in structs}


def test_player_spellbook_lists_caster_classes(tmp_path):
    book = SaveEditor(_make_char_save(tmp_path)).player_spellbook()
    bard = next(b for b in book if b.class_id == 1)
    assert bard.is_base
    assert {sl.list_field for sl in bard.lists} == {"KnownList0", "KnownList1"}
    prc = next(b for b in book if b.class_id == 500)
    assert not prc.is_base


def test_add_and_remove_spell_syncs_ifo_and_bic(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    bard = next(b for b in editor.player_spellbook() if b.class_id == 1)
    editor.add_spell(bard.class_index, "KnownList0", 300)
    editor.remove_spell(bard.class_index, "KnownList0", 100)
    new_save = editor.save_as(tmp_path / "out")
    ids = _kl(_ifo_char(new_save.sav_path), bard.class_index, "KnownList0")
    assert 300 in ids and 100 not in ids
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert 300 in _kl(bic.root, bard.class_index, "KnownList0")
    assert 100 in _kl(_ifo_char(save.sav_path), bard.class_index, "KnownList0")  # original


def test_add_then_remove_spell_nets_to_nothing(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    bard = next(b for b in editor.player_spellbook() if b.class_id == 1)
    editor.add_spell(bard.class_index, "KnownList0", 300)
    assert editor.has_edits
    editor.remove_spell(bard.class_index, "KnownList0", 300)
    assert not editor.has_edits


def test_add_spell_to_empty_level_uses_minimal_struct(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    bard = next(b for b in editor.player_spellbook() if b.class_id == 1)
    editor.add_spell(bard.class_index, "KnownList1", 50)  # was empty
    new_save = editor.save_as(editor._save.folder.parent / "out")
    kl1 = _ifo_char(new_save.sav_path).fields["ClassList"].value.structs[
        bard.class_index].fields["KnownList1"].value.structs
    assert len(kl1) == 1 and kl1[0].fields["Spell"].value == 50 and kl1[0].struct_type == 3


def test_add_item_copy_is_independent(tmp_path):
    # editing the clone in the tree must not alter the source item
    editor = SaveEditor(_make_char_save(tmp_path))
    bag = next(it for it in editor.player_items() if it.name == "Bag")
    editor.add_item_copy(bag.path, where="Bag")
    carried = editor._item_struct(editor._module_tree(), ()).fields  # player struct
    items = carried["ItemList"].value.structs
    items[-1].fields["BaseItem"].value = 999  # mutate the clone
    assert items[0].fields["BaseItem"].value != 999  # source unchanged


def _make_char_save_with_git(tmp_path, name="000000 - test") -> SaveGame:
    """A save whose .sav also holds an area .git with a store item to clone."""
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(GffType.LIST, GffList([_character()])),
    }))
    # a .git: a store whose single panel holds one item (resref "shopsword").
    store_item = GffStruct(struct_type=0, fields={
        "BaseItem": GffField(GffType.INT, 3),
        "TemplateResRef": GffField(GffType.CRESREF, "shopsword"),
        "LocalizedName": _loc("Shop Sword"),
        "ObjectId": GffField(GffType.DWORD, 55),
        "PropertiesList": GffField(GffType.LIST, GffList([_prop(6, 0, 5)])),
    })
    store = GffStruct(struct_type=0, fields={
        "Tag": GffField(GffType.CEXOSTRING, "SHOP"),
        "StoreList": GffField(GffType.LIST, GffList([
            GffStruct(struct_type=0, fields={
                "ItemList": GffField(GffType.LIST, GffList([store_item])),
            }),
        ])),
    })
    git = Gff("GIT ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "StoreList": GffField(GffType.LIST, GffList([store])),
    }))
    bic = Gff("BIC ", "V3.2", _character())
    folder = tmp_path / name
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([
        ("module", 2014, write_gff(ifo)), ("area1", 2023, write_gff(git)),
    ]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    return SaveGame(folder=folder)


def test_clone_store_item_into_inventory(tmp_path):
    save = _make_char_save_with_git(tmp_path)
    editor = SaveEditor(save)
    editor.add_item_from_area("area1", "shopsword", where="Shop Sword")
    assert "from area1" in editor.pending_changes()[0].summary

    new_save = editor.save_as(tmp_path / "out")
    carried = _ifo_char(new_save.sav_path).fields["ItemList"].value.structs
    clone = carried[-1]
    assert clone.fields["TemplateResRef"].value == "shopsword"
    assert clone.struct_type == 0  # a carried item now
    assert len(clone.fields["PropertiesList"].value.structs) == 1  # kept its property
    # the source area .git was only read, never modified
    er = ErfReader()

    def git(sav):
        return er.read_resource_bytes(sav, er.find_resource(sav, "area1", res_type=2023))

    assert git(save.sav_path) == git(new_save.sav_path)


def test_clone_missing_resref_errors(tmp_path):
    editor = SaveEditor(_make_char_save_with_git(tmp_path))
    with pytest.raises(SaveEditError, match="could not find"):
        editor.add_item_from_area("area1", "no_such_item")


def _helm_props(char):
    helm = char.fields["Equip_ItemList"].value.structs[0]
    return helm.fields["PropertiesList"].value.structs


def _make_char_save_with_details(tmp_path, name="000000 - test"):
    char = _character()
    char.fields["Gold"] = GffField(GffType.DWORD, 100)
    char.fields["Str"] = GffField(GffType.BYTE, 12)
    char.fields["GoodEvil"] = GffField(GffType.BYTE, 50)
    char.fields["Appearance_Type"] = GffField(GffType.WORD, 6)
    char.fields["Portrait"] = GffField(GffType.CRESREF, "po_hu_m_11_")
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(GffType.LIST, GffList([char])),
    }))
    bic_char = _character()
    bic_char.fields["Gold"] = GffField(GffType.DWORD, 100)
    bic_char.fields["Str"] = GffField(GffType.BYTE, 12)
    bic_char.fields["Appearance_Type"] = GffField(GffType.WORD, 6)
    bic_char.fields["Portrait"] = GffField(GffType.CRESREF, "po_hu_m_11_")
    bic = Gff("BIC ", "V3.2", bic_char)
    folder = tmp_path / name
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([("module", 2014, write_gff(ifo))]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    return SaveGame(folder=folder)


def test_player_fields_lists_editable_character_fields(tmp_path):
    editor = SaveEditor(_make_char_save_with_details(tmp_path))
    fields = {f.field: f for f in editor.player_fields()}
    assert fields["Gold"].value == 100 and fields["Gold"].kind == "int"
    assert fields["Str"].value == 12
    assert fields["FirstName"].kind == "name" and fields["FirstName"].value == "Hero"


def test_set_character_field_and_name_sync(tmp_path):
    save = _make_char_save_with_details(tmp_path)
    editor = SaveEditor(save)
    editor.set_character_field("Gold", 5000, where="Gold")
    editor.set_character_field("Str", 20, where="Strength")
    editor.set_character_name("FirstName", "Renamed", where="First name")
    assert any("100→5000" in c.summary for c in editor.pending_changes())

    new_save = editor.save_as(tmp_path / "out")
    char = _ifo_char(new_save.sav_path)
    assert char.fields["Gold"].value == 5000 and char.fields["Str"].value == 20
    assert char.fields["FirstName"].value.text() == "Renamed"
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert bic.root.fields["Gold"].value == 5000  # mirror synced
    assert _ifo_char(save.sav_path).fields["Gold"].value == 100  # original untouched


def test_char_field_revert_removes_pending(tmp_path):
    editor = SaveEditor(_make_char_save_with_details(tmp_path))
    editor.set_character_field("Str", 30)
    assert editor.has_edits
    editor.set_character_field("Str", 12)  # back to original
    assert not editor.has_edits


def test_appearance_and_portrait_editable(tmp_path):
    save = _make_char_save_with_details(tmp_path)
    fields = {f.field: f for f in SaveEditor(save).player_fields()}
    assert fields["Appearance_Type"].kind == "appearance" and fields["Appearance_Type"].value == 6
    assert fields["Portrait"].kind == "resref" and fields["Portrait"].value == "po_hu_m_11_"

    editor = SaveEditor(save)
    editor.set_character_field("Appearance_Type", 1, where="Appearance")  # Elf
    editor.set_character_resref("Portrait", "po_el_f_02_", where="Portrait")
    new_save = editor.save_as(tmp_path / "out")
    char = _ifo_char(new_save.sav_path)
    assert char.fields["Appearance_Type"].value == 1
    assert char.fields["Portrait"].value == "po_el_f_02_"
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert bic.root.fields["Portrait"].value == "po_el_f_02_"  # mirror synced


def test_set_property_changes_subtype_and_cost(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    helm = next(it for it in editor.player_items() if it.slot == 1)
    editor.set_property(
        helm.path, 0, subtype=2, cost_value=7, where="Helm", label="Ability Bonus: Con +7",
    )
    assert "Ability Bonus: Con +7" in editor.pending_changes()[0].summary
    new_save = editor.save_as(tmp_path / "out")
    prop = _helm_props(_ifo_char(new_save.sav_path))[0]
    assert prop.fields["Subtype"].value == 2 and prop.fields["CostValue"].value == 7
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert _helm_props(bic.root)[0].fields["Subtype"].value == 2  # mirror synced


def test_set_property_revert_removes_pending(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    helm = next(it for it in editor.player_items() if it.slot == 1)
    original = helm.properties[0].prop  # Ability Bonus, subtype 0, cost 2
    editor.set_property(helm.path, 0, subtype=5, cost_value=9)
    assert editor.has_edits
    editor.set_property(helm.path, 0, subtype=original.subtype, cost_value=original.cost_value)
    assert not editor.has_edits  # back to original -> no pending change


def test_add_item_property_syncs_ifo_and_bic(tmp_path):
    save = _make_char_save(tmp_path)
    editor = SaveEditor(save)
    helm = next(it for it in editor.player_items() if it.slot == 1)
    before = len(helm.properties)
    editor.add_item_property(
        helm.path, property_name=1, subtype=0, cost_value=5, cost_table=2,
        where="Helm", label="AC Bonus +5",
    )
    assert "add AC Bonus +5" in editor.pending_changes()[0].summary

    new_save = editor.save_as(tmp_path / "out")
    props = _helm_props(_ifo_char(new_save.sav_path))
    assert len(props) == before + 1
    added = props[-1]
    assert added.fields["PropertyName"].value == 1 and added.fields["CostValue"].value == 5
    assert added.struct_type == len(props) - 1  # struct_type == list index
    bic = read_gff((new_save.folder / "player.bic").read_bytes())
    assert len(_helm_props(bic.root)) == before + 1  # mirror synced


def test_remove_item_property_reindexes(tmp_path):
    editor = SaveEditor(_make_char_save(tmp_path))
    helm = next(it for it in editor.player_items() if it.slot == 1)
    before = len(helm.properties)
    editor.remove_item_property(helm.path, 0, where="Helm", label="first prop")
    new_save = editor.save_as(editor._save.folder.parent / "out")
    props = _helm_props(_ifo_char(new_save.sav_path))
    assert len(props) == before - 1
    assert [p.struct_type for p in props] == list(range(len(props)))  # re-indexed


def test_addable_properties_have_valid_shapes():
    from vaultkeeper.game.item_properties import addable_properties

    templates = addable_properties()
    assert any(t.label == "Ability Bonus" and t.subtypes for t in templates)  # subtype
    assert any(t.label == "Haste" and t.magnitude is None for t in templates)  # flag
    assert any(t.label == "AC Bonus" and t.magnitude and not t.subtypes for t in templates)
