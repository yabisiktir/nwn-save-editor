"""The application icon: generated, committed, and actually worn by the app."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from nwnsaveeditor.ui.editor.appicon import app_icon, icons_dir

_ROOT = Path(__file__).resolve().parents[1]
_ICONS = _ROOT / "assets" / "icons"


@pytest.mark.parametrize("size", [16, 32, 48, 64, 128, 256, 512, 1024])
def test_every_size_is_committed(size):
    assert (_ICONS / f"icon_{size}.png").is_file()


def test_the_big_ones_exist_because_a_retina_dock_asks_for_them():
    """1024 is what macOS wants; without it the Dock upscales and it looks soft."""
    from PySide6.QtGui import QImage

    assert QImage(str(_ICONS / "icon_1024.png")).width() == 1024


def test_the_windows_icon_carries_every_size_in_one_file():
    data = (_ICONS / "icon.ico").read_bytes()
    _, kind, count = struct.unpack_from("<HHH", data, 0)
    assert kind == 1, "not an icon file"
    sizes = set()
    for i in range(count):
        w, _h, *_ = struct.unpack_from("<BBBBHHII", data, 6 + i * 16)
        sizes.add(w or 256)
    assert {16, 32, 48, 256} <= sizes


def test_a_macos_icns_is_built():
    icns = _ICONS / "icon.icns"
    assert icns.is_file()
    assert icns.read_bytes()[:4] == b"icns"


def test_the_app_icon_offers_several_sizes(qtbot):
    icon = app_icon()
    assert not icon.isNull()
    assert len(icon.availableSizes()) >= 4, "one size would be scaled everywhere"


def test_the_window_wears_it(qtbot, tmp_path):
    from tests.test_save_editor import _make_char_save

    from nwnsaveeditor.ui.editor.host import StandaloneHost
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

    window = SaveEditorWindow(
        [_make_char_save(tmp_path)],
        StandaloneHost(game_root=tmp_path, game_user_dir=tmp_path, settings_dir=tmp_path),
    )
    qtbot.addWidget(window)
    assert not window.windowIcon().isNull()


def test_it_is_found_from_a_frozen_layout(monkeypatch, tmp_path):
    """A build unpacks assets beside the binary, not next to the source."""
    import sys

    frozen = tmp_path / "assets" / "icons"
    frozen.mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert icons_dir() == frozen


def _draw():
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    from make_icons import draw

    return draw


@pytest.mark.parametrize("size", [16, 32, 48, 64, 128, 256, 1024])
def test_every_size_renders_something(size):
    """Not blank, and not a single flat colour."""
    image = _draw()(size)
    step = max(1, size // 32)
    seen = {image.pixel(x, y) for x in range(0, size, step) for y in range(0, size, step)}
    assert len(seen) > 3, f"{size}px is essentially blank"


def test_each_size_is_rendered_from_the_build_authored_for_it():
    """The artwork ships in three builds, not one drawing scaled down.

    That is the whole reason it survives 16px: the designer stripped detail for
    the small sizes rather than letting a downscale mush it. Rendering 16 from
    the full-detail source would throw that away silently.
    """
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    import make_icons

    assert make_icons.build_for(1024).name.endswith("nwn-save-editor.svg")
    assert make_icons.build_for(64).name.endswith("nwn-save-editor.svg")
    assert make_icons.build_for(48).name.endswith("-48.svg")
    assert make_icons.build_for(32).name.endswith("-32.svg")
    assert make_icons.build_for(16).name.endswith("-32.svg")


def test_the_small_build_really_does_carry_less():
    """DESIGN.txt: below 32 the ink lines go, leaving cover, pages and gutter."""
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    import make_icons

    full = (make_icons.SOURCE / "nwn-save-editor.svg").read_text()
    small = (make_icons.SOURCE / "nwn-save-editor-32.svg").read_text()
    assert len(small) < len(full), "the 32px build should be the reduced one"


def test_the_sources_are_vendored_so_a_build_needs_nothing_outside_the_repo():
    for name in ("nwn-save-editor.svg", "nwn-save-editor-48.svg",
                 "nwn-save-editor-32.svg", "DESIGN.txt"):
        assert (_ICONS / "source" / name).is_file(), f"{name} is not vendored"
