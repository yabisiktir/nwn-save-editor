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


def test_staged_bytes_reflect_the_added_level_for_a_live_reread(tmp_path):
    """The screen re-reads the character from these bytes, so the new level must
    be visible before the save is written."""
    from nwnfile.formats.bic_reader import BicFileReader

    ed = SaveEditor(_save(tmp_path))
    assert ed.staged_character_bytes() is None  # nothing staged -> read the file
    ed.add_class_level(1, _gains(), con_modifier=2)
    data = ed.staged_character_bytes()
    assert data is not None and ed.has_character_edits
    info = BicFileReader().read_bytes(data)
    assert (1, 9) in info.classes  # Bard 8 -> 9 shows in the re-parsed record


# -- level history (LvlStatList) -------------------------------------------- #
def _character_with_history(bard_level: int = 8) -> GffStruct:
    """A character that keeps a SkillList and a one-entry LvlStatList, so an added
    level has a history to extend."""
    char = _character()
    char.fields["ClassList"].value.structs[0].fields["ClassLevel"].value = bard_level
    skills = [GffStruct(struct_type=0, fields={"Rank": GffField(GffType.SHORT, r)})
              for r in (2, 0, 4)]
    char.fields["SkillList"] = GffField(GffType.LIST, GffList(skills))
    first = GffStruct(struct_type=0, fields={
        "LvlStatClass": GffField(GffType.BYTE, 1),
        "LvlStatHitDie": GffField(GffType.BYTE, 6),
        "EpicLevel": GffField(GffType.BYTE, 0),
        "SkillPoints": GffField(GffType.WORD, 3),  # 3 unspent carried in
        "SkillList": GffField(GffType.LIST, GffList([
            GffStruct(struct_type=0, fields={"Rank": GffField(GffType.BYTE, 0)})
            for _ in range(3)
        ])),
        "FeatList": GffField(GffType.LIST, GffList([])),
    })
    char.fields["LvlStatList"] = GffField(GffType.LIST, GffList([first]))
    return char


def _save_with_history(tmp_path, bard_level: int = 8) -> SaveGame:
    ifo = Gff("IFO ", "V3.2", GffStruct(struct_type=0xFFFFFFFF, fields={
        "Mod_PlayerList": GffField(
            GffType.LIST, GffList([_character_with_history(bard_level)])),
    }))
    bic = Gff("BIC ", "V3.2", _character_with_history(bard_level))
    folder = tmp_path / "000000 - hist"
    folder.mkdir()
    (folder / "x.sav").write_bytes(_make_erf([("module", 2014, write_gff(ifo))]))
    (folder / "player.bic").write_bytes(write_gff(bic))
    return SaveGame(folder=folder)


def _history(ed):
    player = ed._player_struct(ed._module_tree())
    return player.fields["LvlStatList"].value.structs


def test_a_level_appends_a_history_entry(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    assert len(_history(ed)) == 1
    ed.add_class_level(
        1, _gains(), con_modifier=2, int_modifier=1,
        skill_ranks={0: 5}, feats=(391,),  # skill 0: 2 -> 5 (delta 3); one feat
    )
    hist = _history(ed)
    assert len(hist) == 2  # a new entry
    entry = hist[-1]
    assert entry.get("LvlStatClass") == 1
    assert entry.get("LvlStatHitDie") == 6  # d6 rolled max, no Con folded in
    assert entry.get("EpicLevel") == 0  # total level 9
    assert [s.get("Feat") for s in entry.fields["FeatList"].value.structs] == [391]
    deltas = [s.get("Rank") for s in entry.fields["SkillList"].value.structs]
    assert deltas == [3, 0, 0]  # only skill 0 moved, by 3
    # running unspent balance: 3 carried in + (budget 7 - spent 3) = 7
    assert entry.get("SkillPoints") == 7
    assert "LvlStatAbility" not in entry.fields  # no ability raised this level


def test_history_records_an_ability_only_when_one_was_raised(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0, ability="Con")
    entry = _history(ed)[-1]
    assert "LvlStatAbility" in entry.fields
    assert entry.get("LvlStatAbility") == 2  # Con -> index 2


def test_history_entry_reverts_on_discard(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0, feats=(391,))
    assert len(_history(ed)) == 2
    ed.discard_change(("class", 1))
    assert len(_history(ed)) == 1  # back to the original single entry


def test_history_written_to_both_trees(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0)
    for tree in ed._targets():
        assert len(ed._player_struct(tree).fields["LvlStatList"].value.structs) == 2


def test_a_history_entry_marks_an_epic_level(tmp_path):
    # start at level 20 so the added level (21) is the character's first epic one
    ed = SaveEditor(_save_with_history(tmp_path, bard_level=20))
    ed.add_class_level(1, _gains(class_level=21, character_level=21), con_modifier=0)
    assert _history(ed)[-1].get("EpicLevel") == 1


# -- known spells (caster levels) ------------------------------------------- #
def _known(cstruct, spell_level):
    f = cstruct.fields.get(f"KnownList{spell_level}")
    return [s.get("Spell") for s in f.value.structs] if f else None


def test_known_spells_go_to_the_spellbook_and_the_history(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    ed.add_class_level(
        1, _gains(), con_modifier=0,
        spells_known={0: [33, 37], 1: [16]},  # two cantrips + one 1st-level
    )
    player = ed._player_struct(ed._module_tree())
    bard = player.fields["ClassList"].value.structs[0]  # class 1
    assert _known(bard, 0) == [33, 37]  # spellbook KnownList0
    assert _known(bard, 1) == [16]      # spellbook KnownList1
    entry = _history(ed)[-1]
    assert [s.get("Spell") for s in entry.fields["KnownList0"].value.structs] == [33, 37]
    assert [s.get("Spell") for s in entry.fields["KnownList1"].value.structs] == [16]


def test_known_spells_append_to_an_existing_list_without_duplicates(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    bard = ed._player_struct(ed._module_tree()).fields["ClassList"].value.structs[0]
    bard.fields["KnownList0"] = GffField(GffType.LIST, GffList([
        GffStruct(struct_type=3, fields={"Spell": GffField(GffType.WORD, 33)}),
    ]))
    ed.add_class_level(1, _gains(), con_modifier=0, spells_known={0: [33, 37]})
    bard = ed._player_struct(ed._module_tree()).fields["ClassList"].value.structs[0]
    assert _known(bard, 0) == [33, 37]  # 33 not duplicated, 37 appended


def test_no_known_spells_writes_no_knownlist(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0)
    entry = _history(ed)[-1]
    assert not any(k.startswith("KnownList") for k in entry.fields)


def test_known_spells_revert_on_discard(tmp_path):
    ed = SaveEditor(_save_with_history(tmp_path))
    ed.add_class_level(1, _gains(), con_modifier=0, spells_known={0: [33]})
    ed.discard_change(("class", 1))
    bard = ed._player_struct(ed._module_tree()).fields["ClassList"].value.structs[0]
    assert _known(bard, 0) is None  # the KnownList0 we created is gone
