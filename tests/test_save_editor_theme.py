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


# -- inheriting an embedding host's theme (Vaultkeeper) --------------------- #
def test_an_embedding_host_can_dictate_the_theme(qtbot, tmp_path):
    """A host with editor_theme() opens the editor matching it, not its own
    remembered choice — Vaultkeeper passing its resolved light/dark down."""
    from tests.test_save_editor import _make_char_save_with_details

    save = _make_char_save_with_details(tmp_path)

    class _HostCtrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def set_save_editor_theme(self, name):
            pass

        def _settings(self):
            return SimpleNamespace(save_editor_theme="dark")  # would be dark…

        def editor_theme(self):
            return "light"  # …but the host says light, and the host wins

    editor = SaveEditorWindow([save], _HostCtrl())
    qtbot.addWidget(editor)
    assert t.active_theme() == "light"


def test_without_the_host_hook_the_saved_theme_still_wins(qtbot, tmp_path):
    """Standalone, or any host without editor_theme(), uses save_editor_theme."""
    from tests.test_save_editor import _make_char_save_with_details

    save = _make_char_save_with_details(tmp_path)

    class _Ctrl:
        ctx = SimpleNamespace(game_root=tmp_path / "NWN", game_user_dir=tmp_path)

        def set_save_editor_theme(self, name):
            pass

        def _settings(self):
            return SimpleNamespace(save_editor_theme="light")

    editor = SaveEditorWindow([save], _Ctrl())
    qtbot.addWidget(editor)
    assert t.active_theme() == "light"


def _shown_tooltip():
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        if widget.metaObject().className() == "QTipLabel" and widget.isVisible():
            return widget
    return None


def _purge_tooltips():
    """Delete the shared QTipLabel singleton between passes.

    ``QToolTip.hideText`` only *hides* it; reused in the next pass it can be picked
    up before the new owner's stylesheet re-polishes it, so a light pass reads the
    dark pass's colours (dark on CI, fine on macOS).
    """
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    for widget in QApplication.topLevelWidgets():
        if widget.metaObject().className() == "QTipLabel":
            widget.deleteLater()
    # ``deleteLater`` only *posts*; QToolTip keeps a static pointer to the label and
    # hands the same one back until it is really gone, so flush the deferred deletes
    # rather than trusting one processEvents pass.
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def _tooltip_look(owner, text: str):
    """Show ``owner``'s tooltip and return what it actually looks like."""
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication, QToolTip

    _purge_tooltips()
    QToolTip.showText(QPoint(20, 20), text, owner)
    QApplication.processEvents()
    tip = _shown_tooltip()
    assert tip is not None, "no tooltip was shown"
    font, palette = tip.font(), tip.palette()
    margins = tip.contentsMargins()
    look = (
        font.family(), font.pixelSize(), font.weight(),
        palette.color(QPalette.ColorRole.ToolTipBase).name(),
        palette.color(QPalette.ColorRole.ToolTipBase).alpha(),
        palette.color(QPalette.ColorRole.ToolTipText).name(),
        (margins.left(), margins.top(), margins.right(), margins.bottom()),
    )
    QToolTip.hideText()
    return look


def test_tooltips_are_readable_in_both_themes(window, qtbot):
    """A QToolTip has no stylesheet of its own; without a theme-aware rule it fell
    back to the OS palette and rendered dark-on-dark in light mode (reported).

    Driven through the window the editor actually builds — an earlier version of
    this test applied ``tooltip_qss`` to a bare QMainWindow itself, so it passed
    while nothing in the editor was applying that rule at all.
    """
    from PySide6.QtGui import QColor

    for theme in ("dark", "light"):
        window._set_theme(theme)
        assert t.active_theme() == theme
        _purge_tooltips()
        _, _, _, background, alpha, text, _ = _tooltip_look(
            window._open_btn, "Open another save"
        )
        assert alpha == 255, f"{theme}: tooltip background is see-through"
        assert background == t.SURFACE.lower(), f"{theme}: tooltip background not themed"
        assert text == t.TEXT.lower(), f"{theme}: tooltip text not themed"
        # …and readable against it, not merely themed.
        back, front = QColor(background), QColor(text)
        assert abs(back.lightness() - front.lightness()) > 90, (
            f"{theme}: tooltip text does not contrast with its background"
        )
    _purge_tooltips()


