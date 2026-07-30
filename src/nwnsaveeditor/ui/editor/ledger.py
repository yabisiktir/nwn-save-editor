"""The change ledger — a slide-over listing every staged edit.

One row per staged change (where it is, and ``old → new``), with a per-row
**Discard**. Edits backed out with the toolbar's Undo stay listed, struck through
and excluded from the write count, so the user can see what they reversed.

A note on the model: the toolbar's Undo/Redo is a linear stack, so "undo" is only
defined for the most recent edit. Per-row reversal is therefore **Discard**, which
:meth:`SaveEditor.discard_change` implements by replaying every *other* edit — that
works for any row, in any order, without per-kind inverses.
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

#: The slide-over's width, and how far in from the window's right edge it sits.
LEDGER_W = 420


class ChangeLedger(QFrame):
    """The slide-over panel. Lives as a child of the window and overlays it."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.setFixedWidth(LEDGER_W)
        self.setStyleSheet(
            f"ChangeLedger{{background:{t.SURFACE};"
            f"border-left:1px solid {t.hairline(0.14)};}}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(-8)
        shadow.setYOffset(0)
        shadow.setColor(QColor(0, 0, 0, 128))
        self.setGraphicsEffect(shadow)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        header = QHBoxLayout()
        self._title = w.heading("Changes")
        header.addWidget(self._title)
        header.addStretch(1)
        close = w.small_ghost("Close")
        close.clicked.connect(self.hide)
        header.addWidget(close)
        outer.addLayout(header)

        self._count = w.body("", t.TEXT_2, 12)
        outer.addWidget(self._count)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}" + w.SCROLLBAR_QSS
        )
        outer.addWidget(self._scroll, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._discard_all = w.ghost_button("Discard all")
        self._discard_all.clicked.connect(self._on_discard_all)
        footer.addWidget(self._discard_all)
        footer.addStretch(1)
        self._save = w.gold_button("Save…")
        self._save.setToolTip("Write these changes")
        self._save.clicked.connect(self._on_save)
        footer.addWidget(self._save)
        outer.addLayout(footer)

        self.hide()

    # -- placement --------------------------------------------------------- #
    def reposition(self) -> None:
        """Pin to the window's right edge, below the toolbar."""
        parent = self.parentWidget()
        if parent is None:
            return
        top = t.TOOLBAR_H
        self.setGeometry(parent.width() - LEDGER_W, top, LEDGER_W, parent.height() - top)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.refresh()
            self.reposition()
            self.show()
            self.raise_()

    # -- content ----------------------------------------------------------- #
    def refresh(self) -> None:
        session = self._window._session
        staged = session.pending_changes() if session is not None else []
        undone = session.undone_changes() if session is not None else []

        self._count.setText(
            f"{len(staged)} to write"
            + (f" · {len(undone)} undone (not written)" if undone else "")
        )
        self._discard_all.setEnabled(bool(staged))
        self._save.setEnabled(bool(staged))

        body = QWidget()
        body.setStyleSheet("background:transparent;")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(6)
        if not staged and not undone:
            column.addWidget(w.body("Nothing staged yet.", t.TEXT_3, 12.5))
        for change in staged:
            column.addWidget(self._row(change, undone=False))
        for change in undone:
            column.addWidget(self._row(change, undone=True))
        column.addStretch(1)
        self._scroll.setWidget(body)

    def _row(self, change, *, undone: bool) -> QWidget:
        row = QFrame()
        row.setObjectName("LedgerRow")
        row.setStyleSheet(
            f"#LedgerRow{{background:{t.INSET};border:1px solid {t.hairline(0.06)};"
            f"border-radius:8px;}}"
        )
        column = QVBoxLayout(row)
        column.setContentsMargins(12, 9, 12, 9)
        column.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(8)
        where = w.body(change.where or change.kind, t.TEXT_3 if undone else t.TEXT, 12.5)
        if undone:
            where.setStyleSheet(where.styleSheet() + "text-decoration:line-through;")
        top.addWidget(where, 1)
        section = w.body(_section_label(change.kind), t.TEXT_3, 10.5)
        top.addWidget(section)
        column.addLayout(top)

        detail = QHBoxLayout()
        detail.setSpacing(8)
        summary = w.mono(change.summary, t.TEXT_3 if undone else t.TEXT_2, 11.5)
        if undone:
            summary.setStyleSheet(summary.styleSheet() + "text-decoration:line-through;")
        detail.addWidget(summary, 1)
        if undone:
            detail.addWidget(w.body("undone — not written", t.TEXT_3, 10.5))
        else:
            discard = w.small_ghost("Discard")
            discard.setToolTip("Drop this change, keeping the rest")
            discard.clicked.connect(
                lambda _=False, c=change: self._on_discard(c)
            )
            detail.addWidget(discard)
        column.addLayout(detail)
        return row

    # -- actions ----------------------------------------------------------- #
    def _on_discard(self, change) -> None:
        session = self._window._session
        if session is None:
            return
        session.discard_change((change.kind, change.key))
        self._window.notify_changed()
        self.refresh()

    def _on_discard_all(self) -> None:
        self._window._discard_all()
        self.refresh()

    def _on_save(self) -> None:
        # The design has this jump straight to the save dialog in overwrite mode.
        # That dialog is not built yet, so for now it runs the save-as-new flow,
        # which is the safer of the two.
        self.hide()
        self._window._save_as_new()


def _section_label(kind: str) -> str:
    from vaultkeeper.ui.save_editor.sections import by_key, section_for_kind

    section = by_key(section_for_kind(kind) or "")
    return section.label if section is not None else kind
