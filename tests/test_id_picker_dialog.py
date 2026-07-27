"""Tests for the searchable id picker (ui/dialogs/id_picker_dialog.py).

Guards the selection behaviour: a row must always be selected so OK/Enter works —
the earlier bug was that filtering left nothing selected, so "Add a feat" no-oped.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from vaultkeeper.ui.dialogs.id_picker_dialog import IdPickerDialog  # noqa: E402

_ITEMS = [(1, "Alertness"), (6, "Cleave"), (391, "Great Cleave"), (2, "Ambidexterity")]


def _names(dialog):
    tree = dialog._tree
    return [tree.topLevelItem(i).text(1) for i in range(tree.topLevelItemCount())]


def test_first_row_selected_on_open(qtbot):
    dialog = IdPickerDialog("Pick", _ITEMS)
    qtbot.addWidget(dialog)
    # sorted by name -> Alertness first; something is selected so OK works immediately
    assert dialog.selected_id() == 1


def test_filter_selects_the_top_match(qtbot):
    dialog = IdPickerDialog("Pick", _ITEMS)
    qtbot.addWidget(dialog)
    dialog._filter.setText("cleave")
    assert dialog.selected_id() == 6  # Cleave (top of the two "cleave" matches)
    dialog._filter.setText("great cleave")
    assert dialog.selected_id() == 391  # Great Cleave


def test_filter_matches_raw_id(qtbot):
    dialog = IdPickerDialog("Pick", _ITEMS)
    qtbot.addWidget(dialog)
    dialog._filter.setText("391")  # typing the id also finds the row
    assert dialog.selected_id() == 391


def test_id_column_shows_the_raw_id(qtbot):
    dialog = IdPickerDialog("Pick", _ITEMS)
    qtbot.addWidget(dialog)
    tree = dialog._tree
    ids = {
        tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
        for i in range(tree.topLevelItemCount())
    }
    assert ids == {1, 2, 6, 391}
    assert tree.columnCount() == 2 and tree.headerItem().text(0) == "ID"


def test_no_match_selects_nothing(qtbot):
    dialog = IdPickerDialog("Pick", _ITEMS)
    qtbot.addWidget(dialog)
    dialog._filter.setText("zzz-no-match")
    assert dialog.selected_id() is None  # OK/Enter safely does nothing


def test_prc_ids_are_marked(qtbot):
    dialog = IdPickerDialog("Pick", _ITEMS, mark_ids=frozenset({391}), mark_label="PRC")
    qtbot.addWidget(dialog)
    names = _names(dialog)
    assert any("Great Cleave" in text and "PRC" in text for text in names)
    assert not any(text == "Cleave" and "PRC" in text for text in names)
