"""The first thing a standalone run shows when it has nothing to open.

Detection finds the game on a normal install, and after that the folders are
remembered — so this dialog is for the run where detection came up empty: a game
in an unusual place, saves on a second drive, a fresh machine. Rather than the
old dead-end (a message box, then exit to the command line to pass ``--user-dir``),
it lets the folders be pointed at here, in the GUI, and re-scans as they change so
the person can see the save count climb off zero before opening the editor.

It talks to the host through the same surface the settings screen uses
(``set_game_paths`` / ``set_extra_save_dirs``), so whatever is chosen is persisted
the ordinary way and the next launch starts pointed at it. The scan itself is
:func:`nwnsaveeditor.save_game.scan_all_saves`, the one the rest of the app uses,
so "found here" means the same thing it will mean once the editor is open.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.save_game import scan_all_saves
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w


class FirstRunDialog(QDialog):
    """Point a standalone run at its folders when nothing was found to open."""

    def __init__(self, host, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._host = host
        self.setWindowTitle("Set up the Save Editor")
        self.setMinimumWidth(560)
        self.resize(600, 560)
        self.setStyleSheet(w.dialog_qss())

        column = QVBoxLayout(self)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(14)
        column.addWidget(w.heading("Set up the Save Editor", 20))
        column.addWidget(w.body(
            "No save games were found automatically. Point the editor at your "
            "Neverwinter Nights folders and it will remember them — you only do "
            "this once.",
            t.TEXT_2, 12.5,
        ))

        column.addWidget(w.cap_label("Folders"))
        column.addWidget(self._folder_row(
            "game_user_dir", "User files folder",
            "The Neverwinter Nights folder NWN writes to — its saves, haks and "
            "portraits live under it. Saves are read from its nwn.ini SAVES "
            "location (plus any Additional save folders below).",
        ))
        column.addWidget(self._folder_row(
            "game_root", "Game installation",
            "Only needed to show names: items, feats and spells are stored as "
            "numbers, and the names come from the game's files.",
        ))

        column.addWidget(w.hline())
        column.addWidget(w.cap_label("Additional save folders"))
        column.addWidget(self._extra_saves_block())

        column.addStretch(1)

        # A live count so the person sees the saves appear before opening — the
        # whole point of scanning here rather than after the window is up.
        self._status = w.body("", t.TEXT_2, 12.5)
        column.addWidget(self._status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        quit_button = w.ghost_button("Quit")
        quit_button.clicked.connect(self.reject)
        buttons.addWidget(quit_button)
        self._open_button = w.gold_button("Open editor")
        self._open_button.clicked.connect(self.accept)
        buttons.addWidget(self._open_button)
        column.addLayout(buttons)

        self._refresh_status()

    # -- the saves this dialog resolves ------------------------------------- #
    def found_saves(self) -> list:
        """Every save under the (possibly just-chosen) folders, newest first."""
        user = getattr(getattr(self._host, "ctx", None), "game_user_dir", None)
        extra = self._host.extra_save_dirs() if hasattr(self._host, "extra_save_dirs") else ()
        return scan_all_saves(user, extra)

    def _refresh_status(self) -> None:
        count = len(self.found_saves())
        if count:
            noun = "save game" if count == 1 else "save games"
            self._status.setText(f"✓  {count} {noun} found.")
            self._status.setStyleSheet(f"color:{t.GREEN};")
        else:
            self._status.setText("No save games found yet — choose a folder above.")
            self._status.setStyleSheet(f"color:{t.PRC_AMBER};")
        self._open_button.setEnabled(count > 0)

    # -- folder rows -------------------------------------------------------- #
    def _folder_row(self, key: str, label: str, blurb: str) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(w.body(label, t.TEXT, 13))
        column.addWidget(w.body(blurb, t.TEXT_3, 11.5))

        line = QHBoxLayout()
        line.setSpacing(8)
        current = getattr(getattr(self._host, "ctx", None), key, None)
        value = w.mono(str(current) if current else "not set", t.TEXT_2, 11.5)
        value.setWordWrap(True)
        setattr(self, f"_{key}_label", value)
        line.addWidget(value, 1)
        browse = w.small_ghost("Choose…")
        browse.clicked.connect(lambda _=False, k=key, lbl=label: self._browse(k, lbl))
        line.addWidget(browse)
        column.addLayout(line)
        return holder

    def _browse(self, key: str, label: str) -> None:
        start = getattr(getattr(self._host, "ctx", None), key, None)
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose your {label}", str(start or Path.home())
        )
        if not chosen:
            return
        # Qt hands back a forward-slash path even on Windows; store and show it
        # with the OS's own separators (C:\… not C:/…).
        chosen_path = Path(chosen)
        self._host.set_game_paths(**{key: chosen_path})
        getattr(self, f"_{key}_label").setText(str(chosen_path))
        self._refresh_status()

    # -- extra saves folders ------------------------------------------------ #
    def _extra_saves_block(self) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(w.body(
            "Any other folder that holds save sub-folders — a second saves "
            "directory, a backup drive.",
            t.TEXT_3, 11.5,
        ))
        self._extra_saves_list = QVBoxLayout()
        self._extra_saves_list.setSpacing(3)
        column.addLayout(self._extra_saves_list)
        add = w.small_ghost("Add folder…")
        add.clicked.connect(self._add_extra_save_dir)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addStretch(1)
        column.addLayout(row)
        self._rebuild_extra_saves()
        return holder

    def _rebuild_extra_saves(self) -> None:
        while self._extra_saves_list.count():
            item = self._extra_saves_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                w.retire(widget)
        dirs = self._host.extra_save_dirs() if hasattr(self._host, "extra_save_dirs") else []
        if not dirs:
            self._extra_saves_list.addWidget(w.body("None added.", t.TEXT_3, 12))
            return
        for folder in dirs:
            line = QWidget()
            line.setStyleSheet("background:transparent;")
            row = QHBoxLayout(line)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(w.mono(str(folder), t.TEXT_2, 11.5), 1)
            remove = w.small_ghost("Remove")
            remove.clicked.connect(lambda _=False, f=folder: self._remove_extra_save_dir(f))
            row.addWidget(remove)
            self._extra_saves_list.addWidget(line)

    def _add_extra_save_dir(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose a folder that holds NWN save sub-folders", str(Path.home())
        )
        if not chosen:
            return
        current = [str(d) for d in self._host.extra_save_dirs()]
        if chosen not in current:
            self._host.set_extra_save_dirs([*current, chosen])
            self._rebuild_extra_saves()
            self._refresh_status()

    def _remove_extra_save_dir(self, folder) -> None:
        kept = [d for d in self._host.extra_save_dirs() if str(d) != str(folder)]
        self._host.set_extra_save_dirs(kept)
        self._rebuild_extra_saves()
        self._refresh_status()
