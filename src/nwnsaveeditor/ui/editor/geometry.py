"""Remembering the window's size and position between runs.

Restoring geometry blind is how a window becomes unreachable: a position saved
while a second monitor was attached puts the window nowhere on screen once that
monitor is gone, and a window you cannot see is a window you cannot drag back.
So a restore is *checked* here before it is accepted, and a rejected one falls
back to a size derived from the screen actually present — the same spirit as
:func:`host._saved_dir`, which drops a remembered folder that has gone away
rather than pinning the editor to it.

The stored form is base64 text rather than raw bytes so it can live in the
settings JSON alongside everything else.
"""

from __future__ import annotations

import base64
import binascii

from PySide6.QtCore import QByteArray, QRect
from PySide6.QtGui import QGuiApplication

#: How much of the window has to land on a screen for a restore to be accepted.
#: Sized to be enough title bar to grab with the mouse: a window overlapping a
#: screen by a few pixels is not "visible", it is stuck.
MIN_VISIBLE_W = 120
MIN_VISIBLE_H = 40


def encode(data: QByteArray) -> str:
    """``QMainWindow.saveGeometry()`` bytes as text for the settings file."""
    return base64.b64encode(bytes(data)).decode("ascii")


def decode(text: str) -> QByteArray | None:
    """Turn stored text back into geometry bytes; ``None`` if it is not usable.

    Settings files get hand-edited and copied between machines, so unreadable
    text here means "no remembered geometry", never an error.
    """
    if not text:
        return None
    try:
        return QByteArray(base64.b64decode(text.encode("ascii"), validate=True))
    except (binascii.Error, UnicodeEncodeError, ValueError):
        return None


def available_rects() -> list[QRect]:
    """The usable area of every attached screen (excluding docks and taskbars)."""
    return [screen.availableGeometry() for screen in QGuiApplication.screens()]


def is_on_screen(frame: QRect, rects: list[QRect] | None = None) -> bool:
    """Whether ``frame`` lands on some screen by enough to be usable.

    ``rects`` is injectable so the rule can be exercised against monitor layouts
    that are not the one the test happens to run on.
    """
    for rect in available_rects() if rects is None else rects:
        overlap = rect.intersected(frame)
        if overlap.width() >= MIN_VISIBLE_W and overlap.height() >= MIN_VISIBLE_H:
            return True
    return False


def fit_to_screen(width: int, height: int, rect: QRect | None = None) -> tuple[int, int]:
    """``(width, height)`` shrunk to fit the primary screen's usable area.

    The editor's preferred size is bigger than a small laptop display, and a
    window taller than the screen opens with its own chrome off the bottom.
    """
    if rect is None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return width, height
        rect = screen.availableGeometry()
    return min(width, rect.width()), min(height, rect.height())


def center_on_primary(window) -> None:
    """Put ``window`` in the middle of the primary screen's usable area.

    Clamped to the top-left corner, so a window as large as the screen still
    starts somewhere it can be reached rather than at a negative offset.
    """
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    available = screen.availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(available.center())
    window.move(
        max(available.left(), frame.left()), max(available.top(), frame.top())
    )
