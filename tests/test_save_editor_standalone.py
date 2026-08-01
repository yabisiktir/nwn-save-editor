"""Running the save editor without a Vaultkeeper application.

The editor is a save editor Vaultkeeper launches, not a part of Vaultkeeper. What
holds that true is the small host protocol — so these tests pin the surface, not
the implementation.
"""

from __future__ import annotations

import json
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
    from tests.test_save_editor import _make_char_save

    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

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
    assert not (tmp_path / "save_editor.json").exists()


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
    from tests.test_save_editor import _make_char_save

    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

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
