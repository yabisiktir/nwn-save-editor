"""The item detail panels — one per context, deliberately not shared.

The handoff is explicit about this: an item selected in *your* inventory gets a
panel that can edit its magical properties, while an item selected in a store,
creature or container gets a different panel whose only action is **Add a copy to
my inventory**. They are separate classes rather than one panel with a flag, so a
cross-context edit is not merely disallowed — it has nowhere to be typed.

Every property field an editor offers comes from the game's ``iprp_*`` tables, so
an edit cannot produce a value the engine does not recognise. Changing a
property's *type* in place is not supported; remove it and add the one you want.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.item_names import base_item_type
from vaultkeeper.game.item_properties import describe_property
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w


class _PanelBase(QWidget):
    """Shared chrome: the fixed-width column, the item's name and base type."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(t.DETAIL_W)
        self.setStyleSheet(
            f"_PanelBase{{background:{t.SURFACE};border:1px solid {t.hairline(0.06)};"
            f"border-radius:{t.RADIUS_PANEL}px;}}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}" + w.SCROLLBAR_QSS
        )
        body = QWidget()
        body.setStyleSheet("background:transparent;")
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(14, 14, 14, 14)
        self._body.setSpacing(10)
        area.setWidget(body)
        outer.addWidget(area)

    def _add_identity(self, item) -> None:
        name = w.body(item.name or "(unnamed item)", t.TEXT, 14)
        name.setStyleSheet(name.styleSheet() + "font-weight:600;")
        self._body.addWidget(name)
        kind = base_item_type(item.base_item)
        self._body.addWidget(w.body(kind or f"Base item {item.base_item}", t.TEXT_2, 12))
        if getattr(item, "resref", ""):
            self._body.addWidget(w.mono(item.resref, t.TEXT_3, 11))
        self._body.addWidget(w.hline())

    def _empty(self, message: str) -> None:
        self._body.addWidget(w.body(message, t.TEXT_3, 12.5))
        self._body.addStretch(1)