def test_every_tooltip_in_the_editor_looks_the_same(window, qtbot):
    """One tooltip appearance per theme, across every section.

    Qt resolves a tooltip's style from the stylesheet cascade of the widget it is
    shown *for*, so unscoped widget QSS ("font-size:12.5px;background:transparent;")
    used to hand its font and its transparency straight to the tooltip: hovering a
    heading gave a 16px tooltip, an inventory cell a 9px one with the cell's gold
    border, and anything painted ``background:transparent`` gave a tooltip with no
    background at all — fourteen appearances in all, several unreadable.

    ``widgets.own_style`` scopes those declarations to the widget's own exact class,
    which a ``QTipLabel`` (a QLabel *subclass*) does not match. This is the guard on
    that: it cannot be fixed from above, because a ``QToolTip`` rule on the window —
    or even on the application — loses to any nearer declaration.
    """
    import shiboken6
    from PySide6.QtWidgets import QApplication, QWidget

    window.resize(1400, 900)
    window.show()
    qtbot.waitExposed(window)

    for theme in ("dark", "light"):
        window._set_theme(theme)
        assert t.active_theme() == theme
        QApplication.processEvents()  # the switch rebuilds the shell
        looks: dict[tuple, str] = {}
        for key, row in list(window._nav_rows.items()):
            row.click()
            QApplication.processEvents()
            # Snapshot first: showing a tooltip pumps the event loop, which drops the
            # widgets a screen rebuild retired — iterating findChildren lazily walks
            # into one of those and raises "C++ object already deleted".
            targets = [
                (wdg, wdg.toolTip())
                for wdg in window.findChildren(QWidget)
                if wdg.toolTip() and wdg.isVisible()
            ]
            for widget, tip in targets:
                if not shiboken6.isValid(widget):
                    continue
                looks.setdefault(
                    _tooltip_look(widget, tip),
                    f"{key}: {widget.metaObject().className()} — {tip[:40]!r}",
                )
        assert len(looks) == 1, (
            f"{theme}: {len(looks)} different tooltip appearances:\n  "
            + "\n  ".join(f"{look} <- {where}" for look, where in looks.items())
        )
    _purge_tooltips()


def test_dialog_tooltips_match_the_window_s(qtbot):
    """A dialog is a separate top-level with its own cascade, so it needs the rule
    too — ``dialog_qss`` carries it, and the two bare dialogs set it themselves."""
    from PySide6.QtWidgets import QDialog, QLabel, QSpinBox, QVBoxLayout

    from nwnsaveeditor.ui.editor.screens import item_panels as ip

    for theme in ("dark", "light"):
        t.set_theme(theme)
        dialog = w.style_dialog(QDialog())
        layout = QVBoxLayout(dialog)
        widgets = [
            w.body("x"), w.heading("H"), w.mono("m"), w.prc_badge(),
            ip.item_cell("L", filled=True, selected=False, tooltip="tip"),
            w.ghost_button("Go"), QSpinBox(), QLabel("plain"),
        ]
        for widget in widgets:
            if not widget.toolTip():
                widget.setToolTip("An enhancement bonus of +2")
            layout.addWidget(widget)
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.waitExposed(dialog)

        looks = {_tooltip_look(widget, widget.toolTip()) for widget in widgets}
        assert len(looks) == 1, f"{theme}: dialog tooltips differ: {looks}"
        background, alpha = looks.copy().pop()[3], looks.copy().pop()[4]
        assert (background, alpha) == (t.SURFACE.lower(), 255), (
            f"{theme}: a dialog tooltip is not on the themed surface"
        )
        dialog.close()
    _purge_tooltips()


def test_a_widget_stylesheet_cannot_leak_into_its_tooltip(qtbot):
    """``own_style`` keeps the widget's look and drops nothing but the leak."""
    from PySide6.QtWidgets import QLabel

    t.set_theme("dark")
    css = f"font-family:{t.UI_FAMILY};font-size:20px;color:{t.GOLD};background:transparent;"

    from PySide6.QtWidgets import QVBoxLayout, QWidget

    host = QWidget()
    layout = QVBoxLayout(host)
    bare = QLabel("Sample")
    bare.setStyleSheet(css)
    scoped = w.own_style(QLabel("Sample"), css)
    layout.addWidget(bare)
    layout.addWidget(scoped)
    qtbot.addWidget(host)
    host.show()
    qtbot.waitExposed(host)  # an unshown widget has not resolved its stylesheet font

    # The widget itself is untouched by the scoping…
    assert scoped.font().pixelSize() == bare.font().pixelSize() == 20
    assert scoped.sizeHint() == bare.sizeHint()
    # …while only the bare one hands its font and its transparency to the tooltip.
    assert _tooltip_look(bare, "tip")[1] == 20, "the leak this guards against is gone"
    assert _tooltip_look(scoped, "tip")[1] != 20, "the widget's font reached its tooltip"
    _purge_tooltips()


def test_message_boxes_follow_the_theme(qtbot):
    """A QMessageBox is a separate top-level and misses the dialog styling, so it
    fell back to the OS palette. The window's scoped rule must reach it."""
    from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QWidget

    for theme in ("dark", "light"):
        t.set_theme(theme)
        win = QMainWindow()
        win.setStyleSheet(f"QMainWindow{{background:{t.APP_BG};}}" + w.message_box_qss())
        win.setCentralWidget(QWidget())
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)

        box = QMessageBox(
            QMessageBox.Icon.Question, "Discard?", "Discard 1 change.",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, win,
        )
        qtbot.addWidget(box)
        box.show()
        qtbot.waitExposed(box)

        box_bg = box.palette().color(box.palette().ColorRole.Window).name().lower()
        assert box_bg == t.APP_BG.lower(), f"{theme}: message box background not themed"
        label = next(lbl for lbl in box.findChildren(QLabel) if "Discard" in lbl.text())
        text = label.palette().color(label.palette().ColorRole.WindowText).name().lower()
        assert text == t.TEXT.lower(), f"{theme}: message text not themed"
        box.close()
