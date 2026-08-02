"""What a skill actually comes to — and how race, class and templates reach it."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nwnfile.hak_stack import HakStack
from nwnsaveeditor import skill_totals

SKILLS_2DA = """2DA V2.0

    Label         KeyAbility
0   Animal_Empathy CHA
2   Discipline    STR
5   Hide          DEX
19  Tumble        DEX
38  Truespeak     INT
"""

#: A Skill Bonus property; 52 is the id, Subtype is the skill, CostValue the size.
def _prop(property_name: int, subtype: int, cost_value: int):
    return SimpleNamespace(
        property_name=property_name, subtype=subtype, cost_value=cost_value
    )


def _item(name: str, *properties, slot: int = 1):
    return SimpleNamespace(name=name, tag=name, slot=slot, properties=list(properties))


def _skill(index: int, name: str, rank: int):
    return SimpleNamespace(index=index, name=name, rank=rank)


class _Stack(HakStack):
    def read_text(self, name, res_type, *, base=True):
        return SKILLS_2DA if name == "skills" else None


@pytest.fixture
def stack():
    return _Stack()


def _one(skills, abilities, items, stack=None):
    return {t.name: t for t in skill_totals.compute(skills, abilities, items, None, stack)}


# -- the key ability modifier, which is how everything else reaches a skill --- #
def test_the_modifier_comes_from_the_score_in_play(stack):
    """Race, class levels and templates raise the ability; the skill follows.

    Strength 29 is what the save stores; 70 is what the character has after the
    racial adjustment, Red Dragon Disciple levels and worn gear.
    """
    skills = [_skill(2, "Discipline", 43)]
    stored = _one(skills, {"Str": 29}, [], stack)["Discipline"]
    in_play = _one(skills, {"Str": 70}, [], stack)["Discipline"]
    assert stored.total == 52
    assert in_play.total == 73  # 43 rank + 30
    assert in_play.ability == "STR"


def test_a_skill_with_no_key_ability_gets_no_modifier(stack):
    total = _one([_skill(99, "Unknown", 5)], {"Str": 70}, [], stack)["Unknown"]
    assert total.ability == ""
    assert total.total == 5


def test_skills_2da_is_read_through_the_saves_haks(stack):
    """PRC adds skills past the base game's; one missing from the table would
    silently lose its ability modifier."""
    assert skill_totals.key_abilities(None, stack)[38] == "INT"
    assert skill_totals.key_abilities(None, None) == {}


# -- gear, including the skin PRC templates write to -------------------------- #
def test_a_template_reaches_a_skill_through_the_prc_skin(stack):
    """The Dark template's Hide bonus is an ordinary property on the skin."""
    skin = _item("base_prc_skin", _prop(52, 5, 8), slot=131072)
    total = _one([_skill(5, "Hide", 10)], {"Dex": 50}, [skin], stack)["Hide"]
    assert total.item_bonus == 8
    assert total.total == 38  # 10 rank + 20 Dex + 8
    assert total.sources == (("PRC skin (templates and class features)", 8),)


def test_each_item_is_named_separately(stack):
    items = [
        _item("Tuxedo of Infiltration", _prop(52, 5, 12)),
        _item("base_prc_skin", _prop(52, 5, 8), slot=131072),
    ]
    total = _one([_skill(5, "Hide", 10)], {"Dex": 50}, items, stack)["Hide"]
    assert total.item_bonus == 20
    assert [name for name, _ in total.sources] == [
        "Tuxedo of Infiltration", "PRC skin (templates and class features)"
    ]


def test_a_decreased_skill_property_subtracts(stack):
    penalty = _item("Cursed Boots", _prop(29, 5, 4))
    total = _one([_skill(5, "Hide", 10)], {"Dex": 10}, [penalty], stack)["Hide"]
    assert total.item_bonus == -4
    assert total.total == 6


def test_carried_and_ammunition_items_grant_nothing(stack):
    carried = _item("Bagged Cloak", _prop(52, 5, 10), slot=None)
    quiver = _item("Arrows of Sneaking", _prop(52, 5, 10), slot=4096)
    total = _one([_skill(5, "Hide", 10)], {"Dex": 10}, [carried, quiver], stack)["Hide"]
    assert total.item_bonus == 0
    assert total.sources == ()


def test_two_properties_on_one_item_are_one_source(stack):
    item = _item("Ring of Shadows", _prop(52, 5, 3), _prop(52, 5, 4))
    total = _one([_skill(5, "Hide", 0)], {"Dex": 10}, [item], stack)["Hide"]
    assert total.sources == (("Ring of Shadows", 7),)


# -- what the tooltip says ---------------------------------------------------- #
def test_every_part_of_a_skill_is_named(stack):
    skin = _item("base_prc_skin", _prop(52, 5, 8), slot=131072)
    detail = _one([_skill(5, "Hide", 10)], {"Dex": 50}, [skin], stack)["Hide"].detail()
    assert "Hide 38" in detail
    assert "10\trank, as stored in the save" in detail
    assert "+20\tDEX modifier, from the score in play" in detail
    assert "+8\tPRC skin (templates and class features)" in detail


def test_the_old_net_bonus_helper_still_agrees(stack):
    items = [_item("A", _prop(52, 5, 3)), _item("B", _prop(52, 5, 4))]
    assert skill_totals.item_skill_bonuses(items) == {5: 7}
