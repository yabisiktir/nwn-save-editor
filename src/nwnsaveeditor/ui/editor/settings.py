"""Where the editor is pointed, and whether it is the editor's to point.

Two folders decide what the editor can do: the *user directory* holds your saves,
and the *game root* holds the tables every name is read from. This shows both, and
where each came from.

It only lets you change them when the editor owns them. Embedded in an application
that has its own game-folder setting, they are that application's to change —
writing them here would either be ignored or would quietly disagree with what the
editor is actually reading. So the host declares the capability by offering
``set_game_paths``, exactly as it declares ``portrait_path``; without it, this is a
read-only report that names who is in charge.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w


def _wrap_grows(holder: QWidget) -> QWidget:
    """Let a group with a wrapping label take its full height in a parent layout.

    A ``QWidget`` holding a heightForWidth label does not, by default, tell its
    parent it has one — so the parent uses the one-line sizeHint and the label
    paints over the next row. Opting the holder's size policy in fixes that
    (offscreen tolerates it; the native macOS style does not)."""
    policy = holder.sizePolicy()
    policy.setHeightForWidth(True)
    holder.setSizePolicy(policy)
    return holder


class SettingsDialog(QDialog):
    """The editor's folders and theme."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent or window)
        self._window = window
        self._host = window._controller
        self._chosen: dict[str, Path] = {}
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self.resize(600, 640)
        self.setStyleSheet(w.dialog_qss() + w.scrollbar_qss())

        # A scroll area keeps a growing settings list usable on a small screen, and
        # keeps the Close/Apply buttons pinned below it rather than scrolling away.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # The viewport must be transparent AND the content must paint the theme
        # background itself: a bare QScrollArea viewport falls back to the system
        # palette, so on a dark-mode Mac the light theme rendered dark-on-dark
        # (the dialog's own QDialog background sits behind the viewport, unseen).
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        scroll.viewport().setStyleSheet("background:transparent;")
        content = QWidget()
        content.setStyleSheet(f"background:{t.APP_BG};")
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        column = QVBoxLayout(content)
        column.setContentsMargins(22, 20, 22, 18)
        column.setSpacing(14)
        column.addWidget(w.heading("Settings", 20))

        if not self.editable():
            column.addWidget(w.warning_panel(
                f"These folders are managed by {self._host_name()}, which opened this "
                f"editor. Change them there — editing them here would have no effect "
                f"on what the editor actually reads."
            ))

        column.addWidget(w.cap_label("Folders"))
        column.addWidget(_wrap_grows(self._folder_row(
            "game_user_dir", "Save games",
            "Your saves, haks, portraits and override — the folder NWN writes to.",
        )))
        column.addWidget(_wrap_grows(self._folder_row(
            "game_root", "Game installation",
            "Only needed for names: items, feats and spells are stored as numbers, "
            "and the names come from the game's 2DAs and dialog.tlk.",
        )))

        if self.extra_saves_editable():
            column.addWidget(w.hline())
            column.addWidget(w.cap_label("Additional save folders"))
            column.addWidget(_wrap_grows(self._extra_saves_block()))

        if self.icons_editable():
            column.addWidget(w.hline())
            column.addWidget(w.cap_label("Item icons"))
            column.addWidget(_wrap_grows(self._icon_toggle(
                "exact_item_icons", "Show each item's own icon",
                "Off, every item of a type shows that type's one picture.",
            )))
            column.addWidget(_wrap_grows(self._icon_toggle(
                "hak_item_icons", "Look in your haks too",
                "Custom content keeps its icons in haks — without this a CEP or PRC "
                "item falls back to a generic picture. Costs about a second, once.",
            )))

        column.addWidget(w.hline())
        column.addWidget(w.cap_label("Appearance"))
        theme = w.SegmentedControl((("dark", "Dark"), ("light", "Light")))
        theme.set_value(t.active_theme())
        theme.changed.connect(lambda _: window._set_theme(theme.value()))
        row = QHBoxLayout()
        row.addWidget(w.body("Colour theme", t.TEXT_2, 13), 1)
        row.addWidget(theme)
        column.addLayout(row)

        if self.class_editing_available():
            column.addWidget(w.hline())
            column.addWidget(w.cap_label("Advanced"))
            column.addWidget(_wrap_grows(self._class_editing_toggle()))

        column.addStretch(1)

        # A pinned footer: the buttons stay put while the settings above scroll.
        footer = QWidget()
        footer.setStyleSheet(f"background:{t.SURFACE};border-top:1px solid {t.hairline(0.1)};")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(22, 12, 22, 12)
        buttons.addStretch(1)
        close = w.ghost_button("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        if self.editable():
            apply = w.gold_button("Apply")
            apply.clicked.connect(self._apply)
            buttons.addWidget(apply)
        outer.addWidget(footer)

    # -- what the host allows ----------------------------------------------- #
    def editable(self) -> bool:
        """Whether the paths are the editor's to change."""
        return hasattr(self._host, "set_game_paths")

    def icons_editable(self) -> bool:
        """Whether the icon options are the editor's to change.

        Same rule as the folders: a host offering its own icon settings owns
        them, and a toggle here would write somewhere the editor never reads.
        """
        return hasattr(self._host, "set_item_icon_options")

    def class_editing_available(self) -> bool:
        """Whether this host offers the (opt-in) class-level editing toggle."""
        return hasattr(self._host, "set_class_level_editing")

    def extra_saves_editable(self) -> bool:
        """Whether extra saves folders are this host's to manage."""
        return hasattr(self._host, "set_extra_save_dirs")

    # -- extra saves folders ------------------------------------------------- #
    def _extra_saves_block(self) -> QWidget:
        self._extra_saves_holder = QWidget()
        self._extra_saves_holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(self._extra_saves_holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(w.body(
            "Scanned alongside the install's own saves. Each is a folder that "
            "contains save sub-folders — a second saves directory, a backup drive.",
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
        return self._extra_saves_holder

    def _rebuild_extra_saves(self) -> None:
        while self._extra_saves_list.count():
            item = self._extra_saves_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                w.retire(widget)
        dirs = self._host.extra_save_dirs()
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
            self._window.reload_saves()

    def _remove_extra_save_dir(self, folder) -> None:
        kept = [d for d in self._host.extra_save_dirs() if str(d) != str(folder)]
        self._host.set_extra_save_dirs(kept)
        self._rebuild_extra_saves()
        self._window.reload_saves()

    def _class_editing_toggle(self) -> QWidget:
        from PySide6.QtWidgets import QCheckBox

        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        row = QVBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        settings = self._host._settings() if hasattr(self._host, "_settings") else None
        box = QCheckBox("Enable class level editing")
        box.setChecked(bool(getattr(settings, "enable_class_level_editing", False)))
        box.setStyleSheet(f"color:{t.TEXT};font-family:{t.UI_FAMILY};font-size:13px;")
        box.toggled.connect(self._host.set_class_level_editing)
        row.addWidget(box)
        note = w.body(
            "Add class levels, applying the hit points, attack, saves and XP a level "
            "brings. Off by default: a level-up writes several fields, and a PRC "
            "class level still needs an in-game re-level to set up its features.",
            t.TEXT_3, 11.5,
        )
        note.setWordWrap(True)
        row.addWidget(note)
        return holder

    def _icon_toggle(self, key: str, label: str, blurb: str) -> QWidget:
        from PySide6.QtWidgets import QCheckBox

        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        row = QVBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        settings = self._host._settings() if hasattr(self._host, "_settings") else None
        box = QCheckBox(label)
        box.setChecked(bool(getattr(settings, key, True)))
        box.setStyleSheet(
            f"color:{t.TEXT};font-family:{t.UI_FAMILY};font-size:13px;"
        )
        box.toggled.connect(lambda on, k=key: self._set_icon_option(k, on))
        row.addWidget(box)
        note = w.body(blurb, t.TEXT_3, 11.5)
        note.setWordWrap(True)
        row.addWidget(note)
        return holder

    def _set_icon_option(self, key: str, value: bool) -> None:
        """Apply at once — an icon toggle has nothing to validate or cancel."""
        self._host.set_item_icon_options(**{key: value})
        self._window.reload_icons()

    def _host_name(self) -> str:
        """Whatever opened the editor, named as well as it can be."""
        name = type(self._host).__name__
        return "the application" if name.startswith("_") else name

    # -- rows ---------------------------------------------------------------- #
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
        if self.editable():
            browse = w.small_ghost("Choose…")
            browse.clicked.connect(lambda _=False, k=key, lbl=label: self._browse(k, lbl))
            line.addWidget(browse)
        column.addLayout(line)
        if current is None:
            column.addWidget(w.body(
                "Not found. Names will show as raw ids until this is set."
                if key == "game_root" else "Not found — no saves can be listed.",
                t.PRC_AMBER, 11.5,
            ))
        return holder

    def _browse(self, key: str, label: str) -> None:
        start = getattr(getattr(self._host, "ctx", None), key, None)
        chosen = QFileDialog.getExistingDirectory(
            self, f"Choose the {label.lower()} folder", str(start or Path.home())
        )
        if not chosen:
            return
        self._chosen[key] = Path(chosen)
        getattr(self, f"_{key}_label").setText(chosen)

    def _apply(self) -> None:
        """Hand the chosen folders to the host, then rebuild what depends on them."""
        if not self._chosen:
            self.accept()
            return
        self._host.set_game_paths(**{k: v for k, v in self._chosen.items()})
        self._window.forget_game_tables()
        self.accept()
