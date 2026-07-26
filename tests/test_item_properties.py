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
    assert describe_property(_prop(12, 29, 0), {12: "Bonus Feat"}) == "Bonus Feat"


def test_unknown_property_id_falls_back():
    assert describe_property(_prop(999, 0, 0), {}) == "Property 999"


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
