"""Running the save editor without a Vaultkeeper application.

The editor is a save editor Vaultkeeper launches, not a part of Vaultkeeper. What
holds that true is the small host protocol — so these tests pin the surface, not
the implementation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nwnsaveeditor.ui.editor.__main__ import collect_saves, main, parse_args
from nwnsaveeditor.ui.editor.host import (
    EditorHost,
    StandaloneHost,
    default_settings_dir,
)


# -- the host surface -------------------------------------------------------- #
def test_the_standalone_host_satisfies_the_protocol(tmp_path):
    host = StandaloneHost(game_root=tmp_path, game_user_dir=tmp_path, settings_dir=tmp_path)
    assert isinstance(host, EditorHost)


def test_the_editor_opens_with_nothing_but_a_host(qtbot, tmp_path):
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow
    from tests.test_save_editor import _make_char_save

    host = StandaloneHost(game_root=None, game_user_dir=None, settings_dir=tmp_path)
    window = SaveEditorWindow([_make_char_save(tmp_path)], host)
    qtbot.addWidget(window)

    assert window.session().player_fields(), "the character reads without a game folder"
    for key in ("character", "inventory", "spellbook", "raw"):
        assert window._screens[key] is not None


# -- its own settings -------------------------------------------------------- #
def test_the_theme_is_remembered_between_runs(tmp_path):
    StandaloneHost(settings_dir=tmp_path).set_save_editor_theme("light")
    assert StandaloneHost(settings_dir=tmp_path)._settings().save_editor_theme == "light"


def test_it_does_not_write_to_vaultkeepers_settings(tmp_path):
    """The app may have its settings file open; a standalone run must not touch it."""
    host = StandaloneHost(settings_dir=tmp_path)
    host.set_save_editor_theme("light")
    written = list(tmp_path.iterdir())
    assert [p.name for p in written] == ["save_editor.json"]


def test_an_unknown_theme_is_refused_rather_than_stored(tmp_path):
    host = StandaloneHost(settings_dir=tmp_path)
    host.set_save_editor_theme("chartreuse")

    assert host._settings().save_editor_theme == "dark"
    # The file exists either way now — the constructor writes it to remember
    # where the game is — so what matters is that the bad value is not in it.
    saved = json.loads((tmp_path / "save_editor.json").read_text(encoding="utf-8"))
    assert saved["save_editor_theme"] == "dark"


def test_a_corrupt_settings_file_falls_back_to_dark(tmp_path):
    (tmp_path / "save_editor.json").write_text("{not json", encoding="utf-8")
    assert StandaloneHost(settings_dir=tmp_path)._settings().save_editor_theme == "dark"


def test_an_unwritable_settings_dir_does_not_take_the_editor_down(tmp_path):
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("", encoding="utf-8")
    host = StandaloneHost(settings_dir=blocked / "nested")
    host.set_save_editor_theme("light")  # must not raise
    assert host._settings().save_editor_theme == "light", "in memory for this run"


def test_the_settings_dir_is_not_the_working_directory():
    assert default_settings_dir().is_absolute()


# -- the command line -------------------------------------------------------- #
def test_named_save_folders_are_opened(tmp_path):
    from tests.test_save_editor import _make_char_save

    save = _make_char_save(tmp_path)
    assert [s.folder for s in collect_saves([save.folder], None)] == [save.folder]


def test_a_path_that_is_not_a_save_folder_is_skipped(tmp_path):
    assert collect_saves([tmp_path / "nope"], None) == []


def test_with_no_arguments_it_scans_the_user_directory(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        "nwnsaveeditor.save_game.scan_save_games",
        lambda folder: seen.setdefault("folder", folder) or [],
    )
    collect_saves([], tmp_path)
    assert seen["folder"] == tmp_path / "saves"


def test_the_arguments_are_what_a_person_would_expect():
    args = parse_args(["--game-root", "/g", "--user-dir", "/u", "/saves/one"])
    assert args.game_root == Path("/g")
    assert args.user_dir == Path("/u")
    assert args.saves == [Path("/saves/one")]


def test_no_saves_explains_where_it_looked(tmp_path, monkeypatch):
    """A blank window would leave a wrong user directory undiagnosable."""
    from PySide6.QtWidgets import QMessageBox

    told = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: told.append(a))
    monkeypatch.setattr(
        "nwnsaveeditor.ui.editor.__main__.collect_saves", lambda *a: []
    )
    assert main(["--user-dir", str(tmp_path)]) == 1
    assert told and str(tmp_path) in told[0][2]


def test_the_console_script_points_at_this_entry_point():
    import tomllib

    root = Path(__file__).resolve().parents[1]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["gui-scripts"]
    assert scripts["nwn-save-editor"] == "nwnsaveeditor.ui.editor.__main__:main"


@pytest.mark.parametrize("payload", ['{"save_editor_theme": "light"}', "{}"])
def test_a_settings_file_is_read_leniently(tmp_path, payload):
    (tmp_path / "save_editor.json").write_text(payload, encoding="utf-8")
    theme = StandaloneHost(settings_dir=tmp_path)._settings().save_editor_theme
    assert theme in {"dark", "light"}
    assert json.loads(payload) is not None  # the payload really is what we wrote


# -- portraits --------------------------------------------------------------- #
def _portrait_window(qtbot, tmp_path, user_dir):
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow
    from tests.test_save_editor import _make_char_save

    # An explicit empty game root: passing None makes StandaloneHost go looking
    # for a real install, which would make these depend on the machine.
    game_root = tmp_path / "NWN"
    game_root.mkdir(exist_ok=True)
    host = StandaloneHost(
        game_root=game_root, game_user_dir=user_dir, settings_dir=tmp_path
    )
    window = SaveEditorWindow([_make_char_save(tmp_path)], host)
    qtbot.addWidget(window)
    return window


def test_the_editor_finds_a_portrait_without_a_host_lookup(qtbot, tmp_path):
    """It used to delegate the whole search to a host method only an application
    had, so running on its own showed no portrait even with the file right there."""
    user = tmp_path / "user"
    (user / "portraits").mkdir(parents=True)
    (user / "portraits" / "hero_m.tga").write_bytes(b"not a real tga")

    window = _portrait_window(qtbot, tmp_path, user)
    assert window.portrait_path("hero_") == user / "portraits" / "hero_m.tga"


def test_it_searches_nwns_folders_nearest_first(qtbot, tmp_path):
    user = tmp_path / "user"
    for name in ("ovr", "override", "portraits"):
        (user / name).mkdir(parents=True)
    window = _portrait_window(qtbot, tmp_path, user)
    names = [d.name for d in window.portrait_dirs()]
    assert names == ["ovr", "override", "portraits"]


def test_the_save_folder_is_searched_first_because_a_save_can_carry_its_own(
    qtbot, tmp_path
):
    user = tmp_path / "user"
    (user / "portraits").mkdir(parents=True)
    window = _portrait_window(qtbot, tmp_path, user)
    dirs = window.portrait_dirs(window.save)
    assert dirs[0] == window.save.folder


def test_a_host_that_knows_better_is_preferred(qtbot, tmp_path):
    """An application may know about portraits its own installs put down."""
    user = tmp_path / "user"
    (user / "portraits").mkdir(parents=True)
    (user / "portraits" / "hero_m.tga").write_bytes(b"x")
    window = _portrait_window(qtbot, tmp_path, user)

    theirs = tmp_path / "from-the-host.tga"
    window._controller.portrait_path = lambda resref, extra_dirs=(): theirs
    assert window.portrait_path("hero_") == theirs


def test_a_host_lookup_that_raises_falls_back_rather_than_showing_nothing(
    qtbot, tmp_path
):
    user = tmp_path / "user"
    (user / "portraits").mkdir(parents=True)
    (user / "portraits" / "hero_m.tga").write_bytes(b"x")
    window = _portrait_window(qtbot, tmp_path, user)

    def _boom(resref, extra_dirs=()):
        raise RuntimeError("host is confused")

    window._controller.portrait_path = _boom
    assert window.portrait_path("hero_") == user / "portraits" / "hero_m.tga"


def test_a_character_with_no_portrait_resref_asks_for_nothing(qtbot, tmp_path):
    window = _portrait_window(qtbot, tmp_path, tmp_path / "user")
    assert window.portrait_path("") is None


# -- remembering where the game is ------------------------------------------- #
def _fake_game(tmp_path, name="NWN"):
    root = tmp_path / name
    (root / "data").mkdir(parents=True)
    return root


def test_a_path_passed_on_the_command_line_is_remembered(tmp_path):
    """Otherwise every launch needs the flag again on a machine where detection
    guesses wrong, or where the game sits somewhere unusual."""
    root = _fake_game(tmp_path)
    StandaloneHost(game_root=root, game_user_dir=tmp_path, settings_dir=tmp_path)

    again = StandaloneHost(settings_dir=tmp_path)
    assert again.ctx.game_root == root
    assert again.ctx.game_user_dir == tmp_path


def test_what_you_pass_beats_what_was_saved(tmp_path):
    first, second = _fake_game(tmp_path, "one"), _fake_game(tmp_path, "two")
    StandaloneHost(game_root=first, settings_dir=tmp_path)
    host = StandaloneHost(game_root=second, settings_dir=tmp_path)
    assert host.ctx.game_root == second
    assert StandaloneHost(settings_dir=tmp_path).ctx.game_root == second


def test_a_remembered_path_that_has_gone_falls_back_to_detection(tmp_path, monkeypatch):
    """An unplugged drive or an uninstalled game must not pin the editor to
    somewhere empty for good."""
    vanished = _fake_game(tmp_path, "gone")
    StandaloneHost(game_root=vanished, settings_dir=tmp_path)
    shutil.rmtree(vanished)

    detected = _fake_game(tmp_path, "detected")
    monkeypatch.setattr(
        "nwnsaveeditor.ui.editor.host.default_game_root", lambda: detected
    )
    assert StandaloneHost(settings_dir=tmp_path).ctx.game_root == detected


def test_remembering_paths_does_not_forget_the_theme(tmp_path):
    root = _fake_game(tmp_path)
    host = StandaloneHost(game_root=root, settings_dir=tmp_path)
    host.set_save_editor_theme("light")

    again = StandaloneHost(settings_dir=tmp_path)
    assert again._settings().save_editor_theme == "light"
    assert again.ctx.game_root == root


def test_the_user_directory_is_looked_for_where_each_platform_keeps_it():
    """Enhanced Edition on Linux uses ~/.local/share, not Documents — guessing
    Documents everywhere finds nothing there."""
    from nwnfile.locations import HostOS, user_documents_dir

    linux = user_documents_dir(HostOS.LINUX)
    assert linux.parts[-3:] == (".local", "share", "Neverwinter Nights")
    for host in (HostOS.MACOS, HostOS.WINDOWS):
        assert user_documents_dir(host).parts[-2:] == ("Documents", "Neverwinter Nights")


def test_detection_is_delegated_rather_than_guessed_at(monkeypatch):
    """It walks Steam library folders, GOG/Beamdog and Wine prefixes, and checks
    each candidate really looks like an NWN root."""
    import nwnsaveeditor.ui.editor.host as host_mod

    called = []
    monkeypatch.setattr(
        "nwnfile.locations.discover_installs", lambda *a, **k: called.append(1) or []
    )
    assert host_mod.default_game_root() is None
    assert called, "the shared locator is what decides, not a hardcoded list"


def test_a_missing_game_folder_is_explained_rather_than_left_puzzling(
    tmp_path, monkeypatch
):
    """Without it every name comes out as a raw id. Saying so beats a screen of
    "Feat 1337" with no explanation."""
    from PySide6.QtWidgets import QMessageBox

    told = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: told.append(a))
    monkeypatch.setattr(
        "nwnsaveeditor.ui.editor.__main__.collect_saves",
        lambda *a: [__import__("tests.test_save_editor", fromlist=["x"])._make_char_save(tmp_path)],
    )
    monkeypatch.setattr("nwnsaveeditor.ui.editor.host.default_game_root", lambda: None)
    monkeypatch.setattr(
        "nwnsaveeditor.ui.editor.window.SaveEditorWindow.show", lambda self: None
    )
    monkeypatch.setattr("PySide6.QtWidgets.QApplication.exec", lambda self: 0)

    assert main(["--user-dir", str(tmp_path)]) == 0
    assert told, "a missing game folder must be reported"
    assert "raw numbers" in told[0][2]


def test_class_level_editing_is_off_by_default_and_persists(tmp_path):
    assert StandaloneHost(settings_dir=tmp_path)._settings().enable_class_level_editing is False
    StandaloneHost(settings_dir=tmp_path).set_class_level_editing(True)
    assert StandaloneHost(settings_dir=tmp_path)._settings().enable_class_level_editing is True
    StandaloneHost(settings_dir=tmp_path).set_class_level_editing(False)
    assert StandaloneHost(settings_dir=tmp_path)._settings().enable_class_level_editing is False
