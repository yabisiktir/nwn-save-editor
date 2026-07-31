"""The Save Game Editor's Spellbook screen."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton

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


# -- adding the right spell to the right level ------------------------------ #
class _Levels:
    """Bard (class 1) casts spell 100 at level 0 and nothing else."""

    def describes(self, class_id):
        return class_id == 1

    def spells_at(self, class_id, level):
        return {100} if (class_id, level) == (1, 0) else set()


def _spy_picker(monkeypatch, screen, reject=True):
    """Capture what the Add-a-spell picker is offered, without showing it."""
    from PySide6.QtWidgets import QDialog

    import vaultkeeper.ui.dialogs.id_picker_dialog as idp

    seen = {}

    class _Spy(idp.IdPickerDialog):
        def __init__(self, title, options, **kw):
            seen["title"] = title
            seen["options"] = list(options)
            super().__init__(title, options, **kw)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(idp, "IdPickerDialog", _Spy)
    monkeypatch.setattr(screen, "_spell_levels", lambda: _Levels())
    return seen


def test_strict_offers_only_what_the_class_casts_at_that_level(window, screen, monkeypatch):
    """A save stores a spell id in a level-numbered list and nothing else, so an
    unfiltered picker let a level-6 wizard spell into a bard's level-0 list."""
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    seen = _spy_picker(monkeypatch, screen)

    book = window.session().player_spellbook()
    bard = next(c for c in book if c.class_id == 1)
    level0 = next(sl for sl in bard.lists if sl.level == 0)
    screen._add_spell(bard, level0)

    assert [sid for sid, _name in seen["options"]] == [100]


def test_free_mode_offers_everything_and_says_so(window, screen, monkeypatch):
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("free")
    seen = _spy_picker(monkeypatch, screen)

    book = window.session().player_spellbook()
    bard = next(c for c in book if c.class_id == 1)
    level0 = next(sl for sl in bard.lists if sl.level == 0)
    screen._add_spell(bard, level0)

    assert len(seen["options"]) > 1
    assert "cannot cast" in seen["title"]


def test_a_class_the_table_cannot_describe_still_offers_everything(window, screen, monkeypatch):
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    seen = _spy_picker(monkeypatch, screen)

    book = window.session().player_spellbook()
    other = next((c for c in book if c.class_id != 1), None)
    if other is None:
        pytest.skip("the fixture character has one caster class")
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    # A non-base class also asks the PRC question first; say yes without a modal.
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes
    )
    screen._add_spell(other, other.lists[0])
    assert "not in spells.2da" in seen.get("title", "")


def test_a_level_with_nothing_to_add_says_so_instead_of_an_empty_picker(
    window, screen, monkeypatch
):
    window._edit_toggle.setChecked(True)
    window._rule_mode.set_value("strict")
    _spy_picker(monkeypatch, screen)
    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a))

    book = window.session().player_spellbook()
    bard = next(c for c in book if c.class_id == 1)
    high = next((sl for sl in bard.lists if sl.level != 0), None)
    if high is None:
        pytest.skip("the fixture bard has only a level-0 list")
    screen._add_spell(bard, high)
    assert told, "an empty picker helps nobody"


# -- the whole class at once ------------------------------------------------ #
def test_the_level_row_offers_an_all_view(screen):
    screen.refresh()
    assert any(b.startswith("All") for b in _buttons(screen))


def _two_level_book():
    """A Known list at level 0 and another at level 3, on one class."""
    from vaultkeeper.game.save_editor import ClassSpellbook, SpellList

    return [ClassSpellbook(
        class_index=0, class_id=10, class_name="Wizard", is_base=True,
        lists=[
            SpellList(0, "KnownList0", "Known", 0, [(1, "Light"), (2, "Daze")]),
            SpellList(0, "KnownList3", "Known", 3, [(3, "Fireball")]),
        ],
    )]


def test_all_lists_every_level_with_its_level_shown(screen, monkeypatch):
    from vaultkeeper.ui.save_editor.screens.spellbook import ALL

    monkeypatch.setattr(screen, "_book", _two_level_book)
    screen._choose_level(ALL)
    text = _texts(screen._scroll.widget())

    assert {"Light", "Daze", "Fireball"} <= set(text.split("\n")), "every level's"
    assert "L0" in text and "L3" in text, "each row says which level it is in"
    assert "KNOWN — ALL LEVELS (3)" in text


def test_all_orders_by_level_then_name(screen, monkeypatch):
    from vaultkeeper.ui.save_editor.screens.spellbook import ALL

    monkeypatch.setattr(screen, "_book", _two_level_book)
    screen._choose_level(ALL)
    shown = [line for line in _texts(screen._scroll.widget()).split("\n")
             if line in {"Light", "Daze", "Fireball"}]
    assert shown == ["Daze", "Light", "Fireball"]


def test_all_does_not_offer_add_because_it_names_no_level(window, screen):
    from vaultkeeper.ui.save_editor.screens.spellbook import ALL

    window._edit_toggle.setChecked(True)
    screen._choose_level(ALL)
    assert not [b for b in _buttons(screen) if "Add a spell" in b]
    assert "Pick a level to add spells" in _texts(screen._scroll.widget())


def test_all_still_removes_from_the_right_level(window, screen):
    from vaultkeeper.ui.save_editor.screens.spellbook import ALL

    window._edit_toggle.setChecked(True)
    book = window.session().player_spellbook()
    chosen = book[0]
    target = next((sl for sl in chosen.lists if sl.spells), None)
    if target is None:
        pytest.skip("the fixture class knows no spells")
    spell_id = target.spells[0][0]

    screen._choose_level(ALL)
    screen._remove_spell(chosen, target, spell_id)
    keys = [c.key for c in window.session().pending_changes() if c.kind == "spell"]
    assert (chosen.class_index, target.list_field, "remove", spell_id) in keys


def test_switching_back_to_a_level_still_works(window, screen):
    from vaultkeeper.ui.save_editor.screens.spellbook import ALL

    screen._choose_level(ALL)
    screen._choose_level(0)
    assert screen._level == 0
    assert "all levels" not in _texts(screen._scroll.widget())
