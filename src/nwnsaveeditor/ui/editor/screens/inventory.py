"""The Inventory & Equipment screen — equipment grid, carried bag, item detail.

The equipment slots reproduce the game's own inventory panel, slot for slot and
position for position (nwn.fandom.com/wiki/Inventory_slot). The handoff asked
for a humanoid arrangement instead and that is what this screen had, but a
layout that matches nothing forces anyone checking a character against the
running game to hunt for each slot; fidelity won.

The detail column is filled by :mod:`~nwnsaveeditor.ui.editor.screens.item_panels`,
which has a separate panel class per context so a store or creature item can never
be property-edited from here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from nwnfile.formats.bic_reader import EQUIP_SLOT_NAMES
from nwnfile.item_names import base_item_type
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w
from nwnsaveeditor.ui.editor.screens.item_panels import PlayerItemPanel, item_cell

#: ``(row, column)`` for each equipment slot bit, laid out as the game's own
#: inventory panel does it (nwn.fandom.com/wiki/Inventory_slot). Five columns:
#:
#:      main hand │ armor   │ off-hand │ helmet │ cloak
#:                │         │ belt     │ gloves │ boots
#:      arrows    │ bullets │ bolts    │ rings  │ amulet
#:
#: The gloves sit directly under the helmet, the boots under the cloak and the
#: belt under the off-hand, as they do in the game. The game additionally draws
#: the two weapon cells double height, which is not reproduced: that comes from
#: its panel being non-uniform, and in an even grid a tall main-hand cell only
#: displaces the belt out of the column it belongs in. Two earlier versions were
#: invented outright — one anatomical, one two flanking columns — and both made
#: anyone comparing against the running game hunt for each slot.
PAPERDOLL: dict[int, tuple[int, int]] = {
    16: (0, 0),       # Main hand
    2: (0, 1),        # Armor
    32: (0, 2),       # Off hand
    1: (0, 3),        # Helmet
    64: (0, 4),       # Cloak
    1024: (1, 2),     # Belt, under the off-hand
    8: (1, 3),        # Gloves, under the helmet
    4: (1, 4),        # Boots, under the cloak
    2048: (2, 0),     # Arrows ┐
    4096: (2, 1),     # Bullets├ ammunition, along the bottom-left
    8192: (2, 2),     # Bolts  ┘
    128: (2, 3),      # First ring
    256: (3, 3),      # Second ring
    512: (2, 4),      # Amulet
}

#: Slots the engine keeps for itself. On a PRC install the skin carries the feats
#: and bonuses PRC regenerates, so they are shown — apart, and clearly labelled.
CREATURE_SLOTS: tuple[int, ...] = (131072, 16384, 32768, 65536)


class Paperdoll(QWidget):
    """The equipment grid.

    Nothing is painted behind the cells. Earlier versions drew a humanoid
    outline, which only made sense while the slots were arranged as a body; the
    game's panel is a plain grid of slots and the figure would now sit across
    the ammunition.
    """


class InventoryScreen(QWidget):
    """The Inventory & Equipment section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._selected: tuple | None = None  # the selected item's GFF path
        self._sort = "type"  # matches the game's own inventory grouping
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
        # Read once: a character can have natural weapons recorded and none of
        # them equipped, which is exactly the case worth showing.
        natural = self._natural_weapons()
        if natural or any(bit in equipped for bit in CREATURE_SLOTS):
            column.addWidget(self._build_creature_slots(equipped, natural))

        # Split the bag by container. Two thirds of a real character's items live
        # inside bags, and a single flat grid gives no clue which item is in what.
        loose = [i for i in carried if len(i.path) == 1]
        inside: dict[tuple, list] = {}
        for item in carried:
            if len(item.path) > 1:
                inside.setdefault(tuple(item.path[:-1]), []).append(item)

        carried_header = QHBoxLayout()
        carried_header.addWidget(w.heading(f"Carried ({len(loose)})"))
        carried_header.addSpacing(16)
        carried_header.addWidget(w.cap_label("Sort"))
        order = w.SegmentedControl((("type", "By type"), ("name", "By name")))
        order.set_value(self._sort)
        order.changed.connect(lambda _o=order: self._set_sort(order.value()))
        carried_header.addWidget(order)
        carried_header.addStretch(1)
        column.addLayout(carried_header)
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

    def _build_creature_slots(self, equipped: dict, natural: list) -> QWidget:
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
        if natural:
            column.addWidget(self._build_natural_weapons(natural))
        return holder

    def _natural_weapons(self) -> list:
        try:
            return self._window.session().player_natural_weapons()
        except Exception:
            return []

    def _build_natural_weapons(self, weapons: list) -> QWidget:
        """What PRC has recorded, equipped or not.

        A claw or a bite is an ordinary item in a creature weapon slot, so only
        the one currently in hand appeared as equipment. PRC keeps the whole set
        in the character's VarTable and swaps them in by script, which is why a
        Dragon Disciple's bite could look as though the save had lost it.
        """
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 8, 0, 0)
        column.setSpacing(6)
        column.addWidget(w.cap_label(f"Natural weapons — PRC ({len(weapons)})"))
        column.addWidget(w.body(
            "PRC records these on the character and swaps them into the creature "
            "slots by script, so one being unequipped does not mean it is gone. "
            "The names come from the blueprint resref — the blueprints live in a "
            "hak, not in the save. Derived from your classes and feats, so this "
            "list is read-only.",
            t.TEXT_3, 11.5,
        ))
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        for weapon in weapons:
            panel.body_layout().addWidget(_natural_row(weapon))
        column.addWidget(panel)
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
        """Items in a stable, readable order — the GFF order is arbitrary.

        "Type" groups by base item the way the game's own inventory does (all the
        potions together, all the armour together); "Name" is a flat A–Z.
        """
        if self._sort == "type":
            return sorted(items, key=lambda i: (
                (base_item_type(i.base_item) or f"#{i.base_item}").lower(),
                self._name(i).lower(),
                tuple(i.path),
            ))
        return sorted(items, key=lambda i: (self._name(i).lower(), tuple(i.path)))

    def _set_sort(self, order: str) -> None:
        self._sort = order
        self.refresh()

    def _icon(self, item):
        icons = getattr(self._window, "_icons", None)
        if icons is None:
            return None
        from nwnsaveeditor.ui.icons import load_item_icon

        icon = load_item_icon(icons, item)
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


def _natural_row(weapon) -> QWidget:
    """One recorded natural weapon: what it is, and whether it is in hand."""
    row = QWidget()
    row.setStyleSheet(
        f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};"
    )
    line = QHBoxLayout(row)
    line.setContentsMargins(12, 6, 12, 6)
    line.setSpacing(10)
    line.addWidget(w.body(weapon.label, t.TEXT, 12.5), 1)
    line.addWidget(w.mono(weapon.group, t.TEXT_3, 11))
    line.addWidget(w.mono(weapon.resref, t.TEXT_3, 11))
    if weapon.equipped:
        slot = w.body(
            EQUIP_SLOT_NAMES.get(weapon.equipped_slot, "equipped"), t.GOLD, 11.5
        )
        slot.setToolTip("Currently in one of the creature weapon slots")
        line.addWidget(slot)
    else:
        line.addWidget(w.body("not in hand", t.TEXT_3, 11.5))
    return row
