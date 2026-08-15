"""Resolving a raw GFF id field to a readable line (nwnfile/field_meaning.py)."""

from __future__ import annotations

from nwnfile.field_meaning import field_meaning


class _Ref:
    def feat_name(self, i): return {2213: "Divine Strike"}.get(i, f"feat {i}")
    def feat_description(self, i): return "Bonus damage vs undead." if i == 2213 else ""
    def spell_name(self, i): return {66: "Grease"}.get(i, f"spell {i}")
    def spell_description(self, i): return "Slippery floor." if i == 66 else ""
    def skill_name(self, i): return {3: "Discipline"}.get(i, f"skill {i}")


def test_a_feat_resolves_to_name_and_description():
    title, desc = field_meaning("Feat", 2213, _Ref())
    assert "Divine Strike" in title and "2213" in title
    assert "undead" in desc


def test_a_spell_resolves():
    title, desc = field_meaning("Spell", 66, _Ref())
    assert "Grease" in title and "Slippery" in desc


def test_class_and_race_resolve_by_name():
    # class_name/race_name come from the bundled tables; just assert the shape
    ctitle, _ = field_meaning("LvlStatClass", 0, _Ref())
    assert ctitle.startswith("Class #0:")
    rtitle, _ = field_meaning("Race", 0, _Ref())
    assert rtitle.startswith("Race #0:")


def test_lvlstat_ability_names_the_score():
    assert field_meaning("LvlStatAbility", 2, _Ref())[0].endswith("Constitution")


def test_an_unremarkable_field_is_none():
    assert field_meaning("ObjectId", 12345, _Ref()) is None
    assert field_meaning("Feat", "not-an-int", _Ref()) is None


def test_base_item_resolves_to_its_type():
    # base_item_type reads the bundled baseitems.2da (53 = Scimitar)
    title, _ = field_meaning("BaseItem", 53, _Ref())
    assert title == "Base item #53: Scimitar"


def test_an_unknown_base_item_is_none():
    assert field_meaning("BaseItem", 999999, _Ref()) is None
