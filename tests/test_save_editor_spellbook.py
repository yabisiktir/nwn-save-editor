"""The Save Game Editor's Spellbook screen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from vaultkeeper.ui.save_editor.screens.spellbook import SpellbookScreen
from vaultkeeper.ui.save_editor.window import SaveEditorWindow


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save

    save = _make_char_save(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


@pytest.fixture
def screen(window) -> SpellbookScreen:
    return window._screens["spellbook"]


def _texts(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def _buttons(widget) -> list[str]:
    return [b.text() for b in widget.findChildren(QPushButton)]


def test_a_caster_class_is_selected_by_default(window, screen):
    book = window.session().player_spellbook()
    assert book, "the fixture character should have a spellbook"
    assert screen._class_index == book[0].class_index
    assert screen._level is not None


def test_the_level_buttons_count_the_spells_at_each_level(window, screen):
    book = window.session().player_spellbook()
    chosen = next(c for c in book if c.class_index == screen._class_index)
    levels = sorted({sl.level for sl in chosen.lists})
    labels = _buttons(screen._scroll.widget())
    for level in levels:
        count = sum(len(sl.spells) for sl in chosen.lists if sl.level == level)
        assert any(f"L{level}" in text and f"({count})" in text for text in labels)


def test_known_and_memorized_are_shown_as_separate_groups(window, screen):
    """A class can hold both; merging them would misreport what is prepared."""
    book = window.session().player_spellbook()
    chosen = next(c for c in book if c.class_index == screen._class_index)
    kinds = {sl.kind for sl in chosen.lists if sl.level == screen._level}
    text = _texts(screen._scroll.widget()).lower()  # cap_label uppercases headings
    assert kinds
    for kind in kinds:
        assert kind.lower() in text


def test_add_and_remove_appear_only_in_edit_mode(window, screen):
    assert "+ Add a spell…" not in _buttons(screen._scroll.widget())
    assert "×" not in _buttons(screen._scroll.widget())
    window._edit_toggle.setChecked(True)
    assert "+ Add a spell…" in _buttons(screen._scroll.widget())


def test_removing_a_spell_stages_it(window, screen):
    window._edit_toggle.setChecked(True)
    book = window.session().player_spellbook()
    chosen = next(c for c in book if c.class_index == screen._class_index)
    spell_list = next(sl for sl in chosen.lists if sl.spells)
    spell_id = spell_list.spells[0][0]

    screen._remove_spell(chosen, spell_list, spell_id)
    changes = window.session().pending_changes()
    assert [c.kind for c in changes] == ["spell"]
    assert changes[0].summary == "remove spell"


def test_a_staged_addition_marks_its_row(window, screen):
    """Guards the key shape: the session keys spell changes with a verb in the
    middle, so a naive (class, list, id) lookup would never match and no row
    would ever show the ● marker."""
    window._edit_toggle.setChecked(True)
    book = window.session().player_spellbook()
    chosen = next(c for c in book if c.class_index == screen._class_index)
    spell_list = next(sl for sl in chosen.lists if sl.spells)
    existing = {sid for sid, _name in spell_list.spells}
    new_id = next(i for i in range(1, 500) if i not in existing)

    window.session().add_spell(chosen.class_index, spell_list.list_field, new_id)
    window.notify_changed()
    assert (chosen.class_index, spell_list.list_field, new_id) in screen._pending_spell_keys()


def test_a_prc_spellbook_warns_before_staging(window, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    book = window.session().player_spellbook()
    chosen = next(c for c in book if c.class_index == screen._class_index)
    spell_list = next(sl for sl in chosen.lists if sl.spells)
    object.__setattr__(chosen, "is_base", False)  # treat it as PRC for this check

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    screen._remove_spell(chosen, spell_list, spell_list.spells[0][0])
    assert not window.session().has_edits, "declining the PRC warning must stage nothing"


def test_switching_class_resets_the_level(window, screen):
    screen._choose_level(screen._level)
    screen._choose_class(screen._class_index)
    assert screen._level is not None, "a level is always chosen after a class switch"


def test_a_character_with_no_spellbook_says_so(qtbot, tmp_path, monkeypatch):
    """A non-caster must get the empty state, not a crash or a blank screen."""
    from tests.test_save_editor import _make_char_save

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([_make_char_save(tmp_path)], _Ctrl())
    qtbot.addWidget(editor)
    screen = editor._screens["spellbook"]
    monkeypatch.setattr(screen, "_book", list)
    screen.refresh()
    assert "no caster class" in _texts(screen._scroll.widget())
