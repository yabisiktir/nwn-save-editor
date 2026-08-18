"""The Save Game Editor's two dialogs: Open Save, and Save.

The save states the Open dialog
shows are measured, not decorative: *read-only* means the folder really cannot be
written, and *corrupt* means the ``.sav``'s ``module.ifo`` would not decode — so
the disabled Open button reflects a save that genuinely cannot be opened.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nwnsaveeditor.save_game import SaveGame
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w

OPEN_DIALOG_W = 680
SAVE_DIALOG_W = 560


def _input_qss(family: str | None = None) -> str:
    """A line edit in the editor's chrome; ``family`` defaults to the mono face."""
    return (
        f"QLineEdit{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{family or t.MONO_FAMILY};"
        f"font-size:12px;padding:7px 9px;}}"
        f"QLineEdit:focus{{border-color:{t.gold_border(0.5)};}}"
    )


@dataclass
class SaveState:
    """What the Open dialog knows about one save."""

    save: SaveGame
    module: str
    saved: datetime | None
    size: int
    state: str  #: "normal" | "readonly" | "corrupt"

    @property
    def openable(self) -> bool:
        return self.state != "corrupt"

    @property
    def action_label(self) -> str:
        """The design has the primary button's wording follow the state."""
        return "Open read-only" if self.state == "readonly" else "Open"


def inspect_save(save: SaveGame) -> SaveState:
    """Measure a save's module, timestamp, size and state.

    Only the module's *name* is shown here, so the area names are not read: each
    one is a separate lookup inside the ``.sav``, which made opening this dialog
    cost (areas x saves) archive reads before it could paint.
    """
    try:
        info = save.module_info(read_area_names=False)
    except Exception:
        info = None
    try:
        size = sum(f.stat().st_size for f in save.folder.rglob("*") if f.is_file())
    except OSError:
        size = 0

    if info is None:
        state = "corrupt"  # the .sav's module.ifo would not decode
    elif not os.access(save.folder, os.W_OK):
        state = "readonly"
    else:
        state = "normal"
    return SaveState(
        save=save,
        module=(info.name if info is not None else "") or "—",
        saved=save.saved,
        size=size,
        state=state,
    )


def _human_size(size: int) -> str:
    if size >= 1 << 30:
        return f"{size / (1 << 30):.1f} GB"
    if size >= 1 << 20:
        return f"{size / (1 << 20):.0f} MB"
    return f"{size / 1024:.0f} KB"


