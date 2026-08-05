"""Attributing a character's bonuses to the sources a save actually records."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nwnfile.formats.bic_reader import ItemProperty
from nwnsaveeditor import active_bonuses as ab


def _prop(property_name: int, subtype: int = 0, cost_value: int = 0) -> ItemProperty:
    return ItemProperty(
        property_name=property_name, subtype=subtype,
        cost_table=0, cost_value=cost_value, param1=0, param1_value=0,
    )


def _item(name: str, slot: int | None, *props: ItemProperty):
    return SimpleNamespace(
        name=name, slot=slot,
        properties=[SimpleNamespace(prop=p, index=i) for i, p in enumerate(props)],
    )


# -- what counts as a source ------------------------------------------------ #
def test_only_worn_items_contribute():
    """A sword in the backpack grants nothing, and neither does ammunition."""
    groups = ab.item_contributions([
        _item("worn ring", 128, _prop(0, 0, 5)),
        _item("in the bag", None, _prop(0, 0, 5)),
        _item("arrows", 2048, _prop(0, 0, 5)),
    ])
    assert len(groups) == 1
    assert [c.source for c in groups[0].contributions] == ["worn ring"]


def test_the_prc_skin_is_credited_as_the_skin_not_by_its_resref_name():
    """`base_prc_skin` means nothing to a player; "Creature skin" does."""
    groups = ab.item_contributions([_item("base_prc_skin", ab.SKIN_SLOT, _prop(0, 0, 6))])
    assert groups[0].contributions[0].source == "Creature skin (PRC)"


def test_an_items_display_name_can_be_resolved_through_the_editors_resolver():
    """Most items store only a strref, so the caller passes the same name_of the
    rest of the editor uses rather than the raw record name."""
    groups = ab.item_contributions(
        [_item("(unnamed: belt)", 1024, _prop(0, 0, 10))],
        name_of=lambda _item: "Greater Archer's Belt",
    )
    assert groups[0].contributions[0].source == "Greater Archer's Belt"


# -- routing ---------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("prop", "category", "subject"),
    [
        (_prop(0, 0, 10), "Ability scores", "Strength"),
        (_prop(0, 5, 4), "Ability scores", "Charisma"),
        (_prop(1, 0, 5), "Armour class", "Armour class"),
        (_prop(6, 0, 5), "Attack & damage", "Enhancement bonus"),
        (_prop(40, 0, 7), "Saving throws", "Saving throws"),
        (_prop(40, 13, 4), "Saving throws", "Saving throws vs. Poison"),
        (_prop(41, 1, 3), "Saving throws", "Will save"),
        (_prop(51, 0, 20), "Regeneration", "Regeneration"),
        (_prop(20, 10, 7), "Immunities & resistances", "Damage immunity: Fire"),
        (_prop(23, 7, 2), "Immunities & resistances", "Damage resistance: Cold"),
        (_prop(12, 16, 0), "Feats granted by gear", "Feats granted by gear"),
        (_prop(35, 0, 0), "Other gear properties", "Other gear properties"),
    ],
)
def test_each_property_lands_in_the_group_it_affects(prop, category, subject):
    groups = ab.item_contributions([_item("thing", 128, prop)])
    assert (groups[0].category, groups[0].subject) == (category, subject)


def test_no_equipped_property_is_silently_dropped():
    """Every property must reach a group — an unrouted one would vanish, and a
    bonus this view forgot is exactly the failure it exists to prevent."""
    props = [_prop(pid, 0, 1) for pid in range(0, 96)]
    groups = ab.item_contributions([_item("everything", 128, *props)])
    assert sum(g.count for g in groups) == len(props)


# -- arithmetic ------------------------------------------------------------- #
def test_a_group_reports_both_the_largest_and_the_sum():
    """NWN applies only the largest same-type item bonus; the save does not say
    which one, so neither number may be presented alone."""
    groups = ab.item_contributions([
        _item("belt", 1024, _prop(0, 0, 10)),
        _item("ring", 128, _prop(0, 0, 5)),
    ])
    group = groups[0]
    assert (group.largest, group.total) == (10, 15)
    assert group.summary == "largest +10 · sum +15"


def test_a_lone_contribution_shows_one_number_not_two():
    groups = ab.item_contributions([_item("ring", 128, _prop(0, 3, 5))])
    assert groups[0].summary == "+5"


def test_a_decreased_property_counts_as_a_penalty():
    """"Decreased Skill: Taunt +10" stores the size of the penalty, not a bonus."""
    groups = ab.item_contributions([_item("skin", ab.SKIN_SLOT, _prop(29, 42, 10))])
    assert groups[0].largest == -10


@pytest.mark.parametrize("pid", [39, 22, 74, 53])
def test_a_table_index_is_never_added_up_as_if_it_were_a_bonus(pid):
    """Spell Resistance, Damage Reduction, Massive Criticals and Immunity
    Specific Spell keep a table row or a spell id in CostValue. Summing those
    would print a number that means nothing, so they carry none."""
    groups = ab.item_contributions([_item("thing", 128, _prop(pid, 0, 216))])
    assert groups[0].largest is None
    assert "216" not in groups[0].summary


def test_repeated_properties_collapse_but_still_count_once_each():
    """The owner's skin carries the same immunity thirteen times over."""
    groups = ab.item_contributions([
        _item("skin", ab.SKIN_SLOT, *[_prop(20, 10, 7) for _ in range(13)])
    ])
    group = groups[0]
    assert len(group.contributions) == 1, "identical properties must fold into one row"
    assert group.contributions[0].repeats == 13
    assert group.contributions[0].label.startswith("13×")
    assert group.count == 13


