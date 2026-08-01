"""The Property Reference screen — read-only discovery over the iprp_* tables."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QPushButton, QSpinBox

from nwnsaveeditor.ui.editor.window import SaveEditorWindow


class _Tables:
    """A stand-in for ItemPropertyTables with two properties."""

    available = True

    def property_ids(self):
        return [0, 52]

    def property_name_label(self, pid):
        return {0: "Ability", 52: "Skill"}.get(pid)

    def cost_table_for(self, pid):
        return {0: 1, 52: 25}.get(pid)

    def cost_options(self, table):
        return {1: "+1", 2: "+2"} if table is not None else {}

    def subtype_options(self, pid):
        return {0: "Strength", 1: "Dexterity"} if pid == 0 else None

    def param1_options(self, pid):
        return None


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    from tests.test_save_editor import _make_char_save

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

    editor = SaveEditorWindow([_make_char_save(tmp_path)], _Ctrl())
    qtbot.addWidget(editor)
    monkeypatch.setattr(editor, "property_tables", lambda: _Tables())
    return editor


@pytest.fixture
def screen(window):
    """The reference lives inside Raw Data, not in the sidebar."""
    screen = window._screens["raw"]._reference
    screen.refresh()
    return screen


def _texts(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def test_it_lists_the_games_property_types(screen):
    text = _texts(screen)
    assert "Ability" in text
    assert "Skill" in text


def test_selecting_a_property_shows_its_valid_values(screen):
    screen._choose(0)
    text = _texts(screen._detail_scroll.widget())
    assert "Strength" in text, "its subtypes"
    assert "+1" in text, "its accepted magnitudes"
    assert "row 0" in text, "and the row each option really is"


def test_a_property_with_no_subtypes_says_so(screen):
    screen._choose(52)
    text = _texts(screen._detail_scroll.widget())
    assert "takes no subtypes" in text


def test_it_reports_which_of_your_items_carry_a_property(window, screen):
    """The question the editor could not answer before: where is this on me?"""
    carried = {
        entry.prop.property_name
        for item in window.session().player_items()
        for entry in item.properties
    }
    if not carried:
        pytest.skip("the fixture character has no item properties")
    pid = next(iter(carried))
    assert screen._uses(pid), "a property the character carries must be located"


def test_a_property_nobody_carries_says_so(window, screen, monkeypatch):
    monkeypatch.setattr(screen, "_uses", lambda _pid: [])
    screen._choose(0)
    assert "None of your items carry this." in _texts(screen._detail_scroll.widget())


def test_the_filter_narrows_the_list(screen):
    screen._set_filter("skill")
    text = _texts(screen)
    assert "Skill" in text
    assert "Ability" not in text


def test_the_filter_also_matches_a_raw_id(screen):
    screen._set_filter("52")
    assert "Skill" in _texts(screen)


def test_the_screen_offers_no_way_to_edit(window, screen):
    """It is a reference. Editing item properties belongs to the item panel."""
    window._edit_toggle.setChecked(True)
    screen.refresh()
    assert not screen.findChildren(QSpinBox)
    assert not [b for b in screen.findChildren(QPushButton) if b.text()]


def test_unreadable_tables_explain_themselves(window, monkeypatch):
    monkeypatch.setattr(window, "property_tables", lambda: None)
    screen = window._screens["raw"]._reference
    screen.refresh()
    assert "could not be read" in _texts(screen)


# -- where it lives --------------------------------------------------------- #
def test_it_is_not_its_own_sidebar_section(window):
    """Leaving Raw Data to look up a property id defeats the point of looking it
    up, so it is a companion panel rather than a destination."""
    from nwnsaveeditor.ui.editor.sections import SECTIONS

    assert "properties" not in {section.key for section in SECTIONS}


def test_raw_data_hides_it_until_asked(window):
    raw = window._screens["raw"]
    assert raw._reference.isHidden()
    assert raw._reference_button.text() == "Property reference ›"


def test_the_toggle_shows_it_beside_the_tree(window):
    raw = window._screens["raw"]
    raw._toggle_reference()
    assert not raw._reference.isHidden()
    assert not raw._tree.isHidden(), "beside the tree, not instead of it"
    assert raw._reference_button.text() == "‹ Hide reference"

    raw._toggle_reference()
    assert raw._reference.isHidden()


def test_it_refreshes_with_the_screen_only_while_shown(window, monkeypatch):
    raw = window._screens["raw"]
    calls = []
    monkeypatch.setattr(raw._reference, "refresh", lambda: calls.append(1))
    raw.refresh()
    assert not calls, "a hidden panel must not pay for every tree rebuild"
