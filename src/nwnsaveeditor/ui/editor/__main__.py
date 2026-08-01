"""Run the save editor on its own: ``python -m nwnsaveeditor.ui.editor``.

Vaultkeeper opens the same window from Tools → Save Game Editor. The only
difference is who supplies the host — see
:mod:`nwnsaveeditor.ui.editor.host`, which is the whole of what the editor
asks for. Nothing here is Vaultkeeper-specific, which is the point: the editor
is a save editor that Vaultkeeper happens to launch, not a part of Vaultkeeper.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="nwn-save-editor",
        description="Browse and edit Neverwinter Nights save games.",
    )
    parser.add_argument(
        "saves", nargs="*", type=Path,
        help="save folders to open; defaults to every save in the NWN user directory",
    )
    parser.add_argument(
        "--game-root", type=Path, default=None,
        help="the installed game — needed to name items, spells and properties",
    )
    parser.add_argument(
        "--user-dir", type=Path, default=None,
        help="the NWN user directory, where saves and haks live",
    )
    return parser.parse_args(argv)


def collect_saves(paths: list[Path], user_dir: Path | None) -> list:
    """The saves to offer: the ones named, or everything in the user directory."""
    from nwnsaveeditor.save_game import SaveGame, scan_save_games

    if paths:
        return [SaveGame(folder=path) for path in paths if path.is_dir()]
    return scan_save_games(user_dir / "saves" if user_dir is not None else None)


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from nwnsaveeditor.ui.editor.host import StandaloneHost
    from nwnsaveeditor.ui.editor.window import SaveEditorWindow

    args = parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("NWN Save Editor")

    host = StandaloneHost(game_root=args.game_root, game_user_dir=args.user_dir)
    saves = collect_saves(args.saves, host.ctx.game_user_dir)
    if not saves:
        # Better than an empty window: say where it looked, since a wrong or
        # missing user directory is the one thing that makes this a blank screen.
        QMessageBox.warning(
            None, "No saves found",
            f"No save games found in {host.ctx.game_user_dir or '(no user directory)'}.\n\n"
            "Pass save folders on the command line, or --user-dir to point at "
            "your Neverwinter Nights directory. Whatever you pass is remembered, "
            "so you only need the flag once.",
        )
        return 1

    if host.ctx.game_root is None:
        # The editor still opens and edits — it just cannot name anything, since
        # every name comes from the game's 2DAs and dialog.tlk. Saying so beats
        # a screen full of "Feat 1337" with no explanation.
        QMessageBox.information(
            None, "Game folder not found",
            "The Neverwinter Nights installation could not be found, so items, "
            "feats and spells will show as raw numbers rather than names.\n\n"
            "Pass --game-root to point at it; it is remembered afterwards.",
        )

    window = SaveEditorWindow(saves, host)
    window.resize(1440, 920)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main())
