"""The Save Game Editor's light/dark theme."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w
from nwnsaveeditor.ui.editor.window import SaveEditorWindow


@pytest.fixture(autouse=True)
def _restore_theme():
    """The active theme is module-level state — never let a test leak it."""
    before = t.active_theme()
    yield
    t.set_theme(before)


@pytest.fixture
def window(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save_with_details

    save = _make_char_save_with_details(tmp_path)
    written: dict[str, str] = {}

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)
        saved = written

        def set_save_editor_theme(self, name):
            written["theme"] = name

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    return editor


# -- the palettes ---------------------------------------------------------- #
def test_both_themes_exist_and_dark_is_the_default(window):
    assert set(t.THEMES) == {"dark", "light"}
    assert t.active_theme() == "dark", "an unconfigured editor opens dark"


def test_switching_swaps_every_colour_token():
    t.set_theme("dark")
    dark = {name: getattr(t, name) for name in ("APP_BG", "TEXT", "INSET", "SURFACE")}
    t.set_theme("light")
    light = {name: getattr(t, name) for name in dark}
    assert dark != light
    for name in dark:
        assert dark[name] != light[name], f"{name} is the same in both themes"


def test_light_is_light_and_dark_is_dark():
    """Guards against a light palette that is merely a slightly different dark."""

    def brightness(hex_colour: str) -> int:
        value = hex_colour.lstrip("#")
        return sum(int(value[i:i + 2], 16) for i in (0, 2, 4)) // 3

    t.set_theme("dark")
    dark_bg, dark_text = brightness(t.APP_BG), brightness(t.TEXT)
    t.set_theme("light")
    light_bg, light_text = brightness(t.APP_BG), brightness(t.TEXT)

    assert dark_bg < 60 and dark_text > 180, "dark: pale text on a dark ground"
    assert light_bg > 180 and light_text < 80, "light: dark text on a pale ground"


def test_the_shared_qss_helpers_follow_the_theme():
    t.set_theme("dark")
    dark_dialog, dark_scroll = w.dialog_qss(), w.scrollbar_qss()
    t.set_theme("light")
    assert w.dialog_qss() != dark_dialog
    assert w.scrollbar_qss() != dark_scroll


# -- the toggle ------------------------------------------------------------ #
def test_the_toolbar_offers_both_themes(window):
    assert window._theme_toggle.value() == "dark"
    window._theme_toggle.set_value("light")
    assert window._theme_toggle.value() == "light"


def test_switching_rebuilds_the_window_in_the_new_palette(window):
    window._set_theme("light")
    assert t.active_theme() == "light"
    assert window.centralWidget().styleSheet().count(t.APP_BG)


def test_switching_persists_the_choice(window):
    window._set_theme("light")
    assert window._controller.saved["theme"] == "light"


def test_switching_to_the_active_theme_is_a_no_op(window):
    window._set_theme("dark")
    assert not window._controller.saved, "nothing to persist when nothing changed"


# -- state survives the rebuild -------------------------------------------- #
def test_the_open_save_survives_a_theme_change(window):
    before = window.save
    window._set_theme("light")
    assert window.save is before
    assert before.name in window._save_label.text(), "the rebuilt toolbar names the save"


def test_the_current_section_survives_a_theme_change(window):
    window._set_section("inventory")
    window._set_theme("light")
    assert window._nav_rows["inventory"].isChecked()


def test_edit_mode_and_staged_changes_survive_a_theme_change(window):
    window._edit_toggle.setChecked(True)
    field = next(f for f in window.session().player_fields() if f.kind == "int")
    window.session().set_character_field(field.field, int(field.value) + 3, where="x")
    window.notify_changed()

    window._set_theme("light")
    assert window.editing, "the gate stays open"
    assert window._edit_toggle.isChecked()
    assert window.session().has_edits, "staged edits are not discarded by a repaint"
    assert window._pending_caption.text() == "PENDING CHANGES (1)"


def test_the_rule_mode_survives_a_theme_change(window):
    window._rule_mode.set_value("free")
    window._set_theme("light")
    assert window._rule_mode.value() == "free"
