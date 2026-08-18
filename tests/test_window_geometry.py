"""Remembering the window's size and position — and refusing to when it would
put the window somewhere nobody can reach."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRect

from nwnsaveeditor.ui.editor import geometry

# A laptop screen, and a second monitor sitting to its right.
LAPTOP = QRect(0, 0, 1366, 768)
SECOND = QRect(1366, 0, 1920, 1080)


# -- storing it -------------------------------------------------------------- #
def test_geometry_round_trips_through_text():
    data = QByteArray(b"\x01\x02\x03 not ascii \xff")
    assert geometry.decode(geometry.encode(data)) == data


def test_unusable_stored_text_reads_as_no_memory():
    """Settings files get hand-edited and copied between machines; junk there
    means 'no remembered geometry', not a crash."""
    assert geometry.decode("") is None
    assert geometry.decode("not base64 at all!") is None
    assert geometry.decode("💥") is None


# -- the on-screen rule ------------------------------------------------------ #
def test_a_window_on_the_laptop_screen_is_accepted():
    assert geometry.is_on_screen(QRect(100, 100, 800, 600), [LAPTOP])


def test_a_window_on_a_monitor_that_is_gone_is_rejected():
    """The bug this guards: geometry saved on the second monitor, restored after
    it was unplugged, would leave the window off every screen."""
    on_second = QRect(1500, 200, 800, 600)
    assert geometry.is_on_screen(on_second, [LAPTOP, SECOND])
    assert not geometry.is_on_screen(on_second, [LAPTOP])


def test_a_sliver_of_window_does_not_count_as_visible():
    """Overlapping by a few pixels is not reachable — there is no title bar to
    grab, so the window may as well be gone."""
    sliver = QRect(1366 - 8, 300, 800, 600)  # 8px poking onto the laptop screen
    assert not geometry.is_on_screen(sliver, [LAPTOP])

    grabbable = QRect(1366 - geometry.MIN_VISIBLE_W, 300, 800, 600)
    assert geometry.is_on_screen(grabbable, [LAPTOP])


def test_a_window_above_the_screen_is_rejected():
    """Dragged mostly off the top, the title bar is unreachable."""
    assert not geometry.is_on_screen(QRect(200, -600, 800, 600), [LAPTOP])


def test_no_screens_at_all_is_not_on_screen():
    assert not geometry.is_on_screen(QRect(0, 0, 800, 600), [])


# -- the fallback size ------------------------------------------------------- #
def test_the_default_size_is_shrunk_to_a_small_screen():
    """1400x900 is taller than a 1366x768 laptop, which is why the window used to
    open with its own chrome off the bottom."""
    assert geometry.fit_to_screen(1400, 900, LAPTOP) == (1366, 768)


def test_the_default_size_is_untouched_on_a_big_screen():
    assert geometry.fit_to_screen(1400, 900, SECOND) == (1400, 900)