class OpenSaveDialog(QDialog):
    """Pick a save to open. Corrupt saves are listed but cannot be opened."""

    def __init__(self, saves: list[SaveGame], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Save")
        self.setFixedWidth(OPEN_DIALOG_W)
        self.setMinimumHeight(460)
        self.setStyleSheet(f"OpenSaveDialog{{background:{t.APP_BG};}}")
        self._states = [inspect_save(save) for save in saves]
        self._chosen: SaveState | None = next(
            (s for s in self._states if s.openable), None
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)
        outer.addWidget(w.heading("Open a save"))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search by name or module…")
        self._search.setStyleSheet(_input_qss(t.UI_FAMILY))
        self._search.textChanged.connect(self._apply_filter)
        outer.addWidget(self._search)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(w.scroll_area_qss())
        outer.addWidget(self._scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        cancel = w.ghost_button("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self._open = w.gold_button("Open")
        self._open.clicked.connect(self.accept)
        footer.addWidget(self._open)
        outer.addLayout(footer)

        self._rows: list[tuple[str, QWidget, SaveState]] = []
        self._build_rows()
        self._sync_button()

    def _build_rows(self) -> None:
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(6)
        self._rows.clear()
        if not self._states:
            column.addWidget(w.body("No save games were found.", t.TEXT_2, 13))
        for state in self._states:
            row = self._row(state)
            self._rows.append((
                f"{state.save.name} {state.module} {state.save.location}".lower(),
                row, state,
            ))
            column.addWidget(row)
        column.addStretch(1)
        w.set_scroll_widget(self._scroll, body)

    def _row(self, state: SaveState) -> QWidget:
        row = _SaveCard()
        # A Qt stylesheet type selector will not match a class whose name starts
        # with an underscore, so the rows are styled by objectName.
        row.setObjectName("SaveCard")
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.state = state
        self._style_row(row, state)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        text = QVBoxLayout()
        text.setSpacing(2)
        name = w.body(state.save.name, t.TEXT, 13)
        name.setStyleSheet(name.styleSheet() + "font-weight:600;")
        text.addWidget(name)
        stamp = state.saved.strftime("%Y-%m-%d %H:%M") if state.saved else "—"
        text.addWidget(w.body(
            f"{state.module}  ·  {stamp}  ·  {_human_size(state.size)}", t.TEXT_3, 11.5
        ))
        layout.addLayout(text, 1)
        if state.state != "normal":
            layout.addWidget(_state_badge(state.state))
        row.mousePressEvent = lambda _e, s=state: self._choose(s)
        return row

    def _style_row(self, row: QWidget, state: SaveState) -> None:
        selected = state is self._chosen
        border = t.gold_border(0.5) if selected else t.hairline(0.06)
        background = t.gold_tint(0.15) if selected else t.INSET
        row.setStyleSheet(
            f"#SaveCard{{background:{background};border:1px solid {border};"
            f"border-radius:8px;}}"
        )

    def _choose(self, state: SaveState) -> None:
        if not state.openable:
            return  # a corrupt save cannot be opened, so it cannot be chosen
        self._chosen = state
        for _haystack, row, row_state in self._rows:
            self._style_row(row, row_state)
        self._sync_button()

    def _sync_button(self) -> None:
        chosen = self._chosen
        self._open.setEnabled(chosen is not None and chosen.openable)
        self._open.setText(chosen.action_label if chosen is not None else "Open")

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for haystack, row, _state in self._rows:
            row.setVisible(needle in haystack)

    def selected_save(self) -> SaveGame | None:
        return self._chosen.save if self._chosen is not None else None


class _SaveCard(QFrame):
    """A row in the Open dialog.

    A QFrame, not a plain QWidget: QWidget does not paint a stylesheet background
    or border at all unless WA_StyledBackground is set, so the rows drew as bare
    text.
    """


def _state_badge(state: str):
    from PySide6.QtWidgets import QLabel

    colour = t.DANGER if state == "corrupt" else t.TEXT_2
    badge = QLabel(state)
    badge.setStyleSheet(
        f"color:{colour};border:1px solid {colour};border-radius:{t.RADIUS_BADGE}px;"
        f"padding:1px 6px;font-family:{t.UI_FAMILY};font-size:9px;font-weight:700;"
    )
    badge.setToolTip(
        "This save's module.ifo could not be decoded, so it cannot be opened."
        if state == "corrupt"
        else "This save's folder is not writable — it can be opened, but not overwritten."
    )
    return badge


class SaveDialog(QDialog):
    """Commit staged changes, as a new save or over the existing one.

    One dialog with two modes, as the design specifies — the wording, the target
    and the backup affordance all follow ``mode``.
    """

    def __init__(
        self,
        *,
        mode: str,
        save_name: str,
        default_name: str,
        change_count: int,
        undone_count: int,
        rule_mode: str,
        backup_dir: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._mode = mode
        self._backup_dir = backup_dir
        self.setWindowTitle("Save" if mode == "new" else "Overwrite save")
        self.setFixedWidth(SAVE_DIALOG_W)
        self.setStyleSheet(f"SaveDialog{{background:{t.APP_BG};}}")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(14)

        if mode == "new":
            title, subtitle = (
                "Save as a new file",
                "The original file is left untouched.",
            )
        else:
            title, subtitle = (
                "Overwrite this save",
                f"{save_name} will be rewritten in place.",
            )
        outer.addWidget(w.heading(title))
        outer.addWidget(w.body(subtitle, t.TEXT_2, 12.5))

        outer.addWidget(w.cap_label("Writing"))
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        panel.body_layout().addWidget(_kv("Changes to write", str(change_count)))
        panel.body_layout().addWidget(
            _kv("Undone (not written)", str(undone_count), dim=undone_count == 0)
        )
        panel.body_layout().addWidget(_kv(
            "Rule mode",
            "Strict — derived values recomputed" if rule_mode == "strict"
            else "Free — raw values written as entered",
        ))
        self._name_edit: QLineEdit | None = None
        if mode == "new":
            panel.body_layout().addWidget(_kv("Target", "a new save folder", mono=True))
        else:
            panel.body_layout().addWidget(_kv("Target", save_name, mono=True))
        outer.addWidget(panel)

        if mode == "new":
            outer.addWidget(w.cap_label("New file name"))
            self._name_edit = QLineEdit(default_name)
            self._name_edit.setStyleSheet(_input_qss())
            self._name_edit.textChanged.connect(self._sync)
            outer.addWidget(self._name_edit)

        self._backup = QCheckBox("Back up the current file first (recommended)")
        self._backup.setChecked(True)
        self._backup.setStyleSheet(
            f"QCheckBox{{color:{t.TEXT};font-family:{t.UI_FAMILY};font-size:12.5px;}}"
        )
        self._backup.toggled.connect(self._sync)
        if mode == "overwrite":
            outer.addWidget(self._backup)
            self._backup_note = w.body("", t.TEXT_3, 11.5)
            outer.addWidget(self._backup_note)
            self._no_backup_warning = w.warning_panel(
                "Without a backup this overwrite cannot be undone from inside "
                "Vaultkeeper."
            )
            outer.addWidget(self._no_backup_warning)
        else:
            self._backup_note = None
            self._no_backup_warning = None

        self._free_warning = w.warning_panel(
            "Free mode: values that break the game's rules are written exactly as "
            "entered, and the game may clamp or reject them on load."
        )
        self._free_warning.setVisible(rule_mode == "free")
        outer.addWidget(self._free_warning)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._review = w.ghost_button("Review changes")
        self._review.clicked.connect(self._on_review)
        footer.addWidget(self._review)
        footer.addStretch(1)
        cancel = w.ghost_button("Cancel")
        cancel.clicked.connect(self.reject)
        footer.addWidget(cancel)
        self._commit = w.gold_button(
            "Write new file" if mode == "new" else "Overwrite save"
        )
        self._commit.setEnabled(change_count > 0)
        self._commit.clicked.connect(self.accept)
        footer.addWidget(self._commit)
        outer.addLayout(footer)

        self._change_count = change_count
        self._review_requested = False
        self._sync()

    def _sync(self) -> None:
        if self._mode == "overwrite" and self._backup_note is not None:
            backing_up = self._backup.isChecked()
            self._backup_note.setVisible(backing_up)
            self._no_backup_warning.setVisible(not backing_up)
            if backing_up:
                self._backup_note.setText(
                    f"The current save is moved to {self._backup_dir} first. The "
                    "edited save is written and verified in a staging folder "
                    "before the old one is touched, so a failed write never "
                    "damages the original."
                )
        enabled = self._change_count > 0
        if self._name_edit is not None:
            enabled = enabled and bool(self._name_edit.text().strip())
        self._commit.setEnabled(enabled)

    def _on_review(self) -> None:
        self._review_requested = True
        self.reject()

    # -- results ----------------------------------------------------------- #
    @property
    def review_requested(self) -> bool:
        """The user asked to go back to the ledger rather than write."""
        return self._review_requested

    def new_name(self) -> str:
        return self._name_edit.text().strip() if self._name_edit is not None else ""

    def backup_wanted(self) -> bool:
        return self._backup.isChecked()


def _kv(label: str, value: str, *, dim: bool = False, mono: bool = False) -> QWidget:
    row = QWidget()
    row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(12)
    layout.addWidget(w.body(label, t.TEXT_2, 12.5), 1)
    colour = t.TEXT_3 if dim else t.TEXT
    value_label = w.mono(value, colour, 12) if mono else w.body(value, colour, 12.5)
    if not mono:
        value_label.setStyleSheet(value_label.styleSheet() + "font-weight:700;")
    layout.addWidget(value_label)
    return row