def test_a_collapsed_numeric_property_is_still_summed_for_every_copy():
    groups = ab.item_contributions([
        _item("ring", 128, _prop(0, 0, 3), _prop(0, 0, 3))
    ])
    assert (groups[0].largest, groups[0].total) == (3, 6)


# -- ordering --------------------------------------------------------------- #
def test_abilities_read_in_sheet_order_not_alphabetically():
    props = [_prop(0, subtype, 2) for subtype in (5, 0, 4, 1)]
    result = ab.compute([_item("ring", 128, *props)], [], None)
    subjects = [g.subject for g in result.groups]
    assert subjects == ["Strength", "Dexterity", "Wisdom", "Charisma"]


def test_categories_come_out_in_the_views_order():
    result = ab.compute([_item("thing", 128, _prop(35), _prop(0, 0, 2), _prop(1, 0, 3))], [], None)
    assert [c for c, _g in result.by_category()] == [
        "Ability scores", "Armour class", "Other gear properties",
    ]


# -- what cannot be attributed ---------------------------------------------- #
def test_feats_are_counted_but_never_credited_with_a_number():
    """A save records which feats a character has, never what any of them does."""
    result = ab.compute([], [(1, "Cleave", True), (2, "Dodge", True)], None)
    assert result.feat_count == 2
    assert not result.groups, "no feat may invent a bonus group"


def test_only_the_class_numbers_the_record_stores_are_quoted():
    info = SimpleNamespace(
        classes=[(4, 8), (37, 10)], base_attack_bonus=27,
        save_fortitude=73, save_reflex=67, save_will=57,
    )
    result = ab.compute([], [], info)
    assert len(result.classes) == 2
    assert dict(result.class_facts) == {
        "Base attack bonus": "+27", "Base Fortitude save": "+73",
        "Base Reflex save": "+67", "Base Will save": "+57",
    }


def test_an_effect_with_no_spell_is_reported_as_unattributed_not_dropped():
    effects = [
        {"tag": "EffectHolyTouch", "spell": "", "caster_level": 0, "duration": 0.0},
        {"tag": "", "spell": "Bless", "caster_level": 9, "duration": 60.0},
    ]
    out = ab.spell_effects(effects)
    assert [e.attributed for e in out] == [False, True]
    assert out[0].name == "EffectHolyTouch", "a tag is still worth showing"
    assert out[1].caster_level == 9


def test_compute_survives_a_save_with_nothing_readable():
    result = ab.compute([], [], None)
    assert result.groups == [] and result.by_category() == []
    assert result.classes == [] and result.class_facts == []


# -- gear applying to one saving throw --------------------------------------- #
def test_the_universal_group_counts_towards_every_save():
    from nwnsaveeditor.active_bonuses import BonusGroup, Contribution, gear_bonus_for_save

    universal = BonusGroup("saves", "Saving throws", [Contribution("Belt", "+2", 2)])
    assert gear_bonus_for_save([universal], "Fortitude") == 2
    assert gear_bonus_for_save([universal], "Will") == 2


def test_the_largest_wins_because_nwn_does_not_stack_same_type():
    from nwnsaveeditor.active_bonuses import BonusGroup, Contribution, gear_bonus_for_save

    groups = [
        BonusGroup("saves", "Saving throws", [Contribution("Belt", "+2", 2)]),
        BonusGroup("saves", "Fortitude save", [Contribution("Ring", "+5", 5)]),
    ]
    assert gear_bonus_for_save(groups, "Fortitude") == 5


def test_a_save_nothing_applies_to_reports_none():
    from nwnsaveeditor.active_bonuses import BonusGroup, Contribution, gear_bonus_for_save

    groups = [BonusGroup("saves", "Fortitude save", [Contribution("Ring", "+5", 5)])]
    assert gear_bonus_for_save(groups, "Will") is None


def test_the_tables_reach_the_gear_rows(monkeypatch):
    """The Character screen's "Spell immunity" group showed "+216" for Flesh to
    Stone — the same text the inventory panel showed, from the same function."""
    from types import SimpleNamespace

    from nwnfile.formats.bic_reader import ItemProperty
    from nwnsaveeditor.active_bonuses import item_contributions

    class _Tables:
        def cost_options(self, cost_table):
            return {216: "Flesh to Stone"} if cost_table == 16 else {}

    item = SimpleNamespace(
        slot=1, name="Creature skin", properties=[
            SimpleNamespace(prop=ItemProperty(53, 0xFFFF, 16, 216, 255, 0)),
        ],
    )
    groups = item_contributions([item], lambda i: i.name, _Tables())
    details = [c.detail for g in groups for c in g.contributions]
    assert any("Flesh to Stone" in d for d in details)
    assert not any("+216" in d for d in details)
