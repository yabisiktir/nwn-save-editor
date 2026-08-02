"""Spell resistance: where it comes from, and the fact that it never stacks."""

from __future__ import annotations

import pytest

from nwnfile.formats.gff import GffField, GffList, GffStruct, GffType
from nwnfile.hak_stack import HakStack
from nwnfile.spell_resistance import SR_PROPERTY, spell_resistance

SRCOST = """2DA V2.0

    Name Label     Cost
0   2263 Bonus_10  0.1
1   2264 Bonus_12  0.4
2   2265 Bonus_14  1.2
3   2266 Bonus_16  2.0
11  2274 Bonus_32  8.0
40  9999 Bonus_70  9.9
"""


class _Stack(HakStack):
    def read_text(self, name, res_type, *, base=True):
        return SRCOST if name == "iprp_srcost" else None


@pytest.fixture
def stack():
    return _Stack()


def _struct(**fields):
    return GffStruct(0, dict(fields))


def _list(*structs):
    return GffField(GffType.LIST, GffList(list(structs)))


def _int(v):
    return GffField(GffType.INT, v)


def _string(v):
    return GffField(GffType.CEXOSTRING, v)


def _item(tag, *rows):
    return _struct(
        Tag=_string(tag),
        PropertiesList=_list(*[
            _struct(PropertyName=_int(SR_PROPERTY), CostValue=_int(r)) for r in rows
        ]),
    )


def _character(items=(), feats=()):
    return _struct(
        Equip_ItemList=_list(*items),
        FeatList=_list(*[_struct(Feat=_int(f)) for f in feats]),
    )


# -- items, which is also how PRC delivers race and template resistance ------- #
def test_an_items_resistance_is_read_through_the_cost_table(stack):
    """The save stores a table row, not the number."""
    result = spell_resistance(_character([_item("Cloak of Warding", 3)]), stack)
    assert result.effective == 16
    assert result.sources[0].label == "Cloak of Warding"


def test_the_prc_skin_counts_like_any_other_equipped_item(stack):
    """PRC writes racial and template resistance onto the skin as a property."""
    result = spell_resistance(_character([_item("base_prc_skin", 11)]), stack)
    assert result.effective == 32
    assert result.sources[0].kind == "item"


def test_without_the_cost_table_a_row_is_not_guessed_at():
    """A stored row means nothing on its own; inventing a value would mislead."""
    assert spell_resistance(_character([_item("Cloak", 3)])).sources == ()


# -- the rule that matters ---------------------------------------------------- #
def test_resistance_does_not_stack(stack):
    """Two sources of 16 and 32 give 32, never 48."""
    result = spell_resistance(
        _character([_item("Cloak", 3), _item("Amulet", 11)]), stack
    )
    assert result.effective == 32
    assert len(result.sources) == 2
    assert sum(s.value for s in result.sources) == 48, "the sum is real but must not be used"


def test_the_source_that_applies_is_named_and_the_rest_marked_overridden(stack):
    result = spell_resistance(
        _character([_item("Cloak", 3), _item("Amulet", 11)]), stack
    )
    assert result.applies.label == "Amulet"
    assert [s.label for s in result.overridden] == ["Cloak"]


def test_a_character_with_no_resistance_reads_zero_not_none(stack):
    result = spell_resistance(_character(), stack)
    assert result.effective == 0
    assert result.applies is None
    assert not result.immune_to_player_casters


def test_one_item_carrying_two_resistances_uses_its_greater(stack):
    result = spell_resistance(_character([_item("Odd Cloak", 0, 11)]), stack)
    assert result.effective == 32
    assert len(result.sources) == 1


# -- feats -------------------------------------------------------------------- #
def test_a_racial_resistance_feat_scales_with_level(stack):
    """The number in the name is a BASE, not the total.

    PRC's manual page for each of these reads "The creature has an innate spell
    resistance of 17, plus 1 per level", so the owner's level-40 Bralani has 57.
    Taking the name at face value understates such a character by their whole
    level -- 17 against 57, the difference between beatable and nearly immune.
    """
    names = {4617: "Spell Resistance 17"}
    result = spell_resistance(
        _character(feats=[4617]), stack, feat_name=names.get, character_level=40
    )
    assert result.effective == 57
    assert result.sources[0].kind == "feat"
    assert "+1 per level" in result.sources[0].label


def test_the_base_alone_is_used_when_the_level_is_unknown(stack):
    """Better a floor than a number invented from a level nobody supplied."""
    names = {4617: "Spell Resistance 17"}
    result = spell_resistance(_character(feats=[4617]), stack, feat_name=names.get)
    assert result.effective == 17
    assert "per level" not in result.sources[0].label


def test_diamond_soul_is_ten_plus_monk_level(stack):
    names = {4393: "Diamond Soul"}
    result = spell_resistance(
        _character(feats=[4393]), stack, feat_name=names.get, monk_level=12
    )
    assert result.effective == 22
    assert "monk 12" in result.sources[0].label


def test_each_improved_spell_resistance_feat_is_worth_two(stack):
    """``nImprovedSR += 2`` in PRC's prc_forsaker.nss -- not one."""
    names = {
        4393: "Diamond Soul",
        699: "Improved Spell Resistance I",
        700: "Improved Spell Resistance II",
    }
    result = spell_resistance(
        _character(feats=[4393, 699, 700]), stack, feat_name=names.get, monk_level=20
    )
    assert result.effective == 34  # 10 + 20 + 2 + 2


def test_diamond_soul_without_monk_levels_grants_nothing(stack):
    names = {4393: "Diamond Soul"}
    assert spell_resistance(
        _character(feats=[4393]), stack, feat_name=names.get
    ).sources == ()


def test_a_feat_merely_mentioning_resistance_is_not_counted(stack):
    """"Ignore Spell Resistance" and "Lower Spell Resistance" grant none."""
    names = {1: "Ignore Spell Resistance", 2: "Sorcerer Lower Spell Resistance"}
    assert spell_resistance(
        _character(feats=[1, 2]), stack, feat_name=names.get
    ).sources == ()


# -- what the number means ---------------------------------------------------- #
def test_67_is_immunity_to_anything_a_player_can_cast(stack):
    """d20 + 40 caster levels + 6 epic penetration tops out at 66."""
    names = {1: "Spell Resistance 66", 2: "Spell Resistance 67"}  # level 0, so as-is
    assert not spell_resistance(
        _character(feats=[1]), stack, feat_name=names.get
    ).immune_to_player_casters
    assert spell_resistance(
        _character(feats=[2]), stack, feat_name=names.get
    ).immune_to_player_casters


def test_sources_are_ordered_greatest_first(stack):
    result = spell_resistance(
        _character([_item("Small", 0), _item("Big", 11), _item("Middle", 3)]), stack
    )
    assert [s.value for s in result.sources] == [32, 16, 10]
