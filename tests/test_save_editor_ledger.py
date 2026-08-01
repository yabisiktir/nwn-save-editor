"""The change-ledger slide-over and the toolbar's Undo/Redo."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from nwnsaveeditor.ui.editor.window import SaveEditorWindow


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save_with_details

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([_make_char_save_with_details(tmp_path)], _Ctrl())
    qtbot.addWidget(editor)
    editor._edit_toggle.setChecked(True)
    return editor


def _value(window, field):
    return next(f for f in window.session().player_fields() if f.field == field).value


def _ledger_text(window) -> str:
    return "\n".join(label.text() for label in window._ledger.findChildren(QLabel))


def _row_buttons(window) -> list[str]:
    return [b.text() for b in window._ledger._scroll.widget().findChildren(QPushButton)]


# -- toolbar wiring -------------------------------------------------------- #
def test_undo_and_redo_are_disabled_until_there_is_a_stack(window):
    assert not window._undo_btn.isEnabled()
    assert not window._redo_btn.isEnabled()

    window.session().set_character_field("Gold", _value(window, "Gold") + 1, where="Gold")
    window.notify_changed()
    assert window._undo_btn.isEnabled()
    assert not window._redo_btn.isEnabled()

    window._undo()
    assert not window._undo_btn.isEnabled()
    assert window._redo_btn.isEnabled()


def test_toolbar_undo_reverses_the_edit_and_updates_the_footer(window):
    gold = _value(window, "Gold")
    window.session().set_character_field("Gold", gold + 5, where="Gold")
    window.notify_changed()
    assert window._pending_caption.text() == "PENDING CHANGES (1)"

    window._undo()
    assert _value(window, "Gold") == gold
    assert window._pending_caption.text() == "PENDING CHANGES (0)"


def test_review_is_enabled_once_there_is_something_to_review(window):
    assert not window._review_btn.isEnabled()
    window.session().set_character_field("Gold", _value(window, "Gold") + 1, where="Gold")
    window.notify_changed()
    assert window._review_btn.isEnabled()


def test_review_stays_enabled_when_every_change_is_undone(window):
    """An undone change is still worth reviewing — the design keeps it visible."""
    window.session().set_character_field("Gold", _value(window, "Gold") + 1, where="Gold")
    window.notify_changed()
    window._undo()
    assert not window.session().has_edits
    assert window._review_btn.isEnabled()


# -- the slide-over -------------------------------------------------------- #
def test_the_ledger_starts_hidden_and_toggles(window):
    window.show()
    assert not window._ledger.isVisible()
    window._toggle_ledger()
    assert window._ledger.isVisible()
    window._toggle_ledger()
    assert not window._ledger.isVisible()


def test_the_ledger_lists_each_staged_change_with_its_summary(window):
    session = window.session()
    session.set_character_field("Gold", _value(window, "Gold") + 1, where="Gold")
    skill = session.player_skills()[0]
    session.set_skill_rank(skill.index, skill.rank + 3, where=skill.name)
    window.notify_changed()
    window._toggle_ledger()

    text = _ledger_text(window)
    assert "Gold" in text
    assert skill.name in text
    assert "2 to write" in text


def test_undone_changes_are_listed_but_not_counted(window):
    session = window.session()
    session.set_character_field("Gold", _value(window, "Gold") + 1, where="Gold")
    session.set_character_field("Str", _value(window, "Str") + 1, where="Strength")
    window.notify_changed()
    window._undo()
    window._toggle_ledger()

    text = _ledger_text(window)
    assert "1 to write" in text
    assert "1 undone (not written)" in text
    assert "Strength" in text, "an undone change stays visible"
    assert "undone — not written" in text


def test_an_undone_row_offers_no_discard(window):
    """Discard reverses a staged change; an undone one has nothing left to drop."""
    session = window.session()
    session.set_character_field("Gold", _value(window, "Gold") + 1, where="Gold")
    window.notify_changed()
    window._undo()
    window._toggle_ledger()
    assert "Discard" not in _row_buttons(window)


def test_discarding_a_row_drops_only_that_change(window):
    session = window.session()
    gold, strength = _value(window, "Gold"), _value(window, "Str")
    session.set_character_field("Gold", gold + 1, where="Gold")
    session.set_character_field("Str", strength + 1, where="Strength")
    window.notify_changed()
    window._toggle_ledger()

    change = next(c for c in session.pending_changes() if c.key == "Gold")
    window._ledger._on_discard(change)

    assert _value(window, "Gold") == gold
    assert _value(window, "Str") == strength + 1
    assert window._pending_caption.text() == "PENDING CHANGES (1)"


def test_the_empty_ledger_says_so(window):
    window._toggle_ledger()
    assert "Nothing staged yet." in _ledger_text(window)


def test_discard_all_and_save_are_inert_with_nothing_staged(window):
    window._toggle_ledger()
    assert not window._ledger._discard_all.isEnabled()
    assert not window._ledger._save.isEnabled()


def test_the_ledger_follows_the_window_when_it_resizes(window):
    window.show()
    window._toggle_ledger()
    window.resize(1200, 800)
    window._ledger.reposition()
    assert window._ledger.geometry().right() <= window.width()
    assert window._ledger.geometry().top() > 0, "it sits below the toolbar"
