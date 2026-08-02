"""Reading a character's real ability scores: race, PRC templates, worn items."""

from __future__ import annotations

import pytest

from nwnfile.ability_breakdown import ability_breakdown
from nwnfile.formats.gff import GffField, GffList, GffStruct, GffType
from nwnfile.hak_stack import HakStack, hak_names_from_module
from nwnfile.races import RaceTable

RACIALTYPES = """2DA V2.0

    Label     StrAdjust DexAdjust IntAdjust ChaAdjust WisAdjust ConAdjust
0   Dwarf     0         0         0         -2        0         2
1   Elf       0         2         0         0         0         -2
2   Human     ****      ****      ****      ****      ****      ****
159 Bralani   8         8         2         4         4         6
"""


def _field(type_, value):
    return GffField(type_, value)


def _struct(**fields):
    return GffStruct(0, {k: v for k, v in fields.items()})


def _list(*structs):
    return _field(GffType.LIST, GffList(list(structs)))


def _int(value):
    return _field(GffType.INT, value)


def _string(value):
    return _field(GffType.CEXOSTRING, value)


def _property(subtype: int, amount: int):
    return _struct(PropertyName=_int(0), Subtype=_int(subtype), CostValue=_int(amount))


def _item(tag: str, *properties, variables=None):
    fields = {"Tag": _string(tag), "PropertiesList": _list(*properties)}
    if variables:
        fields["VarTable"] = _list(*[
            _struct(Name=_string(n), Value=_int(v) if isinstance(v, int) else _string(v))
            for n, v in variables
        ])
    return _struct(**fields)


def _character(race=159, abilities=(29, 22, 14, 14, 8, 10), items=()):
    fields = {"Race": _int(race)}
    names = ("Str", "Dex", "Con", "Int", "Wis", "Cha")
    for name, value in zip(names, abilities, strict=True):
        fields[name] = _int(value)
    fields["Equip_ItemList"] = _list(*items)
    return _struct(**fields)


class _Stack(HakStack):
    """A stack whose one table is supplied directly, so no install is needed."""

    def read_text(self, name, res_type, *, base=True):
        return RACIALTYPES if name == "racialtypes" else None


@pytest.fixture
def races():
    return RaceTable(_Stack())


# -- the racial adjustment ---------------------------------------------------- #
def test_a_save_stores_base_scores_so_race_must_be_added(races):
    """This is the whole reason our sheet read lower than the game's."""
    [strength, *_] = ability_breakdown(_character(), races)
    assert strength.base == 29
    assert strength.total == 37
    assert [(c.source, c.amount) for c in strength.components] == [("Bralani", 8)]


def test_columns_are_read_by_name_not_position(races):
    """racialtypes.2da orders them Str Dex **Int Cha** Wis Con — not the usual way."""
    assert races.adjustments(159) == {
        "Str": 8, "Dex": 8, "Int": 2, "Cha": 4, "Wis": 4, "Con": 6
    }


def test_a_negative_adjustment_is_kept(races):
    assert races.adjustments(0) == {"Cha": -2, "Con": 2}


def test_a_race_that_adjusts_nothing_contributes_nothing(races):
    assert races.adjustments(2) == {}


def test_an_unknown_race_is_not_guessed_at(races):
    assert not races.has_race(999)
    assert ability_breakdown(_character(race=999), races)[0].total == 29


def test_without_a_table_the_racial_row_is_absent_rather_than_zero():
    """A missing table and a race with no adjustment are different claims."""
    strength = ability_breakdown(_character())[0]
    assert strength.of_kind("race") == ()
    assert strength.total == 29


# -- worn items --------------------------------------------------------------- #
def test_worn_items_are_credited_by_name(races):
    belt = _item("Belt of the Warrior", _property(0, 10))
    strength = ability_breakdown(_character(items=[belt]), races)[0]
    assert strength.total == 47
    assert ("Belt of the Warrior", 10, "item") in [
        (c.source, c.amount, c.kind) for c in strength.components
    ]


