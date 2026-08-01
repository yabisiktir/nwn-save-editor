"""The Settings screen — which folders the editor reads, and whose they are.

The point of these is the embedded case. When an application opens the editor, the
folders are that application's; a screen that let you edit them here would either
be ignored or would disagree with what the editor is actually reading.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from nwnsaveeditor.ui.editor.host import StandaloneHost
from nwnsaveeditor.ui.editor.settings import SettingsDialog
from nwnsaveeditor.ui.editor.window import SaveEditorWindow


def _window(qtbot, tmp_path, host):
    from tests.test_save_editor import _make_char_save

    window = SaveEditorWindow([_make_char_save(tmp_path)], host)
    qtbot.addWidget(window)
    return window


def _standalone(tmp_path):
    game = tmp_path / "NWN"
    game.mkdir(exist_ok=True)
    return StandaloneHost(
        game_root=game, game_user_dir=tmp_path, settings_dir=tmp_path
    )


class VaultkeeperLikeHost:
    """An application that owns the folders itself — no set_game_paths.

    Named without a leading underscore on purpose: that is how a real host is
    named, and the screen credits it by class name.
    """

    def __init__(self, tmp_path):
        self.ctx = type("Ctx", (), {"game_root": tmp_path, "game_user_dir": tmp_path})()

    def _settings(self):
        return type("S", (), {"save_editor_theme": "dark"})()

    def set_save_editor_theme(self, name):
        pass


def _texts(widget) -> str:
    return "\n".join(label.text() for label in widget.findChildren(QLabel))


def _buttons(widget) -> list[str]:
    return [b.text() for b in widget.findChildren(QPushButton)]


# -- standalone: the folders are ours ---------------------------------------- #
def test_standalone_the_folders_can_be_changed(qtbot, tmp_path):
    dialog = SettingsDialog(_window(qtbot, tmp_path, _standalone(tmp_path)))
    qtbot.addWidget(dialog)
    assert dialog.editable()
    assert "Choose…" in _buttons(dialog)
    assert "Apply" in _buttons(dialog)


def test_applying_a_new_folder_tells_the_host_and_rebuilds(qtbot, tmp_path):
    host = _standalone(tmp_path)
    window = _window(qtbot, tmp_path, host)
    dialog = SettingsDialog(window)
    qtbot.addWidget(dialog)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    rebuilt = []
    window.forget_game_tables = lambda: rebuilt.append(1)
    dialog._chosen["game_root"] = elsewhere
    dialog._apply()

    assert host.ctx.game_root == elsewhere
    assert rebuilt, "the cached 2DA/TLK tables must be dropped"


def test_the_new_folder_is_remembered_for_next_time(qtbot, tmp_path):
    host = _standalone(tmp_path)
    dialog = SettingsDialog(_window(qtbot, tmp_path, host))
    qtbot.addWidget(dialog)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    dialog._chosen["game_root"] = elsewhere
    dialog._apply()

    assert StandaloneHost(settings_dir=tmp_path).ctx.game_root == elsewhere


# -- embedded: they are the application's ------------------------------------ #
def test_embedded_the_folders_are_read_only(qtbot, tmp_path):
    """Editing them here would write somewhere the editor does not read."""
    dialog = SettingsDialog(_window(qtbot, tmp_path, VaultkeeperLikeHost(tmp_path)))
    qtbot.addWidget(dialog)

    assert not dialog.editable()
    assert "Choose…" not in _buttons(dialog)
    assert "Apply" not in _buttons(dialog), "nothing to apply — they are not ours"


def test_embedded_it_says_who_is_in_charge(qtbot, tmp_path):
    dialog = SettingsDialog(_window(qtbot, tmp_path, VaultkeeperLikeHost(tmp_path)))
    qtbot.addWidget(dialog)
    text = _texts(dialog)
    assert "VaultkeeperLikeHost" in text, "name the host rather than saying 'the app'"
    assert "no effect" in text


def test_an_unnameable_host_is_described_generically(qtbot, tmp_path):
    """A private or anonymous class name would be noise, not information."""

    class _Anonymous(VaultkeeperLikeHost):
        pass

    dialog = SettingsDialog(_window(qtbot, tmp_path, _Anonymous(tmp_path)))
    qtbot.addWidget(dialog)
    assert "managed by the application" in _texts(dialog)


def test_the_folders_are_still_shown_when_they_are_not_ours(qtbot, tmp_path):
    """Read-only is not the same as hidden — knowing where it is reading matters."""
    dialog = SettingsDialog(_window(qtbot, tmp_path, VaultkeeperLikeHost(tmp_path)))
    qtbot.addWidget(dialog)
    assert str(tmp_path) in _texts(dialog)


def test_vaultkeepers_controller_would_be_read_only():
    """It owns the game folder through its own settings, so it offers no setter."""
    pytest.importorskip("vaultkeeper")
    from vaultkeeper.ui.controller import ProfileController

    assert not hasattr(ProfileController, "set_game_paths")


# -- what a missing folder means --------------------------------------------- #
def test_a_missing_game_root_explains_what_is_lost(qtbot, tmp_path):
    host = _standalone(tmp_path)
    host.ctx.game_root = None
    dialog = SettingsDialog(_window(qtbot, tmp_path, host))
    qtbot.addWidget(dialog)
    assert "raw ids" in _texts(dialog)


def test_the_theme_lives_here_too(qtbot, tmp_path):
    dialog = SettingsDialog(_window(qtbot, tmp_path, _standalone(tmp_path)))
    qtbot.addWidget(dialog)
    assert "Dark" in _buttons(dialog) and "Light" in _buttons(dialog)


def test_the_toolbar_offers_it(qtbot, tmp_path):
    window = _window(qtbot, tmp_path, _standalone(tmp_path))
    assert "Settings…" in [b.text() for b in window.findChildren(QPushButton)]


def test_changing_folders_drops_the_cached_tables(qtbot, tmp_path):
    """They are built once from the game folder; a new folder must re-read them."""
    window = _window(qtbot, tmp_path, _standalone(tmp_path))
    window.property_tables()
    window.look_tables()
    window.forget_game_tables()

    from nwnsaveeditor.ui.editor.window import _UNSET

    assert window._prop_tables is _UNSET
    assert window._look_tables is _UNSET


def test_a_path_is_shown_even_before_anything_is_chosen(qtbot, tmp_path):
    dialog = SettingsDialog(_window(qtbot, tmp_path, _standalone(tmp_path)))
    qtbot.addWidget(dialog)
    assert str(tmp_path) in _texts(dialog)
    assert dialog._chosen == {}, "browsing is what stages a change, not opening"


def test_apply_with_nothing_chosen_changes_nothing(qtbot, tmp_path):
    host = _standalone(tmp_path)
    before = host.ctx.game_root
    dialog = SettingsDialog(_window(qtbot, tmp_path, host))
    qtbot.addWidget(dialog)
    dialog._apply()
    assert host.ctx.game_root == before


def test_choosing_nothing_in_the_browser_leaves_it_alone(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    dialog = SettingsDialog(_window(qtbot, tmp_path, _standalone(tmp_path)))
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    dialog._browse("game_root", "Game installation")
    assert dialog._chosen == {}


def test_browsing_stages_the_choice_without_applying_it(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    host = _standalone(tmp_path)
    before = host.ctx.game_root
    dialog = SettingsDialog(_window(qtbot, tmp_path, host))
    qtbot.addWidget(dialog)
    picked = tmp_path / "picked"
    picked.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(picked))

    dialog._browse("game_root", "Game installation")
    assert dialog._chosen["game_root"] == picked
    assert host.ctx.game_root == before, "not applied until Apply"
    assert str(picked) in _texts(dialog), "but shown so you can see what you picked"


def test_set_game_paths_can_change_one_folder_without_clearing_the_other(tmp_path):
    host = _standalone(tmp_path)
    user_before = host.ctx.game_user_dir
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    host.set_game_paths(game_root=elsewhere)
    assert host.ctx.game_root == elsewhere
    assert host.ctx.game_user_dir == user_before


def test_a_path_is_a_Path_not_a_string(tmp_path):
    host = _standalone(tmp_path)
    host.set_game_paths(game_root=tmp_path / "x")
    assert isinstance(host.ctx.game_root, Path)
