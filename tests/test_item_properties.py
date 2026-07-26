"""Tests for item magical-property naming (game/item_properties.py)."""

from __future__ import annotations

from vaultkeeper.core.formats.bic_reader import ItemProperty
from vaultkeeper.game.item_properties import (
    default_property_names,
    describe_properties,
    describe_property,
    load_property_names,
)


def _prop(name, subtype=0, cost_value=0) -> ItemProperty:
    return ItemProperty(name, subtype, 1, cost_value, 255, 0)


def test_ability_subtype_and_magnitude():
    # Ability Bonus (0), subtype 1 = Dexterity, CostValue 8 -> "+8".
    assert describe_property(_prop(0, 1, 8), {0: "Ability Bonus"}) == "Ability Bonus: Dexterity +8"


def test_damage_subtype_without_misleading_magnitude():
    # Damage Bonus (16), subtype 10 = Fire; CostValue indexes a dice table, so no +N.
    assert describe_property(_prop(16, 10, 5), {16: "Damage Bonus"}) == "Damage Bonus: Fire"


def test_generic_bonus_appends_cost_value():
    assert describe_property(_prop(6, 0, 7), {6: "Enhancement Bonus"}) == "Enhancement Bonus +7"


def test_generic_zero_cost_has_no_magnitude():
    # prop 71 (True Seeing) uses no subtype table -> just the name.
    assert describe_property(_prop(71, 0, 0), {71: "True Seeing"}) == "True Seeing"


def test_unknown_property_id_falls_back():
    assert describe_property(_prop(999, 0, 0), {}) == "Property 999"


def test_feat_subtype_resolved_from_hak_table():
    # Bonus Feat (12), subtype 2 -> iprp_feats FeatIndex 6 -> Cleave (bundled map).
    assert describe_property(_prop(12, 2, 0)) == "Bonus Feat: Cleave"


def test_cast_spell_shows_spell_level_and_uses():
    # Cast Spell (15), subtype 28 -> Chain Lightning (level 6); CostValue 12 = 5 uses/day.
    assert describe_property(_prop(15, 28, 0)) == "Cast Spell: Chain Lightning (level 6)"
    assert describe_property(_prop(15, 28, 12)) == (
        "Cast Spell: Chain Lightning (level 6, 5 uses/day)"
    )


def test_immunity_and_on_hit_subtypes():
    assert describe_property(_prop(37, 3, 0)) == "Immunity: Poison"
    assert describe_property(_prop(48, 1, 0)) == "On Hit: Stun"


def test_damage_immunity_percentage_and_resistance_amount():
    # Damage Immunity (20): subtype = Fire, CostValue 7 = 100% (iprp_immuncost).
    assert describe_property(_prop(20, 10, 7)) == "Damage Immunity: Fire 100%"
    # Damage Resistance (23): subtype = Cold, CostValue 4 = 20/- (iprp_resistcost).
    assert describe_property(_prop(23, 7, 4)) == "Damage Resistance: Cold 20/-"


def test_improved_saving_throws_and_vs_racial_group():
    assert describe_property(_prop(40, 13, 4)) == "Improved Saving Throws: Poison +4"
    assert describe_property(_prop(4, 20, 12)) == (
        "AC Bonus vs. Racial Group: Outsider +12"
    )


def test_bundled_onhit_spell_and_spell_levels_loaded():
    from vaultkeeper.game.item_properties import _onhit_spells, _spell_levels

    assert len(_onhit_spells()) > 50
    assert len(_spell_levels()) > 500
    assert _spell_levels()[28] == 6  # Chain Lightning innate level


def test_skill_subtype_resolved():
    # Skill Bonus (52), subtype 3 -> skills.2da id 3 -> Discipline, with +8.
    assert describe_property(_prop(52, 3, 8)) == "Skill Bonus: Discipline +8"


def test_use_limitation_class_names_the_class():
    # prop 63, subtype 32 -> Champion of Torm (base CLASS_NAMES).
    assert describe_property(_prop(63, 32, 0)) == "Use Limitation Class: Champion of Torm"


def test_bonus_spell_slot_shows_level_and_class():
    # prop 13, subtype 1 = Bard, CostValue 4 = spell level.
    assert describe_property(_prop(13, 1, 4)) == "Bonus Spell Slot of Level 4: Bard"


def test_spell_level_property_shows_level_not_plus_bonus():
    # prop 78 Immunity Spells by Level, CostValue 6 is a spell level (not "+6").
    assert describe_property(_prop(78, 0, 6)) == "Immunity Spells by Level 6"


def test_bundled_subtype_maps_loaded():
    from vaultkeeper.game.item_properties import _feats, _spells

    assert len(_feats()) > 10000  # iprp_feats resolved to feat names
    assert len(_spells()) > 500  # iprp_spells resolved to spell names


def test_describe_properties_uses_bundled_names():
    lines = describe_properties([_prop(0, 5, 8), _prop(51, 0, 3)])
    assert lines == ["Ability Bonus: Charisma +8", "Regeneration +3"]


def test_load_property_names_skips_non_int(tmp_path):
    path = tmp_path / "Item Property Names.json"
    path.write_text('{"0": "Ability Bonus", "bad": "x"}', encoding="utf-8")
    assert load_property_names(path) == {0: "Ability Bonus"}


def test_bundled_property_names_loaded():
    names = default_property_names()
    assert len(names) > 90
    assert names[0] == "Ability Bonus"
    assert names[6] == "Enhancement Bonus"
    assert names[75] == "Freedom of Movement"