def test_properties_that_are_not_ability_bonuses_are_ignored(races):
    noise = _struct(PropertyName=_int(6), Subtype=_int(0), CostValue=_int(99))
    item = _struct(Tag=_string("Sword"), PropertiesList=_list(noise))
    assert ability_breakdown(_character(items=[item]), races)[0].total == 37


# -- PRC templates ------------------------------------------------------------ #
def test_the_prc_skin_is_split_into_the_templates_that_wrote_it(races):
    """PRC templates stamp item properties onto the skin and log each by name."""
    skin = _item(
        "base_prc_skin", _property(2, 8),
        variables=[
            ("PRC_CBon_Names", 2),
            ("PRC_CBon_Names_0", "Template_Saint_con"),
            ("PRC_CBon_Names_1", "Template_Halftroll_con"),
            ("Template_Saint_con", 2),
            ("Template_Halftroll_con", 6),
        ],
    )
    con = ability_breakdown(_character(items=[skin]), races)[2]
    assert con.total == 28  # 14 base + 6 race + 8 skin
    assert [(c.source, c.amount, c.kind) for c in con.of_kind("template")] == [
        ("Halftroll", 6, "template"), ("Saint", 2, "template")
    ]
    assert con.attributed


def test_the_split_never_changes_the_total(races):
    """Attribution is presentation. Counting registry *and* properties would double."""
    plain = _item("base_prc_skin", _property(2, 8))
    logged = _item(
        "base_prc_skin", _property(2, 8),
        variables=[("PRC_CBon_Names", 1), ("PRC_CBon_Names_0", "Template_Saint_con"),
                   ("Template_Saint_con", 8)],
    )
    assert (
        ability_breakdown(_character(items=[plain]), races)[2].total
        == ability_breakdown(_character(items=[logged]), races)[2].total
    )


def test_a_registry_that_does_not_add_up_falls_back_to_the_item(races):
    """Losing points to a partial attribution would be worse than a vaguer label."""
    skin = _item(
        "base_prc_skin", _property(2, 8),
        variables=[("PRC_CBon_Names", 1), ("PRC_CBon_Names_0", "Template_Saint_con"),
                   ("Template_Saint_con", 2)],
    )
    con = ability_breakdown(_character(items=[skin]), races)[2]
    assert con.total == 28
    assert con.of_kind("template") == ()
    assert not con.attributed


def test_templates_are_listed_in_registry_order():
    from nwnfile import prc_bonuses

    skin = _item(
        "base_prc_skin",
        variables=[("PRC_CBon_Names", 3),
                   ("PRC_CBon_Names_0", "Template_Saint_con"),
                   ("PRC_CBon_Names_1", "Template_Halftroll_str"),
                   ("PRC_CBon_Names_2", "Template_Saint_wis"),
                   ("Template_Saint_con", 2), ("Template_Halftroll_str", 6),
                   ("Template_Saint_wis", 2)],
    )
    assert prc_bonuses.template_names(skin) == ["Saint", "Halftroll"]


def test_junk_in_the_registry_is_not_mistaken_for_a_template():
    """Editing tools leave stray names on the skin; only Template_* means a template."""
    from nwnfile import prc_bonuses

    skin = _item(
        "base_prc_skin",
        variables=[("PRC_CBon_Names", 2), ("PRC_CBon_Names_0", "fghjklh"),
                   ("PRC_CBon_Names_1", "Template_Saint_con"),
                   ("fghjklh", 10), ("Template_Saint_con", 2)],
    )
    assert prc_bonuses.template_names(skin) == ["Saint"]


def test_a_character_with_no_skin_still_reads(races):
    assert ability_breakdown(_character(), races)[0].total == 37


# -- the hak search path ------------------------------------------------------ #
def test_the_hak_list_comes_from_the_save(tmp_path):
    """Different saves list different haks, so guessing a name gets it wrong."""
    for name in ("prc8_2das", "prc8_race"):
        (tmp_path / f"{name}.hak").write_bytes(b"")
    module = _struct(Mod_HakList=_list(
        _struct(Mod_Hak=_string("prc8_2das")),
        _struct(Mod_Hak=_string("prc8_race")),
    ))
    stack = HakStack.for_module(hak_names_from_module(module), tmp_path)
    assert [p.stem for p in stack.haks] == ["prc8_2das", "prc8_race"]


