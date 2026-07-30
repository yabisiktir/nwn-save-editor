"""The Companions screen.

Lists the henchmen found across the save's areas, with the state each carries.
Read-only, and deliberately so: companions live in area ``.git`` resources, which
this editor treats as read-only everywhere else too (it is why an item found in
the world can only be *copied*, never edited). Making them editable means a write
path into area creatures, which is its own piece of work.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.companions import find_companions
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w


class CompanionsScreen(QWidget):
    """The Companions section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._selected: int | None = None
        self._companions: list = []
        self._cache: list = []
        self._scanned_for = None  # the sav_path the cache was built from
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(14)
        outer.addWidget(w.heading("Companions"))
        self._note = w.body("", t.TEXT_3, 11.5)
        outer.addWidget(self._note)

        split = QHBoxLayout()
        split.setSpacing(16)
        self._list_slot = QWidget()
        self._list_slot.setFixedWidth(320)
        self._list_slot.setStyleSheet("background:transparent;")
        QVBoxLayout(self._list_slot).setContentsMargins(0, 0, 0, 0)
        split.addWidget(self._list_slot)

        self._detail_slot = QWidget()
        self._detail_slot.setStyleSheet("background:transparent;")
        QVBoxLayout(self._detail_slot).setContentsMargins(0, 0, 0, 0)
        split.addWidget(self._detail_slot, 1)
        outer.addLayout(split, 1)

        self.refresh()

    # -- data --------------------------------------------------------------- #
    def companions(self) -> list:
        """The save's henchmen, scanned once per save.

        The scan parses every area's ``.git`` — about a second on a real save with
        65 areas — and ``refresh()`` runs on every staged edit, so without this
        cache each edit would stall the window. Areas are never modified by the
        editor, so the result cannot go stale while a save is open.
        """
        save = self._window.save
        if save is None or save.sav_path is None:
            return []
        if self._scanned_for == save.sav_path:
            return self._cache
        info = save.module_info()
        areas = [resref for resref, _name in info.areas] if info is not None else []
        try:
            self._cache = find_companions(save.sav_path, areas)
        except Exception:
            self._cache = []
        self._scanned_for = save.sav_path
        return self._cache

    # -- rebuilding --------------------------------------------------------- #
    def refresh(self) -> None:
        self._companions = self.companions()
        self._note.setText(
            "Henchmen are ordinary creatures in the save's areas — these are the "
            "ones recognisable by NWN's NW_HEN_ tag convention or by following a "
            "master. A module using its own tags for its own henchmen will not "
            "appear. Read-only: area contents are never edited."
        )
        _fill(self._list_slot, self._build_list())
        _fill(self._detail_slot, self._build_detail())

    def _build_list(self) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(w.cap_label(f"Found ({len(self._companions)})"))
        if not self._companions:
            column.addWidget(w.body(
                "No henchmen found in this save's areas.", t.TEXT_3, 12.5
            ))
            column.addStretch(1)
            return holder

        if self._selected is None or self._selected >= len(self._companions):
            self._selected = 0
        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        rows = QVBoxLayout(inner)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        for index, companion in enumerate(self._companions):
            rows.addWidget(self._row(index, companion))
        rows.addStretch(1)
        column.addWidget(_scroll(inner), 1)
        return holder

    def _row(self, index: int, companion) -> QWidget:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame

        row = QFrame()
        row.setObjectName("CompanionRow")
        selected = index == self._selected
        row.setStyleSheet(
            f"#CompanionRow{{background:{t.gold_tint(0.15) if selected else t.INSET};"
            f"border:1px solid {t.gold_border(0.5) if selected else t.hairline(0.06)};"
            f"border-radius:8px;}}"
        )
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(row)
        column.setContentsMargins(12, 8, 12, 8)
        column.setSpacing(2)
        name = w.body(companion.display_name, t.TEXT, 12.5)
        name.setStyleSheet(name.styleSheet() + "font-weight:600;")
        column.addWidget(name)
        column.addWidget(w.body(
            f"{companion.area}  ·  {companion.current_hp}/{companion.max_hp} HP",
            t.TEXT_3, 11,
        ))
        row.mousePressEvent = lambda _e, i=index: self._choose(i)
        return row

    def _build_detail(self) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(10)
        if not self._companions or self._selected is None:
            column.addStretch(1)
            return holder

        companion = self._companions[self._selected]
        column.addWidget(w.heading(companion.display_name, 18))
        panel = w.Panel(padding=0)
        body = panel.body_layout()
        body.setSpacing(0)
        for label, value in (
            ("Tag", companion.tag),
            ("Area", companion.area),
            ("Hit points", f"{companion.current_hp} / {companion.max_hp}"),
            ("Experience", f"{companion.experience:,}"),
            ("Faction", str(companion.faction)),
            ("Following a master", "yes" if companion.is_associated else "no"),
        ):
            body.addWidget(_kv(label, value))
        column.addWidget(panel)
        if not companion.name:
            column.addWidget(w.body(
                "This creature stores no name of its own — the game takes its name "
                "from its blueprint, which is not part of the save.",
                t.TEXT_3, 11.5,
            ))
        column.addStretch(1)
        return holder

    def _choose(self, index: int) -> None:
        self._selected = index
        self.refresh()


def _kv(label: str, value: str) -> QWidget:
    row = QWidget()
    row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
    line = QHBoxLayout(row)
    line.setContentsMargins(14, 9, 14, 9)
    line.addWidget(w.body(label, t.TEXT_2, 12.5), 1)
    line.addWidget(w.mono(value, t.TEXT, 12))
    return row


def _scroll(body: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setStyleSheet("QScrollArea{background:transparent;border:none;}" + w.SCROLLBAR_QSS)
    area.setWidget(body)
    return area


def _fill(slot: QWidget, content: QWidget) -> None:
    layout = slot.layout()
    while layout.count():
        widget = layout.takeAt(0).widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
    layout.addWidget(content)
