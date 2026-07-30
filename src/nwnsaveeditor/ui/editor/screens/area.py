"""The Area Contents screen — browse an area's stores, creatures and containers.

An area picker on the left, its contents as a tree in the middle, and the detail
column on the right. Store *pricing* is editable; the items themselves are not.
Areas live in the save's ``.git`` resources, which the editor treats as read-only
— the only thing you can do with an item found here is take a copy into your own
inventory, which :class:`~vaultkeeper.ui.save_editor.screens.item_panels.AreaItemPanel`
is the sole route to.

Areas are decoded on demand: a save has many, and each one means reading and
parsing a resource out of the ``.sav``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.save_area import read_area_contents
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w
from vaultkeeper.ui.save_editor.screens.item_panels import AreaItemPanel

_ROLE = Qt.ItemDataRole.UserRole

_TREE_QSS = f"""
QTreeWidget {{
    background:{t.INSET}; border:1px solid {t.hairline(0.06)};
    border-radius:{t.RADIUS_PANEL}px; color:{t.TEXT};
    font-family:{t.UI_FAMILY}; font-size:12.5px; outline:none;
    show-decoration-selected:1;
}}
QTreeWidget::item {{ padding:5px 4px; border:none; }}
QTreeWidget::item:selected {{ background:{t.gold_tint(0.22)}; color:{t.GOLD}; }}
QTreeWidget::item:hover {{ background:{t.hairline(0.05)}; }}
/* The branch column is painted separately from the item; left unstyled it keeps
   the platform's blue selection block next to our gold row. */
