"""The Inventory & Equipment screen — paperdoll, carried bag, item detail.

The equipment slots are laid out as a humanoid rather than a flat grid (a review
note in the handoff asked for this): a head circle and torso outline are painted
behind the cells, and the paired slots — weapon/shield, the two rings, the two
creature weapons — sit mirrored left and right of the body axis.

The detail column is filled by :mod:`~vaultkeeper.ui.save_editor.screens.item_panels`,
which has a separate panel class per context so a store or creature item can never
be property-edited from here.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.formats.bic_reader import EQUIP_SLOT_NAMES
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w
from vaultkeeper.ui.save_editor.screens.item_panels import PlayerItemPanel, item_cell

#: ``(row, column)`` for each equipment slot bit, arranged as a body.
#: Column 1 is the body axis; 0 and 2 are the mirrored right/left pairs.
PAPERDOLL: dict[int, tuple[int, int]] = {
    1: (0, 1),        # Head
    512: (1, 0),      # Neck
    2: (1, 1),        # Chest
    64: (1, 2),       # Cloak
    16: (2, 0),       # Right Hand (weapon)
    1024: (2, 1),     # Belt
    32: (2, 2),       # Left Hand (shield)
    256: (3, 0),      # Right Ring
    8: (3, 1),        # Arms
    128: (3, 2),      # Left Ring
    2048: (4, 0),     # Arrows
    4: (4, 1),        # Boots
    8192: (4, 2),     # Bolts
    4096: (5, 1),     # Bullets
}

#: Slots the engine keeps for itself. On a PRC install the skin carries the feats
#: and bonuses PRC regenerates, so they are shown — apart, and clearly labelled.
CREATURE_SLOTS: tuple[int, ...] = (131072, 16384, 32768, 65536)

_PAPERDOLL_COLS = 3
_PAPERDOLL_ROWS = 6


class Paperdoll(QWidget):
    """The equipment grid, with a humanoid outline painted behind the cells."""

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 20), 2))

        width, height = self.width(), self.height()
        column = width / _PAPERDOLL_COLS
        row = height / _PAPERDOLL_ROWS
        centre = column * 1.5

        # Head: a circle around the top-centre cell.
        head = min(column, row) * 0.62
        painter.drawEllipse(QRectF(centre - head / 2, row * 0.5 - head / 2, head, head))
        # Torso: a rounded column behind the body axis, from chest to boots.
        torso_w = column * 0.92
        painter.drawRoundedRect(
            QRectF(centre - torso_w / 2, row * 1.05, torso_w, row * 3.9), 18, 18
        )


class InventoryScreen(QWidget):
    """The Inventory & Equipment section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._selected: tuple | None = None  # the selected item's GFF path
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(20)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setStyleSheet(w.scroll_area_qss())
        outer.addWidget(self._scroll, 1)

        self._detail_slot = QWidget()
        self._detail_slot.setFixedWidth(t.DETAIL_W)
        self._detail_slot.setStyleSheet("background:transparent;")
        QVBoxLayout(self._detail_slot).setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._detail_slot)

        self.refresh()

    # -- the surface item_panels is built against ------------------------- #
    @property
    def editing(self) -> bool:
        return self._window.editing

    def session(self):
        return self._window.session()

    def changed(self) -> None:
        self._window.notify_changed()

    def property_tables(self):
        """The game's ``iprp_*`` option tables, or ``None`` if unreadable."""
        return self._window.property_tables()

    def pending_property_keys(self) -> set[tuple]:
        return {
            c.key for c in self._pending()
            if c.kind == "property" and isinstance(c.key, tuple)
        }

    def pending_added_property_keys(self) -> set[tuple]:
        return {
            c.key for c in self._pending()
            if c.kind == "prop-add" and isinstance(c.key, tuple)
        }

    def _pending(self):
        session = self._window._session
        return session.pending_changes() if session is not None else []

    # -- rebuilding ------------------------------------------------------- #
    def refresh(self) -> None:
        try:
            items = self._window.session().player_items()
        except Exception:
            items = []
        by_path = {tuple(item.path): item for item in items}
        if self._selected not in by_path:
            self._selected = None

        equipped = {item.slot: item for item in items if item.slot is not None}
        carried = [item for item in items if item.slot is None]

        # Build a brand-new content widget rather than clearing the old one in
        # place: a QScrollArea with widgetResizable sizes its widget once and does
        # not re-measure when that widget's children are swapped, which left the
        # column crushed into the viewport with sections overlapping.
        content = QWidget()
        content.setStyleSheet("background:transparent;")
        column = QVBoxLayout(content)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(16)

        column.addWidget(w.heading("Equipment"))
        column.addWidget(self._build_paperdoll(equipped), 0, Qt.AlignmentFlag.AlignLeft)
        if any(bit in equipped for bit in CREATURE_SLOTS):
            column.addWidget(self._build_creature_slots(equipped))

        # Split the bag by container. Two thirds of a real character's items live
        # inside bags, and a single flat grid gives no clue which item is in what.
        loose = [i for i in carried if len(i.path) == 1]
        inside: dict[tuple, list] = {}
        for item in carried:
            if len(item.path) > 1:
                inside.setdefault(tuple(item.path[:-1]), []).append(item)

        column.addWidget(w.heading(f"Carried ({len(loose)})"))
        column.addWidget(self._build_bag(self._sorted(loose)))
        # A character can carry several identically-named bags, so number the
        # repeats — "Inside Bag of Holding" seven times tells you nothing.
        seen: dict[str, int] = {}
        for parent_path, contents in sorted(
            inside.items(), key=lambda kv: self._name(by_path.get(kv[0])).lower()
        ):
            container = by_path.get(parent_path)
            label = self._name(container) or "container"
            seen[label] = seen.get(label, 0) + 1
            total = sum(
                1 for path in inside
                if (self._name(by_path.get(path)) or "container") == label
            )
            if total > 1:
                label = f"{label} #{seen[label]}"
            column.addWidget(w.cap_label(f"Inside {label} ({len(contents)})"))
            column.addWidget(self._build_bag(self._sorted(contents)))
        column.addStretch(1)
        w.set_scroll_widget(self._scroll, content)  # takes ownership; the old widget is dropped
        self._show_detail(by_path.get(self._selected))

    def _build_paperdoll(self, equipped: dict) -> QWidget:
        doll = Paperdoll()
        doll.setStyleSheet("background:transparent;")
        grid = QGridLayout(doll)
        grid.setSpacing(10)
        grid.setContentsMargins(10, 10, 10, 10)
        for bit, (row, column) in PAPERDOLL.items():
            grid.addWidget(self._slot_cell(bit, equipped.get(bit)), row, column)
        doll.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return doll

    def _build_creature_slots(self, equipped: dict) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(w.cap_label("Creature slots"))
        column.addWidget(w.body(
            "Engine-owned slots. On a PRC install the skin carries the feats and "
            "bonuses PRC regenerates, so edits here are the ones most likely to "
            "be undone in-game.",
            t.TEXT_3, 11.5,
        ))
        row = QHBoxLayout()
        row.setSpacing(10)
        for bit in CREATURE_SLOTS:
            if bit in equipped:
                row.addWidget(self._slot_cell(bit, equipped[bit]))
        row.addStretch(1)
        column.addLayout(row)
        return holder

    def _slot_cell(self, bit: int, item):
        slot_name = EQUIP_SLOT_NAMES.get(bit, f"Slot {bit}")
        if item is None:
            return item_cell(slot_name, filled=False, selected=False, tooltip=slot_name)
        name = self._name(item)
        cell = item_cell(
            _code(name), filled=True,
            selected=tuple(item.path) == self._selected,
            tooltip=f"{name}\n{slot_name}",
            icon=self._icon(item),
        )
        cell.mousePressEvent = _left_click(lambda p=tuple(item.path): self._select(p))
        return cell

    def _build_bag(self, carried: list) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        # A widget carrying its own layout can still be squeezed below its
        # minimumSizeHint, which flattened a 156-item bag into slivers. Fixing the
        # vertical policy makes the grid's height non-negotiable and lets the
        # surrounding scroll area do the scrolling.
        holder.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        grid = QGridLayout(holder)
        grid.setSpacing(10)
        grid.setContentsMargins(0, 0, 0, 0)
        columns = 8
        if not carried:
            grid.addWidget(w.body("Nothing carried.", t.TEXT_3, 12), 0, 0)
            return holder
        for index, item in enumerate(carried):
            name = self._name(item)
            cell = item_cell(
                _code(name), filled=True,
                selected=tuple(item.path) == self._selected,
                tooltip=name, icon=self._icon(item),
            )
            cell.mousePressEvent = _left_click(lambda p=tuple(item.path): self._select(p))
            grid.addWidget(cell, index // columns, index % columns)
        grid.setColumnStretch(columns, 1)
        return holder

    def _name(self, item) -> str:
        return self._window.item_name(item) if item is not None else ""

    def _sorted(self, items: list) -> list:
        """Items in a stable, readable order — the GFF order is arbitrary."""
        return sorted(items, key=lambda i: (self._name(i).lower(), tuple(i.path)))

    def _icon(self, item):
        icons = getattr(self._window, "_icons", None)
        if icons is None:
            return None
        from vaultkeeper.ui.dialogs.inventory_view import _load_icon

        icon = _load_icon(icons, item)
        return icon.pixmap(t.ITEM_CELL - 12, t.ITEM_CELL - 12) if icon is not None else None

    # -- selection -------------------------------------------------------- #
    def _select(self, path: tuple) -> None:
        self._selected = path
        self.refresh()

    def _show_detail(self, item) -> None:
        layout = self._detail_slot.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                w.retire(widget)
        layout.addWidget(PlayerItemPanel(self, item))


def _code(name: str) -> str:
    """A short cell label for an item with no icon — the design's 2-3 letter code."""
    letters = "".join(ch for ch in name if ch.isalpha())
    return letters[:3].upper() or "??"

def _left_click(action):
    """A mousePressEvent handler that fires only on the left button.

    Right-clicking a cell used to select it, which was never intended — these are
    click targets, not context menus.
    """
    from PySide6.QtCore import Qt

    def handler(event):
        if event.button() == Qt.MouseButton.LeftButton:
            action()

    return handler
