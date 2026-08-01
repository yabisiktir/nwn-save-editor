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


def test_the_pen_is_dropped_at_the_sizes_it_would_only_smear():
    """The first attempt layered scroll, rules and pen in one gold; at 16px they
    merged into a smudge that read as a "7". The pen now appears only from 48 up,
    and the scroll silhouette carries the smaller sizes on its own."""
    draw = _draw()
    from PySide6.QtGui import QColor

    gold = QColor("#deaf56").rgb() & 0xFFFFFF

    def has_bright_gold(size):
        image = draw(size)
        return any(
            abs(((image.pixel(x, y) & 0xFFFFFF) >> 16) - (gold >> 16)) < 12
            and abs(((image.pixel(x, y) >> 8) & 0xFF) - ((gold >> 8) & 0xFF)) < 12
            for x in range(size) for y in range(size)
        )

    assert has_bright_gold(64), "the pen should be drawn at 64"
    assert not has_bright_gold(32), "and dropped at 32, where it would only smear"
