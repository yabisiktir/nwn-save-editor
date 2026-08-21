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

from PySide6.QtCore import Qt, QTimer
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

#: How many saves the Open dialog decodes before painting — about a screenful, so
#: what the user first sees is correct at once while the rest streams in behind it.
_EAGER_ROWS = 12
#: How many pending saves the background pump resolves per idle tick.
_RESOLVE_BATCH = 4


def _input_qss(family: str | None = None) -> str:
    """A line edit in the editor's chrome; ``family`` defaults to the mono face."""
    return (
        f"QLineEdit{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{family or t.MONO_FAMILY};"
        f"font-size:12px;padding:7px 9px;selection-background-color:{t.gold_tint(0.5)};"
        f"selection-color:{t.GOLD};}}"
        f"QLineEdit:focus{{border-color:{t.gold_border(0.5)};}}"
    )


@dataclass
class SaveState:
    """What the Open dialog knows about one save."""

    save: SaveGame
    module: str
    saved: datetime | None
    size: int
    state: str  #: "pending" | "normal" | "readonly" | "corrupt"

    @property
    def openable(self) -> bool:
        # "pending" is not yet decoded, so we cannot promise it opens — it becomes
        # choosable the moment it resolves. "corrupt" never opens.
        return self.state in ("normal", "readonly")

    @property
    def resolved(self) -> bool:
        return self.state != "pending"

    @property
    def action_label(self) -> str:
        """The design has the primary button's wording follow the state."""
        return "Open read-only" if self.state == "readonly" else "Open"


def inspect_save(save: SaveGame, *, resolve: bool = True) -> SaveState:
    """Measure a save's module, timestamp, size and state.

    Only the module's *name* is shown here, so the area names are not read: each
    one is a separate lookup inside the ``.sav``, which made opening this dialog
    cost (areas x saves) archive reads before it could paint.

    Decoding ``module.ifo`` (to name the module and tell a corrupt save from a
    good one) is the costly part — a few ms of archive read *per save*, which is
    what made opening a folder of hundreds of saves hang. Pass ``resolve=False``
    for a **pending** state that skips it (name and size only); the dialog then
    fills the rest in the background via :func:`resolve_state`.
    """
    try:
        size = sum(f.stat().st_size for f in save.folder.rglob("*") if f.is_file())
    except OSError:
        size = 0
    state = SaveState(
        save=save, module="", saved=save.saved, size=size, state="pending"
    )
    if resolve:
        resolve_state(state)
    return state


def resolve_state(state: SaveState) -> SaveState:
    """Decode ``module.ifo`` for a pending state, settling its module name and
    whether it is corrupt / read-only / normal. A no-op once resolved."""
    if state.resolved:
        return state
    save = state.save
    try:
        info = save.module_info(read_area_names=False)
    except Exception:
        info = None
    if info is None:
        state.state = "corrupt"  # the .sav's module.ifo would not decode
    elif not os.access(save.folder, os.W_OK):
        state.state = "readonly"
    else:
        state.state = "normal"
    state.module = (info.name if info is not None else "") or "—"
    return state


def _meta_text(state: SaveState) -> str:
    """The row's second line: ``module · when · size``. A not-yet-decoded save
    reads ``Reading…`` in the module slot, so a pending row looks like it is
    loading rather than empty or broken."""
    module = "Reading…" if not state.resolved else state.module
    stamp = state.saved.strftime("%Y-%m-%d %H:%M") if state.saved else "—"
    return f"{module}  ·  {stamp}  ·  {_human_size(state.size)}"


def _haystack_for(state: SaveState) -> str:
    """The lower-cased text the search box matches a row against."""
    return f"{state.save.name} {state.module} {state.save.location}".lower()


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
        # Resolve only the first screenful up front so the dialog paints at once
        # even on a folder of hundreds of saves; the rest is decoded in the
        # background by _resolve_pump (see resolve_state). A small folder resolves
        # entirely here, so it is correct and flicker-free on the very first frame.
        self._states = [
            inspect_save(save, resolve=(i < _EAGER_ROWS))
            for i, save in enumerate(saves)
        ]
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
        self._start_resolve_pump()

    def _start_resolve_pump(self) -> None:
        """Decode the still-pending saves in the background, a few per idle tick,
        so a big folder's dialog is usable before every module is read. The first
        tick is deferred too, so construction returns with the dialog painted and
        the pending rows still showing their loading cue."""
        if any(not s.resolved for s in self._states):
            QTimer.singleShot(0, self._resolve_pump)

    def _resolve_pump(self) -> None:
        from shiboken6 import isValid

        if not isValid(self):  # dialog closed while a tick was still queued
            return
        # Always drain the front of the still-pending set: resolving a row drops it
        # out, so an incrementing index would skip saves.
        pending = [
            (row, state) for _h, row, state in self._rows if not state.resolved
        ]
        for row, state in pending[:_RESOLVE_BATCH]:
            resolve_state(state)
            self._refresh_row(row, state)
        # A resolved save may be the first openable one — adopt it if nothing is
        # chosen yet, so the Open button lights as soon as something can be opened.
        if self._chosen is None:
            self._chosen = next((s for s in self._states if s.openable), None)
            if self._chosen is not None:
                for _h, r, rs in self._rows:
                    self._style_row(r, rs)
                self._sync_button()
        if len(pending) > _RESOLVE_BATCH:
            QTimer.singleShot(0, self._resolve_pump)

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
            self._rows.append((_haystack_for(state), row, state))
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
        row._meta = w.body(_meta_text(state), t.TEXT_3, 11.5)
        text.addWidget(row._meta)
        layout.addLayout(text, 1)
        # A badge holder that stays in the layout so a pending row can grow a
        # corrupt/read-only badge once it resolves, without a full rebuild.
        row._badge_box = QWidget()
        row._badge_box.setStyleSheet("background:transparent;")
        badge_layout = QHBoxLayout(row._badge_box)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(row._badge_box)
        self._fill_badge(row, state)
        row.mousePressEvent = lambda _e, s=state: self._choose(s)
        return row

    def _fill_badge(self, row: QWidget, state: SaveState) -> None:
        layout = row._badge_box.layout()
        while layout.count():
            old = layout.takeAt(0).widget()
            if old is not None:
                old.setParent(None)
        # "pending" and "normal" carry no badge — an unresolved row must not flash
        # a scary state, and a normal one needs none.
        if state.state in ("readonly", "corrupt"):
            layout.addWidget(_state_badge(state.state))

    def _refresh_row(self, row: QWidget, state: SaveState) -> None:
        """Update a row in place after its save resolved (module name, state)."""
        row._meta.setText(_meta_text(state))
        self._fill_badge(row, state)
        self._style_row(row, state)
        # Rebuild this row's search key so a now-named module becomes searchable.
        self._rows = [
            (_haystack_for(rs) if r is row else h, r, rs)
            for h, r, rs in self._rows
        ]

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
            return  # a corrupt (or not-yet-resolved) save cannot be chosen
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
