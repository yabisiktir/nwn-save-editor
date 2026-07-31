"""Adding an item property — the curated fallback and the table-driven picker."""

from __future__ import annotations

import pytest

from vaultkeeper.ui.dialogs.add_property_dialog import AddPropertyDialog


class _Tables:
    """Three property types: a flag, one with a small subtype list, one huge."""

    available = True

    def property_ids(self):
        return [1, 12, 52]

    def property_name_label(self, pid):
        return {1: "AC Bonus", 12: "Bonus Feat", 52: "Skill Bonus"}.get(pid)

    def cost_table_for(self, pid):
        return {1: 2, 52: 25}.get(pid)  # Bonus Feat has no cost table

    def cost_options(self, table):
        return {1: "+1", 2: "+2"} if table is not None else {}

    def subtype_options(self, pid):
        if pid == 12:
            return {i: f"Feat {i}" for i in range(1, 1200)}  # the real list is huge
        if pid == 52:
            return {0: "Discipline", 1: "Tumble"}
        return None

    def param1_options(self, pid):
        return {0: "One", 1: "Two"} if pid == 1 else None


@pytest.fixture
def dialog(qtbot):
    dlg = AddPropertyDialog(tables=_Tables())
    qtbot.addWidget(dlg)
    dlg.show()  # visibility drives which inputs count; offscreen is fine
    return dlg


def _choose(dialog, label):
    index = next(
        i for i in range(dialog._type.count()) if dialog._type.itemText(i) == label
    )
    dialog._type.setCurrentIndex(index)


# -- the table-driven path -------------------------------------------------- #
def test_it_offers_every_property_the_game_defines(dialog):
    """The curated list was 14 entries, so most property types could not be added."""
    labels = {dialog._type.itemText(i) for i in range(dialog._type.count())}
    assert labels == {"AC Bonus", "Bonus Feat", "Skill Bonus"}


def test_a_huge_subtype_list_gets_a_searchable_picker_not_a_combo(dialog):
    """1,200 feats in a combo box cannot be searched — that was the complaint."""
    _choose(dialog, "Bonus Feat")
    assert dialog._subtype_btn.isVisible()
    assert not dialog._subtype.isVisible()
    assert len(dialog._subtype_options()) == 1199


def test_a_small_subtype_list_stays_a_combo(dialog):
    _choose(dialog, "Skill Bonus")
    assert dialog._subtype.isVisible()
    assert not dialog._subtype_btn.isVisible()


def test_the_value_comes_from_the_propertys_own_cost_table(dialog):
    _choose(dialog, "Skill Bonus")
    values = [dialog._value.itemText(i) for i in range(dialog._value.count())]
    assert values == ["+1", "+2"]


def test_a_property_with_no_cost_table_offers_no_value(dialog):
    _choose(dialog, "Bonus Feat")
    assert not dialog._value.isVisible()
    assert dialog.result_property()["cost_value"] == 0


def test_a_param_is_offered_when_the_property_defines_one(dialog):
    _choose(dialog, "AC Bonus")
    assert dialog._param.isVisible()
    assert dialog.result_property()["param1"] == 0


def test_a_property_with_no_param_passes_none_so_it_stays_unset(dialog):
    _choose(dialog, "Skill Bonus")
    assert dialog.result_property()["param1"] is None


def test_the_picked_feat_is_what_comes_back(dialog):
    _choose(dialog, "Bonus Feat")
    dialog._subtype_value = 900
    built = dialog.result_property()
    assert built["property_name"] == 12
    assert built["subtype"] == 900
    assert built["label"] == "Bonus Feat: Feat 900"


def test_switching_type_does_not_leak_the_previous_subtype(dialog):
    _choose(dialog, "Bonus Feat")
    dialog._subtype_value = 900
    _choose(dialog, "Skill Bonus")
    assert dialog.result_property()["subtype"] in (0, 1)


# -- the fallback ------------------------------------------------------------ #
def test_without_tables_it_falls_back_to_the_curated_set(qtbot):
    dlg = AddPropertyDialog(tables=None)
    qtbot.addWidget(dlg)
    dlg.show()
    _choose(dlg, "AC Bonus")
    dlg._magnitude.setValue(7)
    built = dlg.result_property()
    assert built == {
        "property_name": 1, "subtype": 0, "cost_value": 7,
        "cost_table": 2, "label": "AC Bonus +7",
    }


def test_unreadable_tables_are_treated_as_absent(qtbot):
    class _Empty:
        available = False

    dlg = AddPropertyDialog(tables=_Empty())
    qtbot.addWidget(dlg)
    assert dlg._tables is None
    assert dlg._type.count() == 14, "the curated set"
