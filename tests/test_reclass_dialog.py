"""The level picker for re-classing a taken level (ReclassLevelDialog)."""

from __future__ import annotations

from nwnsaveeditor.ui.dialogs.reclass_level_dialog import ReclassLevelDialog

_LEVELS = [(0, "Level 1 — Fighter"), (1, "Level 2 — Fighter"), (2, "Level 3 — Rogue")]


def test_it_lists_each_level_and_returns_the_chosen_index(qtbot):
    dialog = ReclassLevelDialog(_LEVELS)
    qtbot.addWidget(dialog)
    assert dialog._combo.count() == 3
    dialog._combo.setCurrentIndex(1)
    assert dialog.selected_index() == 1  # the history index behind "Level 2"


def test_keep_previous_is_offered_only_when_allowed(qtbot):
    strict = ReclassLevelDialog(_LEVELS, allow_keep_previous=False)
    qtbot.addWidget(strict)
    assert strict._keep_box is None  # no break-it option in Strict
    assert strict.keep_previous() is False

    free = ReclassLevelDialog(_LEVELS, allow_keep_previous=True)
    qtbot.addWidget(free)
    assert free._keep_box is not None
    assert free.keep_previous() is False  # unticked by default
    free._keep_box.setChecked(True)
    assert free.keep_previous() is True


def test_an_empty_history_yields_no_selection(qtbot):
    dialog = ReclassLevelDialog([])
    qtbot.addWidget(dialog)
    assert dialog.selected_index() is None