def test_a_hak_the_player_has_removed_is_skipped_not_fatal(tmp_path):
    (tmp_path / "prc8_race.hak").write_bytes(b"")
    module = _struct(Mod_HakList=_list(
        _struct(Mod_Hak=_string("gone")), _struct(Mod_Hak=_string("prc8_race"))
    ))
    stack = HakStack.for_module(hak_names_from_module(module), tmp_path)
    assert [p.stem for p in stack.haks] == ["prc8_race"]


def test_a_module_with_no_haks_is_not_an_error():
    assert hak_names_from_module(_struct()) == ()
    assert HakStack.for_module((), None).haks == ()


# -- abilities a class grants as it levels ------------------------------------ #
CLASSES = """2DA V2.0

    Label            StatGainTable
1   Bard             ****
37  Dragon_Disciple  cls_stat_dradis
"""

DRADIS = """2DA V2.0

    Level Str  Con  Int  Cha
0   1     **** **** **** ****
1   2     2    **** **** ****
2   3     **** **** **** ****
3   4     2    **** **** ****
4   5     **** **** **** ****
5   6     **** **** **** ****
6   7     **** 2    **** ****
7   8     **** **** **** ****
8   9     **** **** 2    ****
9   10    4    **** **** 2
"""


class _ClassStack(HakStack):
    def read_text(self, name, res_type, *, base=True):
        return {"classes": CLASSES, "cls_stat_dradis": DRADIS}.get(name)


@pytest.fixture
def classes():
    from nwnfile.class_tables import ClassTable

    return ClassTable(_ClassStack())


def _with_classes(*levels):
    """A character carrying a ClassList of ``(class id, level)``."""
    character = _character()
    character.fields["ClassList"] = _list(*[
        _struct(Class=_int(c), ClassLevel=_int(lv)) for c, lv in levels
    ])
    return character


def test_class_levels_raise_abilities_and_are_not_stored(classes):
    """A Red Dragon Disciple's Strength is re-added on load, never written back."""
    assert classes.gains(37, 10) == {"Str": 8, "Con": 2, "Int": 2, "Cha": 2}


def test_only_levels_actually_reached_count(classes):
    assert classes.gains(37, 6) == {"Str": 4}
    assert classes.gains(37, 1) == {}
    assert classes.gains(37, 0) == {}


def test_a_class_that_grants_nothing_has_no_table(classes):
    assert classes.stat_gain_table(1) == ""
    assert classes.gains(1, 20) == {}


def test_the_class_row_is_named_with_its_level(classes, races):
    strength = ability_breakdown(_with_classes((37, 10)), races, classes=classes)[0]
    assert ("Dragon Disciple 10", 8, "class") in [
        (c.source, c.amount, c.kind) for c in strength.components
    ]
    assert strength.total == 45  # 29 stored + 8 race + 8 class


def test_every_class_in_a_multiclass_contributes(classes, races):
    rows = ability_breakdown(_with_classes((1, 8), (37, 10)), races, classes=classes)
    assert rows[0].total == 45
    assert len(rows[0].of_kind("class")) == 1  # Bard grants no ability


def test_without_the_table_the_class_row_is_absent_not_zero(races):
    assert ability_breakdown(_with_classes((37, 10)), races)[0].of_kind("class") == ()


def test_the_owners_character_adds_up_to_what_the_game_shows(classes, races):
    """Strength 29 stored, 70 in play: race +8, Dragon Disciple +8, gear +25."""
    character = _with_classes((37, 10))
    character.fields["Equip_ItemList"] = _list(
        _item("Belt of the Warrior", _property(0, 10)),
        _item("Planar Shroud", _property(0, 4)),
        _item("Ring of the All-Rounder", _property(0, 5)),
        _item(
            "base_prc_skin", _property(0, 6),
            variables=[("PRC_CBon_Names", 1),
                       ("PRC_CBon_Names_0", "Template_Halftroll_str"),
                       ("Template_Halftroll_str", 6)],
        ),
    )
    assert ability_breakdown(character, races, classes=classes)[0].total == 70