class PlayerItemPanel(_PanelBase):
    """Your own item: its magical properties, editable from the ``iprp_*`` tables."""

    def __init__(self, screen, item, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._screen = screen
        self._item = item
        if item is None:
            self._empty("Select an item to see its magical properties.")
            return
        self._add_identity(item)

        header = QHBoxLayout()
        header.addWidget(w.cap_label(f"Properties ({len(item.properties)})"))
        header.addStretch(1)
        if screen.editing:
            add = w.small_ghost("Add a property…")
            add.clicked.connect(self._add_property)
            header.addWidget(add)
        self._body.addLayout(header)

        if not item.properties:
            self._body.addWidget(w.body("This item has no magical properties.", t.TEXT_3, 12))
        pending = screen.pending_property_keys()
        added = screen.pending_added_property_keys()
        for prop in item.properties:
            key = (tuple(item.path), prop.index)
            self._body.addWidget(
                self._property_row(prop, dirty=key in pending, is_new=key in added)
            )
        self._body.addStretch(1)

    def _property_row(self, prop, *, dirty: bool, is_new: bool) -> QWidget:
        row = QWidget()
        row.setStyleSheet(
            f"background:{t.gold_tint(0.12) if (dirty or is_new) else 'transparent'};"
            f"border-radius:6px;"
        )
        column = QVBoxLayout(row)
        column.setContentsMargins(8, 7, 8, 7)
        column.setSpacing(6)

        line = QHBoxLayout()
        line.setSpacing(8)
        if dirty or is_new:
            line.addWidget(w.status_dot())
        text = w.body(
            describe_property(prop.prop, None),
            t.GOLD if (dirty or is_new) else t.TEXT, 12.5,
        )
        line.addWidget(text, 1)
        column.addLayout(line)

        if self._screen.editing:
            actions = QHBoxLayout()
            actions.setSpacing(6)
            actions.addStretch(1)
            edit = w.small_ghost("Edit…")
            edit.clicked.connect(lambda _=False, p=prop: self._edit_property(p))
            actions.addWidget(edit)
            remove = w.small_ghost("×")
            remove.setToolTip("Remove this property")
            remove.clicked.connect(lambda _=False, p=prop: self._remove_property(p))
            actions.addWidget(remove)
            column.addLayout(actions)
        return row

    # -- actions ---------------------------------------------------------- #
    def _edit_property(self, prop) -> None:
        from vaultkeeper.ui.dialogs.property_editor_dialog import PropertyEditorDialog

        tables = self._screen.property_tables()
        if tables is None:
            QMessageBox.information(
                self, "Property tables unavailable",
                "The game's iprp_* tables could not be read, so this property's "
                "valid values are unknown. Set the game folder in Settings and "
                "reopen the editor.",
            )
            return
        dialog = PropertyEditorDialog(prop.prop, tables, prop.prop.param1, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        edits = dialog.result()
        if not edits:
            return
        self._screen.session().set_property(
            self._item.path, prop.index, where=self._item.name, **edits
        )
        self._screen.changed()

    def _remove_property(self, prop) -> None:
        confirm = QMessageBox.question(
            self, "Remove property",
            f"Remove “{describe_property(prop.prop, None)}” from {self._item.name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._screen.session().remove_item_property(
            self._item.path, prop.index, where=self._item.name
        )
        self._screen.changed()

    def _add_property(self) -> None:
        from vaultkeeper.ui.dialogs.add_property_dialog import AddPropertyDialog

        dialog = AddPropertyDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.values()
        if values is None:
            return
        self._screen.session().add_item_property(
            self._item.path, where=self._item.name, **values
        )
        self._screen.changed()


class AreaItemPanel(_PanelBase):
    """A store / creature / container item: copyable, never editable.

    Deliberately has no property editor at all. These items live in an area's
    ``.git``, which the editor treats as read-only — the only thing you can do
    with one is take a copy into your own inventory.
    """

    def __init__(self, screen, item, area_resref: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._screen = screen
        self._item = item
        self._area_resref = area_resref
        if item is None:
            self._empty("Select an item to see it.")
            return
        self._add_identity(item)

        self._body.addWidget(w.cap_label("Properties"))
        properties = getattr(item, "properties", []) or []
        if not properties:
            self._body.addWidget(w.body("No magical properties.", t.TEXT_3, 12))
        for prop in properties:
            label = w.body(describe_property(getattr(prop, "prop", prop), None), t.TEXT_2, 12.5)
            self._body.addWidget(label)

        self._body.addWidget(w.hline())
        self._action_slot = QWidget()
        self._action_slot.setStyleSheet("background:transparent;")
        QVBoxLayout(self._action_slot).setContentsMargins(0, 0, 0, 0)
        self._body.addWidget(self._action_slot)
        self._show_action()
        self._body.addWidget(w.body(
            "Items here belong to the world, not to you — Vaultkeeper never edits "
            "them. Taking a copy adds a new item to your own inventory.",
            t.TEXT_3, 11.5,
        ))
        self._body.addStretch(1)

    def _show_action(self, *, copied: bool = False) -> None:
        layout = self._action_slot.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if copied:
            done = QLabel("●  Copy added to inventory")
            done.setStyleSheet(
                f"color:{t.GOLD};font-family:{t.UI_FAMILY};font-size:12.5px;"
                f"font-weight:600;background:transparent;"
            )
            layout.addWidget(done)
            return
        button = w.gold_button("Add a copy to my inventory")
        button.setEnabled(self._screen.editing)
        if not self._screen.editing:
            button.setToolTip("Turn on Edit to take a copy")
        button.clicked.connect(self._copy_to_inventory)
        layout.addWidget(button)

    def _copy_to_inventory(self) -> None:
        try:
            self._screen.session().add_item_from_area(
                self._area_resref, self._item.resref, where=self._item.name
            )
        except Exception as exc:  # SaveEditError and friends
            QMessageBox.critical(self, "Copy failed", str(exc))
            return
        self._show_action(copied=True)
        self._screen.changed()


def item_cell(
    label: str, *, filled: bool, selected: bool, tooltip: str = "", icon=None
) -> QLabel:
    """One 62px inventory/equipment cell.

    Empty cells are dashed with their slot name; filled cells get a solid gold
    border, and the selected one is brighter still.
    """
    cell = QLabel(label)
    cell.setFixedSize(t.ITEM_CELL, t.ITEM_CELL)
    cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cell.setWordWrap(True)
    cell.setToolTip(tooltip or label)
    if selected:
        border = f"2px solid {t.GOLD}"
        background = t.gold_tint(0.22)
    elif filled:
        border = f"1px solid {t.gold_border(0.5)}"
        background = t.INSET
    else:
        border = f"1px dashed {t.hairline(0.16)}"
        background = "transparent"
    cell.setStyleSheet(
        f"border:{border};background:{background};border-radius:{t.RADIUS_ROW}px;"
        f"color:{t.TEXT if filled else t.TEXT_3};font-family:{t.UI_FAMILY};"
        f"font-size:{9 if filled else 8.5}px;font-weight:{600 if filled else 500};"
        f"padding:2px;"
    )
    if icon is not None:
        cell.setPixmap(icon)
        cell.setText("")
    if filled:
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
    return cell
