"""The generic "Recompute PRC Features" widget + the top-hak primitive."""

from __future__ import annotations

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.gff import (
    Gff,
    GffField,
    GffList,
    GffStruct,
    GffType,
    LocString,
    write_gff,
)
from nwnsaveeditor import prc_recompute
from nwnsaveeditor.save_editor import SaveEditor
from nwnsaveeditor.save_game import SaveGame
from tests.test_erf_writer import _make_erf


def _loc(text: str) -> GffField:
    return GffField(GffType.CEXOLOCSTRING, LocString(strref=-1, substrings=[(0, text)]))


def _donor_item(object_id: int = 100) -> GffStruct:
    """A minimal, valid carried item — the recompute widget is modelled on this."""
    return GffStruct(struct_type=0, fields={
        "ObjectId": GffField(GffType.DWORD, object_id),
        "BaseItem": GffField(GffType.INT, 77),  # a gem
        "Tag": GffField(GffType.CEXOSTRING, "nw_it_gem005"),
        "TemplateResRef": GffField(GffType.CRESREF, "nw_it_gem005"),
        "LocalizedName": _loc("Gem"),
        "StackSize": GffField(GffType.WORD, 1),
        "Identified": GffField(GffType.BYTE, 1),
        "ModelPart1": GffField(GffType.BYTE, 5),
        "VarTable": GffField(GffType.LIST, GffList([
            GffStruct(struct_type=0, fields={
                "Name": GffField(GffType.CEXOSTRING, "somevar"),
                "Value": GffField(GffType.INT, 7),
            }),
        ])),
        "PropertiesList": GffField(GffType.LIST, GffList([])),
    })


def _character() -> GffStruct:
    return GffStruct(struct_type=0xFFFFFFFF, fields={
        "FeatList": GffField(GffType.LIST, GffList([])),  # marks a player struct
        "Equip_ItemList": GffField(GffType.LIST, GffList([])),
        "ItemList": GffField(GffType.LIST, GffList([_donor_item()])),
    })


def _save(tmp_path) -> SaveGame:
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(GffType.LIST, GffList([_character()])),
        "Mod_HakList": GffField(GffType.LIST, GffList([
            GffStruct(struct_type=8, fields={"Mod_Hak": GffField(GffType.CEXOSTRING, "prc8")}),
        ])),
    }))
    bic = Gff("BIC ", "V3.2", _character())
    folder = tmp_path / "000000 - prc"
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([("module", 2014, write_gff(ifo))]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    return SaveGame(folder=folder)


def _player(ed):
    return ed._player_struct(ed._module_tree())


def _carried(ed):
    return _player(ed).fields["ItemList"].value.structs


def _recompute_item(ed):
    return next((it for it in _carried(ed) if (it.get("Tag") or "") == "prc_recompute"), None)


def _hak_names(ed):
    return [s.get("Mod_Hak") for s in
            ed._module_tree().root.fields["Mod_HakList"].value.structs]


# -- the recompute widget item (SaveEditor.add_recompute_item) -------------- #
def test_add_recompute_item_builds_the_unique_power_widget(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_recompute_item()
    item = _recompute_item(ed)
    assert item is not None
    assert item.get("BaseItem") == 24  # Miscellaneous widget
    assert item.get("TemplateResRef") == "prc_recompute"
    assert item.fields["LocalizedName"].value.text() == "Recompute PRC Features"
    props = item.fields["PropertiesList"].value.structs
    assert len(props) == 1
    p = props[0]
    assert (p.get("PropertyName"), p.get("Subtype")) == (15, 335)  # Cast Spell / Unique Power Self
    assert (p.get("CostTable"), p.get("CostValue")) == (3, 13)  # unlimited uses
    assert "VarTable" not in item.fields  # donor's local vars were not inherited


def test_add_recompute_item_writes_both_trees(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_recompute_item()
    for tree in ed._targets():
        items = ed._player_struct(tree).fields["ItemList"].value.structs
        assert any((it.get("Tag") or "") == "prc_recompute" for it in items)


# -- the top-hak primitive (SaveEditor.prepend_module_hak) ------------------ #
def test_prepend_module_hak_puts_it_first_and_dedupes(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    assert _hak_names(ed) == ["prc8"]
    ed.prepend_module_hak("vktop")
    assert _hak_names(ed) == ["vktop", "prc8"]  # inserted at the top
    ed.prepend_module_hak("vktop")  # again -> moved to top, not duplicated
    assert _hak_names(ed) == ["vktop", "prc8"]


# -- add_widget (hak + item + manifest) ------------------------------------ #
def test_the_widget_script_is_bundled_with_the_app():
    assert prc_recompute.script_bytes() not in (None, b"")


def test_add_widget_installs_the_hak_and_the_item(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    hak_dir = tmp_path / "hak"
    summary = prc_recompute.add_widget(ed, _player(ed), hak_dir)
    assert summary.widget_added
    hak = hak_dir / f"{prc_recompute.HAK_NAME}.hak"
    assert hak.is_file()
    assert {r.resref for r in ErfReader().list_resources(hak)} == {"prc_recompute"}
    assert prc_recompute.HAK_NAME in _hak_names(ed)  # listed in Mod_HakList
    assert prc_recompute.installed_files(hak_dir) == [f"{prc_recompute.HAK_NAME}.hak"]
    assert _recompute_item(ed) is not None


def test_add_widget_is_idempotent(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    hak_dir = tmp_path / "hak"
    prc_recompute.add_widget(ed, _player(ed), hak_dir)
    prc_recompute.add_widget(ed, _player(ed), hak_dir)  # re-run
    widgets = [it for it in _carried(ed) if (it.get("Tag") or "") == "prc_recompute"]
    assert len(widgets) == 1
    assert _hak_names(ed).count(prc_recompute.HAK_NAME) == 1


def test_remove_installed_deletes_the_hak_file(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    hak_dir = tmp_path / "hak"
    prc_recompute.add_widget(ed, _player(ed), hak_dir)
    assert prc_recompute.remove_installed(hak_dir) == 1
    assert not (hak_dir / f"{prc_recompute.HAK_NAME}.hak").exists()
    assert prc_recompute.installed_files(hak_dir) == []


def test_add_widget_survives_a_save_as_round_trip(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    prc_recompute.add_widget(ed, _player(ed), tmp_path / "hak")
    new_save = ed.save_as(tmp_path / "out")
    reread = SaveEditor(new_save)
    assert prc_recompute.HAK_NAME in reread.module_hak_names()
    item = next(
        (it for it in reread._player_struct(reread._module_tree()).fields["ItemList"].value.structs
         if (it.get("Tag") or "") == "prc_recompute"), None)
    assert item is not None  # the widget persisted through a real write
    assert item.fields["PropertiesList"].value.structs[0].get("Subtype") == 335
