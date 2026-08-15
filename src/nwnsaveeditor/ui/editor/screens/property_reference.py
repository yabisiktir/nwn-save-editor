"""The Property Reference — what item properties exist, and where yours are.

Read-only, deliberately. Leto exposed the raw ``iprp_*`` tables because it had no
semantic layer; this editor already drives every property editor from those same
tables, so a value you cannot pick is a value the engine would not accept. What
was missing is *discoverability*: no way to ask "which of my items grant
Regeneration?" or "what values can a Skill bonus take?" without opening an item
and starting an edit.

So this answers those two questions and offers no edit surface at all.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from nwnfile.formats.bic_reader import EQUIP_SLOT_NAMES
from nwnfile.item_properties import describe_property
from nwnsaveeditor.active_bonuses import _source_label
from nwnsaveeditor.ui.editor import tokens as t
from nwnsaveeditor.ui.editor import widgets as w

#: A property's option tables can be huge (Cast Spell has 1,316 subtypes), so the
#: lists are capped and say how many more there are.
SHOWN = 60


class PropertyReferenceScreen(QWidget):
    """The Property Reference section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._selected: int | None = None
        self._filter = ""
        #: the item property the raw tree currently has selected, decoded — the
        #: panel leads with *this* rather than a context-free catalog when set.
        self._decoded = None
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(16)

        left = QWidget()
        left.setFixedWidth(300)
        left.setStyleSheet("background:transparent;")
        self._left = QVBoxLayout(left)
        self._left.setContentsMargins(0, 0, 0, 0)
        self._left.setSpacing(8)
        outer.addWidget(left)

        # The heading, the search box and the list's scroll area are built once
        # and never rebuilt. Typing in the box calls refresh() on every keystroke,
        # so a box built *inside* refresh() is destroyed under the user's hands —
        # focus and caret go with it. Keeping it alive but re-attaching would not
        # help either: setParent(None) clears focus on the way past.
        self._left.addWidget(w.heading("Properties"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter by name or id…")
        self._search.setStyleSheet(_input_qss())
        self._search.textChanged.connect(self._set_filter)
        self._left.addWidget(self._search)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._list_scroll.setStyleSheet(w.scroll_area_qss())
        self._left.addWidget(self._list_scroll, 1)

        self._detail_scroll = QScrollArea()
        self._detail_scroll.setWidgetResizable(True)
        self._detail_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._detail_scroll.setStyleSheet(w.scroll_area_qss())
        outer.addWidget(self._detail_scroll, 1)

        self.refresh()

    # -- data -------------------------------------------------------------- #
    def _tables(self):
        return self._window.property_tables()

    def _items(self) -> list:
        try:
            return self._window.session().player_items()
        except Exception:
            return []

    def _uses(self, property_id: int) -> list[tuple[str, str, object]]:
        """``(where, slot, property)`` for every item of yours carrying this type."""
        out = []
        for item in self._items():
            for entry in item.properties:
                if entry.prop.property_name != property_id:
                    continue
                slot = (
                    EQUIP_SLOT_NAMES.get(item.slot, f"slot {item.slot}")
                    if item.slot is not None else "carried"
                )
                # Reuse the label Active bonuses credits the skin with, so the
                # same item does not read two different ways in one editor.
                out.append((_source_label(item, self._window.item_name(item)), slot, entry.prop))
        return out

    def inspect_property(self, prop) -> None:
        """Lead with the item property the raw tree just selected, decoded — or
        pass ``None`` to fall back to browsing the catalog."""
        self._decoded = prop
        self.refresh()

    # -- rebuilding -------------------------------------------------------- #
    def refresh(self) -> None:
        """Rebuild only the property list; the heading, search box and scroll
        area are the screen's furniture and are left exactly where they are."""
        tables = self._tables()
        if tables is None or not tables.available:
            self._search.setVisible(False)
            w.set_scroll_widget(self._list_scroll, w.body(
                "The game's iprp_* tables could not be read. Set the game folder "
                "in Settings and reopen the editor.",
                t.TEXT_3, 12.5,
            ))
            self._show_detail(None)
            return

        self._search.setVisible(True)
        needle = self._filter.strip().lower()
        ids = [
            pid for pid in tables.property_ids()
            if not needle
            or needle in (tables.property_name_label(pid) or "").lower()
            or needle == str(pid)
        ]
        if self._decoded is not None:  # the tree selection pins the property
            self._selected = self._decoded.property_name
        elif self._selected not in ids:
            self._selected = ids[0] if ids else None

        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        carried = {p.prop.property_name for i in self._items() for p in i.properties}
        for pid in ids:
            column.addWidget(self._row(pid, tables, pid in carried))
        column.addStretch(1)
        w.set_scroll_widget(self._list_scroll, holder)
        self._show_detail(self._selected)

    def _row(self, property_id: int, tables, mine: bool) -> QWidget:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QFrame

        row = QFrame()
        row.setObjectName("PropRow")
        selected = property_id == self._selected
        row.setStyleSheet(
            f"#PropRow{{background:{t.gold_tint(0.15) if selected else 'transparent'};"
            f"border:1px solid "
            f"{t.gold_border(0.5) if selected else 'transparent'};"
            f"border-radius:6px;}}"
        )
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        line = QHBoxLayout(row)
        line.setContentsMargins(10, 6, 10, 6)
        line.setSpacing(8)
        label = tables.property_name_label(property_id) or f"#{property_id}"
        line.addWidget(w.body(label, t.GOLD if selected else t.TEXT, 12.5), 1)
        if mine:
            # A quiet marker beats a separate "my properties" list to keep in sync.
            dot = w.status_dot()
            dot.setToolTip("One of your items carries this")
            line.addWidget(dot)
        line.addWidget(w.mono(str(property_id), t.TEXT_3, 11))
        row.mousePressEvent = _left_click(lambda p=property_id: self._choose(p))
        return row

    def _show_detail(self, property_id: int | None) -> None:
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(12)
        tables = self._tables()
        if property_id is None or tables is None:
            column.addStretch(1)
            w.set_scroll_widget(self._detail_scroll, body)
            return

        label = tables.property_name_label(property_id) or f"#{property_id}"
        decoded = self._decoded if (
            self._decoded is not None and self._decoded.property_name == property_id
        ) else None
        highlight_subtype = decoded.subtype if decoded else None
        highlight_cost = decoded.cost_value if decoded else None
        highlight_param = decoded.param1_value if decoded else None

        if decoded is not None:  # this is the exact property selected in the tree
            column.addWidget(self._decoded_header(decoded, tables))
        column.addWidget(w.heading(label, 18))
        column.addWidget(w.mono(f"property id {property_id}", t.TEXT_3, 11.5))

        uses = self._uses(property_id)
        column.addWidget(w.cap_label(f"On your items ({len(uses)})"))
        if not uses:
            column.addWidget(w.body("None of your items carry this.", t.TEXT_3, 12.5))
        else:
            panel = w.Panel(padding=0)
            panel.body_layout().setSpacing(0)
            for where, slot, prop in uses[:SHOWN]:
                panel.body_layout().addWidget(
                    _kv(f"{where}  ·  {slot}", describe_property(prop, None))
                )
            column.addWidget(panel)
            if len(uses) > SHOWN:
                column.addWidget(w.body(f"… and {len(uses) - SHOWN} more", t.TEXT_3, 11))

        subtypes = tables.subtype_options(property_id)
        column.addWidget(self._options_block(
            "Subtypes", subtypes,
            "What the property applies to — which ability, skill, damage type or spell.",
            highlight=highlight_subtype,
        ))
        cost_table = tables.cost_table_for(property_id)
        values = tables.cost_options(cost_table) if cost_table is not None else {}
        column.addWidget(self._options_block(
            "Values", values or None,
            "The magnitudes the game accepts. A property's stored CostValue is a "
            "row in this table, not the number itself.",
            highlight=highlight_cost,
        ))
        params = tables.param1_options(property_id)
        if params:
            column.addWidget(self._options_block(
                "Parameters", params, "", highlight=highlight_param
            ))

        column.addStretch(1)
        w.set_scroll_widget(self._detail_scroll, body)

    def _decoded_header(self, prop, tables) -> QWidget:
        """The selected property, spelled out — the one-line description plus the
        exact row each coded value points at, so a raw struct reads as English."""
        holder = QWidget()
        holder.setObjectName("Decoded")
        holder.setStyleSheet(
            f"#Decoded{{background:{t.gold_tint(0.12)};border:1px solid "
            f"{t.gold_border(0.4)};border-radius:8px;}}"
        )
        column = QVBoxLayout(holder)
        column.setContentsMargins(12, 10, 12, 10)
        column.setSpacing(4)
        column.addWidget(w.cap_label("This entry"))
        line = w.body(describe_property(prop, None, tables=tables), t.GOLD, 14)
        line.setWordWrap(True)
        column.addWidget(line)

        def named(options, key):
            return (options or {}).get(key)

        pid = prop.property_name
        cost_table = tables.cost_table_for(pid)
        costs = tables.cost_options(cost_table) if cost_table is not None else {}
        bits = [
            _coded("Subtype", prop.subtype, named(tables.subtype_options(pid), prop.subtype)),
            _coded("CostValue", prop.cost_value, named(costs, prop.cost_value)),
        ]
        params = tables.param1_options(pid)
        if params:
            bits.append(_coded("Param1Value", prop.param1_value, named(params, prop.param1_value)))
        column.addWidget(w.body("   ".join(bits), t.TEXT_2, 12))
        return holder

    def _options_block(self, title: str, options, blurb: str, *, highlight=None) -> QWidget:
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        count = len(options) if options else 0
        column.addWidget(w.cap_label(f"{title} ({count})"))
        if blurb:
            column.addWidget(w.body(blurb, t.TEXT_3, 11.5))
        if not options:
            column.addWidget(w.body(
                f"This property takes no {title.lower()}.", t.TEXT_3, 12
            ))
            return holder
        panel = w.Panel(padding=0)
        panel.body_layout().setSpacing(0)
        # Put the highlighted row (the current value) first so it is not lost past
        # the SHOWN cap, then the rest in table order.
        rows = list(options.items())
        if highlight is not None and highlight in options:
            rows.sort(key=lambda kv: kv[0] != highlight)
        for row, text in rows[:SHOWN]:
            panel.body_layout().addWidget(_kv(str(text), f"row {row}", current=row == highlight))
        column.addWidget(panel)
        if count > SHOWN:
            column.addWidget(w.body(f"… and {count - SHOWN} more", t.TEXT_3, 11))
        return holder

    # -- actions ----------------------------------------------------------- #
    def _choose(self, property_id: int) -> None:
        self._selected = property_id
        self.refresh()

    def _set_filter(self, text: str) -> None:
        self._filter = text
        self.refresh()


def _kv(label: str, value: str, *, current: bool = False) -> QWidget:
    row = QWidget()
    bg = t.gold_tint(0.16) if current else "transparent"
    row.setStyleSheet(f"background:{bg};border-bottom:1px solid {t.hairline(0.06)};")
    line = QHBoxLayout(row)
    line.setContentsMargins(12, 6, 12, 6)
    line.setSpacing(10)
    line.addWidget(w.body(label, t.GOLD if current else t.TEXT, 12), 1)
    if current:
        line.addWidget(w.body("this entry", t.GOLD, 11))
    line.addWidget(w.mono(value, t.TEXT_3, 11))
    return row


def _coded(field: str, value: int, name) -> str:
    """``CostValue 2 = 1d6`` — a coded field's raw number and what it names."""
    return f"{field} {value}" + (f" = {name}" if name else "")


def _input_qss() -> str:
    return (
        f"QLineEdit{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};"
        f"font-size:12px;padding:6px 9px;}}"
    )


def _left_click(action):
    """Fire only on the left button — these rows are click targets, not menus."""
    from PySide6.QtCore import Qt

    def handler(event):
        if event.button() == Qt.MouseButton.LeftButton:
            action()

    return handler
