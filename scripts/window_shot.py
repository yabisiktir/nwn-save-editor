"""Render the editor's main window to a PNG, without a human at the screen.

    python scripts/window_shot.py --user-dir ~/Documents/"Neverwinter Nights"
    scripts/win_test.sh --shot          # the same thing, inside a Windows bottle

Why
---
A test proves the widgets behave. It does not prove they are *visible*: a label
can be clipped, a panel can come up empty, a theme can render black on black,
and every assertion still passes. Those only show up by looking -- which is why
they survive until somebody runs the app on the platform that has the problem.

This builds the real window against real saves, lets Qt lay it out and paint,
and writes what came out. Run it under Wine (see ``win_test.sh --shot``) and the
PNG shows the *Windows* rendering, so the two can be compared side by side from
one machine. That is how the clipped "Abilities & Combat" tab was found: macOS's
UI font is narrow enough to hide it, Windows' is not.

It grabs from inside Qt rather than shelling out to a screenshot tool. That
captures the window itself rather than whatever is on the desktop, needs no
Screen Recording permission, and works with no display attached at all --
``QT_QPA_PLATFORM=offscreen`` is enough.

Exit status is the number of windows that failed to build, so it is usable as a
smoke check in a pipeline.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

DEFAULT_OUT = REPO / "build" / "screenshots"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="window_shot.py",
        description="Render the save editor's main window to a PNG.",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"directory for the PNGs (default: {DEFAULT_OUT.relative_to(REPO)})",
    )
    parser.add_argument(
        "--user-dir", type=Path, default=None,
        help="the NWN user directory, where saves live; discovered if omitted",
    )
    parser.add_argument(
        "--game-root", type=Path, default=None,
        help="the installed game, so items and feats get names; discovered if omitted",
    )
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=920)
    parser.add_argument(
        "--settle", type=int, default=4000,
        help="milliseconds to let timers and deferred fills finish before grabbing",
    )
    parser.add_argument(
        "--prefix", default="", help="prefix for the output filenames, e.g. 'win-'"
    )
    return parser.parse_args(argv)


def settle(app, ms: int) -> None:
    """Run the event loop for a while.

    Not cosmetic: several panels fill on a QTimer so that opening a big save
    does not block, and grabbing too early photographs a half-built window.
    """
    from PySide6.QtCore import QDeadlineTimer, QEventLoop

    deadline = QDeadlineTimer(ms)
    while not deadline.hasExpired():
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)


def grab(widget, path: Path, app, args) -> None:
    widget.resize(args.width, args.height)
    widget.show()
    settle(app, args.settle)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not widget.grab().save(str(path)):
        raise RuntimeError(f"Qt could not write {path}")
    size = widget.size()
    print(f"  wrote {path}  ({size.width()}x{size.height()})")


def shoot_editor(app, args) -> None:
    from nwnsaveeditor.save_game import scan_save_games
    from nwnsaveeditor.ui.editor.host import StandaloneHost
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

    host = StandaloneHost(game_root=args.game_root, game_user_dir=args.user_dir)
    user_dir = host.ctx.game_user_dir
    saves = scan_save_games(user_dir / "saves" if user_dir else None)
    print(f"  user dir : {user_dir}")
    print(f"  game root: {host.ctx.game_root}")
    print(f"  saves    : {len(saves)}")
    if not saves:
        # A window with nothing open is a photograph of an empty frame, which
        # would pass this check while showing none of what it is meant to check.
        raise RuntimeError(
            "no saves found — pass --user-dir at your Neverwinter Nights folder"
        )

    window = SaveEditorWindow(saves, host)
    grab(window, args.out / f"{args.prefix}save-editor.png", app, args)
    window.close()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    print(f"platform plugin: {app.platformName()}")

    failures = 0
    for label, shoot in (("save editor", shoot_editor),):
        print(f"{label}:")
        try:
            shoot(app, args)
        except Exception:
            failures += 1
            traceback.print_exc()
            print(f"  !! {label} FAILED")
    return failures


if __name__ == "__main__":
    raise SystemExit(main())
