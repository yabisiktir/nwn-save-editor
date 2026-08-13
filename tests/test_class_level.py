"""Adding a class level (SaveEditor.add_class_level + LevelGains)."""

from __future__ import annotations

from nwnfile.formats.gff import Gff, GffField, GffList, GffStruct, GffType, write_gff
from nwnfile.level_up import LevelGains
from nwnsaveeditor.save_editor import SaveEditor, _xp_for_level
from nwnsaveeditor.save_game import SaveGame
from tests.test_erf_writer import _make_erf


def _character() -> GffStruct:
    classes = [
        GffStruct(struct_type=2, fields={  # Bard, level 8
            "Class": GffField(GffType.INT, 1),
            "ClassLevel": GffField(GffType.SHORT, 8),
        }),
    ]
    return GffStruct(struct_type=0xFFFFFFFF, fields={
        "FeatList": GffField(GffType.LIST, GffList([])),  # marks this a player struct
        "ClassList": GffField(GffType.LIST, GffList(classes)),
        "MaxHitPoints": GffField(GffType.INT, 50),
        "CurrentHitPoints": GffField(GffType.INT, 50),
        "BaseAttackBonus": GffField(GffType.INT, 6),
        "FortSaveThrow": GffField(GffType.INT, 2),
        "RefSaveThrow": GffField(GffType.INT, 6),
        "WillSaveThrow": GffField(GffType.INT, 6),
        "Experience": GffField(GffType.INT, _xp_for_level(8)),
    })


def _save(tmp_path) -> SaveGame:
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(GffType.LIST, GffList([_character()])),
    }))
    bic = Gff("BIC ", "V3.2", _character())
    folder = tmp_path / "000000 - test"
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([("module", 2014, write_gff(ifo))]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    return SaveGame(folder=folder)


def _gains(**over) -> LevelGains:
    base = dict(
        class_id=1, class_name="Bard", class_level=9, character_level=9,
        hit_die=6, bab_gain=1, fort_gain=0, ref_gain=1, will_gain=1,
        skill_point_base=6, granted_feats=(), general_feat=False,
        ability_increase=False, is_base_class=True, spellcaster=True,
    )
    base.update(over)
    return LevelGains(**base)


def test_bumps_the_class_and_applies_the_gains(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=2)  # hp = 6 + 2 = 8
    assert ed.player_classes() == [(1, 9)]  # Bard 8 -> 9
    player = ed._player_struct(ed._module_tree())
    assert player.fields["MaxHitPoints"].value == 58  # 50 + 8
    assert player.fields["BaseAttackBonus"].value == 7  # 6 + 1
    assert player.fields["RefSaveThrow"].value == 7  # 6 + 1
    assert player.fields["FortSaveThrow"].value == 2  # +0
    assert player.fields["Experience"].value == _xp_for_level(9)  # raised to fit


def test_it_edits_both_trees(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0)
    for tree in ed._targets():
        assert ed._class_list(tree).structs[0].get("ClassLevel") == 9


def test_a_new_class_is_added_at_level_one(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_class_level(4, _gains(class_id=4, class_level=1), con_modifier=0)
    assert (4, 1) in ed.player_classes()


def test_repeated_levels_show_as_one_change(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0)
    ed.add_class_level(1, _gains(class_level=10, character_level=10), con_modifier=0)
    classes = [c for c in ed.pending_changes() if c.kind == "class"]
    assert len(classes) == 1
    assert "+2 level" in classes[0].summary


def test_discard_reverts_everything(tmp_path):
    ed = SaveEditor(_save(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=2)
    ed.discard_change(("class", 1))
    assert ed.player_classes() == [(1, 8)]
    player = ed._player_struct(ed._module_tree())
    assert player.fields["MaxHitPoints"].value == 50  # back to original
    assert player.fields["BaseAttackBonus"].value == 6