QTreeWidget::branch {{ background:transparent; }}
QTreeWidget::branch:selected {{ background:{t.gold_tint(0.22)}; }}
"""


class AreaScreen(QWidget):
    """The Area Contents section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._area_resref: str | None = None
        self._area = None
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(16)

        # -- area picker --------------------------------------------------- #
        left = QWidget()
        left.setFixedWidth(220)
        left.setStyleSheet("background:transparent;")
        self._areas_column = QVBoxLayout(left)
        self._areas_column.setContentsMargins(0, 0, 0, 0)
        self._areas_column.setSpacing(8)
        outer.addWidget(left)

        # -- contents tree ------------------------------------------------- #
        middle = QWidget()
        middle.setStyleSheet("background:transparent;")
        self._middle = QVBoxLayout(middle)
        self._middle.setContentsMargins(0, 0, 0, 0)
        self._middle.setSpacing(10)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setStyleSheet(_TREE_QSS + w.SCROLLBAR_QSS)
        w.apply_tree_palette(self._tree)
        self._tree.currentItemChanged.connect(self._on_select)
        self._middle.addWidget(self._tree, 1)
        self._store_button = w.ghost_button("Edit Store…")
        self._store_button.setEnabled(False)
        self._store_button.clicked.connect(self._edit_store)
        self._middle.addWidget(self._store_button, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addWidget(middle, 1)

        # -- detail -------------------------------------------------------- #
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
        return self._window.property_tables()

    # -- rebuilding -------------------------------------------------------- #
    def refresh(self) -> None:
        self._build_area_picker()
        self._reload_area()

    def _areas(self) -> list[tuple[str, str]]:
        save = self._window.save
        if save is None:
            return []
        info = save.module_info()
        return list(info.areas) if info is not None else []

    def _build_area_picker(self) -> None:
        while self._areas_column.count():
            # Bind the widget once: a taken QLayoutItem hands over ownership, and
            # asking it for widget() a second time yields None.
            widget = self._areas_column.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        areas = self._areas()
        self._areas_column.addWidget(w.cap_label(f"Areas ({len(areas)})"))
        if not areas:
            self._areas_column.addWidget(w.body("This save lists no areas.", t.TEXT_3, 12))
            self._areas_column.addStretch(1)
            return
        if self._area_resref not in {resref for resref, _name in areas}:
            self._area_resref = areas[0][0]

        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        for resref, name in areas:
            row = w.NavRow(resref, name or resref, "AR")
            row.setChecked(resref == self._area_resref)
            row.setToolTip(resref)
            row.clicked.connect(lambda _=False, r=resref: self._choose_area(r))
            column.addWidget(row)
        column.addStretch(1)
        scroll = _scroll(holder)
        self._areas_column.addWidget(scroll, 1)

    def _choose_area(self, resref: str) -> None:
        self._area_resref = resref
        self.refresh()

    def _reload_area(self) -> None:
        """Decode the chosen area and rebuild the tree (areas are read on demand)."""
        # The tree is rebuilt on every refresh — including when the Edit gate moves
        # — so remember where the user was and put them back.
        was = self._current_path()
        self._tree.clear()
        self._show_detail(None)
        self._store_button.setEnabled(False)
        save = self._window.save
        if save is None or save.sav_path is None or self._area_resref is None:
            return
        self._area = read_area_contents(
            save.sav_path, self._area_resref, resolver=self._window._resolver()
        )
        if self._area is None:
            self._tree.addTopLevelItem(QTreeWidgetItem(["(this area could not be read)"]))
            return
        self._populate_tree(self._area)
        self._restore_path(was)

    def _current_path(self) -> list[int] | None:
        """The selected node as a list of row indices, stable across a rebuild."""
        node = self._tree.currentItem()
        if node is None:
            return None
        path = []
        while node is not None:
            parent = node.parent()
            container = parent or self._tree.invisibleRootItem()
            path.append(container.indexOfChild(node))
            node = parent
        return list(reversed(path))

    def _restore_path(self, path: list[int] | None) -> None:
        if not path:
            return
        node = self._tree.invisibleRootItem()
        for index in path:
            if index >= node.childCount():
                return
            node = node.child(index)
            node.setExpanded(True)
        self._tree.setCurrentItem(node)

    def _populate_tree(self, area) -> None:
        if area.stores:
            group = QTreeWidgetItem([f"Stores ({len(area.stores)})"])
            self._tree.addTopLevelItem(group)
            for index, store in enumerate(area.stores):
                node = QTreeWidgetItem([f"{store.name or store.tag or 'Store'}"])
                node.setData(0, _ROLE, ("store", index, store))
                group.addChild(node)
                for item in store.items:
                    node.addChild(self._item_node(item))
            group.setExpanded(True)

        if area.creatures:
            group = QTreeWidgetItem([f"Creatures ({len(area.creatures)})"])
            self._tree.addTopLevelItem(group)
            for creature in area.creatures:
                label = creature.name or creature.tag or "Creature"
                node = QTreeWidgetItem([f"{label}  ({creature.item_count})"])
                group.addChild(node)
                for equipped in creature.equipped:
                    node.addChild(self._item_node(equipped.item, prefix="⌾ "))
                for item in creature.carried:
                    node.addChild(self._item_node(item))

        if area.containers:
            group = QTreeWidgetItem([f"Containers ({len(area.containers)})"])
            self._tree.addTopLevelItem(group)
            for container in area.containers:
                label = container.name or container.tag or "Container"
                node = QTreeWidgetItem([f"{label}  ({len(container.items)})"])
                group.addChild(node)
                for item in container.items:
                    node.addChild(self._item_node(item))

        if self._tree.topLevelItemCount() == 0:
            self._tree.addTopLevelItem(
                QTreeWidgetItem(["Nothing here — no stores, creatures or containers."])
            )

    def _item_node(self, item, *, prefix: str = "") -> QTreeWidgetItem:
        node = QTreeWidgetItem([f"{prefix}{item.name}"])
        node.setData(0, _ROLE, ("item", item))
        for child in getattr(item, "contents", []) or []:  # container items nest
            node.addChild(self._item_node(child))
        return node

    # -- selection --------------------------------------------------------- #
    def _on_select(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        role = current.data(0, _ROLE) if current is not None else None
        self._store_button.setEnabled(bool(role) and role[0] == "store" and self.editing)
        if role and role[0] == "item":
            self._show_detail(role[1])
        else:
            self._show_detail(None)

    def _show_detail(self, item) -> None:
        layout = self._detail_slot.layout()
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        layout.addWidget(AreaItemPanel(self, item, self._area_resref or ""))

    # -- store editing ------------------------------------------------------ #
    def _edit_store(self) -> None:
        from vaultkeeper.ui.dialogs.store_edit_dialog import StoreEditDialog

        current = self._tree.currentItem()
        role = current.data(0, _ROLE) if current is not None else None
        if not role or role[0] != "store":
            return
        _kind, index, store = role
        dialog = StoreEditDialog(store, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.session().set_store_fields(
                self._area_resref, index, where=store.name or store.tag, **dialog.values()
            )
        except Exception as exc:
            QMessageBox.critical(self, "Edit failed", str(exc))
            return
        self._window.notify_changed()


def _scroll(body: QWidget):
    from PySide6.QtWidgets import QScrollArea

    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setStyleSheet("QScrollArea{background:transparent;border:none;}" + w.SCROLLBAR_QSS)
    area.setWidget(body)
    return area
