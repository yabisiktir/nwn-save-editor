"""A browsable id/name picker — choose a feat or spell to add to a character.

A two-column **ID + Name** table you can scroll and click; typing in the search box
is an optional filter that matches the name *or* the raw id. Ids in ``mark_ids`` get
a suffix (e.g. ``(PRC)``) because editing them may not persist in-game.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

_ID_ROLE = Qt.ItemDataRole.UserRole


class IdPickerDialog(QDialog):
    """Pick an id from ``[(id, name)]`` — a filterable ID/Name table."""

    def __init__(
        self,
        title: str,
        items: Iterable[tuple[int, str]],
        *,
        mark_ids: frozenset[int] = frozenset(),
        mark_label: str = "",
        value_header: str = "Name",
        categories: tuple[tuple[str, str], ...] = (),
        category_of: dict[int, str] | None = None,
        allow_value: bool = False,
        initial: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        from nwnsaveeditor.ui.editor import widgets as w

        self._allow_value = allow_value
        self._value_box: QSpinBox | None = None
        self.setWindowTitle(title)
        self.resize(480, 520)
        self.setStyleSheet(w.dialog_qss())  # wear the editor's theme, not the app palette
        layout = QVBoxLayout(self)

        self._category_of = category_of or {}
        self._category = categories[0][0] if categories else "all"
        if categories:  # e.g. All / Applicable / Already taken
            self._modes = w.SegmentedControl(categories)
            self._modes.set_value(self._category)
            self._modes.changed.connect(self._choose_category)
            layout.addWidget(self._modes)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search by name or id…")
        self._filter.textChanged.connect(self._apply_filter)
        self._filter.returnPressed.connect(self.accept)  # Enter picks the top match
        layout.addWidget(self._filter)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(2)
        self._tree.setHeaderLabels(["ID", value_header])
        self._tree.setRootIsDecorated(False)
        self._tree.setSortingEnabled(True)
        self._tree.setUniformRowHeights(True)
        for id_, name in items:
            label = f"{name}  ({mark_label})" if id_ in mark_ids and mark_label else name
            row = QTreeWidgetItem(["", label])
            row.setData(0, Qt.ItemDataRole.DisplayRole, id_)  # int -> sorts numerically
            row.setData(0, _ID_ROLE, id_)
            self._tree.addTopLevelItem(row)
        self._tree.sortItems(1, Qt.SortOrder.AscendingOrder)  # by name
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if self._tree.topLevelItemCount():
            self._tree.setCurrentItem(self._tree.topLevelItem(0))  # always a selection
        self._tree.itemDoubleClicked.connect(lambda *_: self.accept())
        w.apply_tree_palette(self._tree)  # gold selection, themed base
        layout.addWidget(self._tree, 1)

        if allow_value:  # the raw tree lets you type any number, not only a listed one
            row = QHBoxLayout()
            row.addWidget(QLabel("Value:"))
            self._value_box = QSpinBox()
            self._value_box.setRange(-2_147_483_648, 2_147_483_647)
            self._value_box.setValue(initial if initial is not None else 0)
            row.addWidget(self._value_box, 1)
            layout.addLayout(row)
            # picking a row fills the field; the field is still free to overtype
            self._tree.currentItemChanged.connect(self._sync_value_from_row)
        if initial is not None:  # start on the current value
            self._select_id(initial)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _choose_category(self, category: str) -> None:
        self._category = category
        self._apply_filter(self._filter.text())

    def _in_category(self, id_) -> bool:
        return self._category == "all" or self._category_of.get(id_) == self._category

    def _apply_filter(self, text: str) -> None:
        needle = text.lower()
        first_visible = None
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            haystack = f"{row.text(0)} {row.text(1)}".lower()  # matches id or name
            hidden = needle not in haystack or not self._in_category(row.data(0, _ID_ROLE))
            row.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = row
        if first_visible is not None:  # keep a visible row selected for OK/Enter
            self._tree.setCurrentItem(first_visible)
        else:
            self._tree.setCurrentItem(None)  # nothing matches -> OK/Enter no-ops

    def _sync_value_from_row(self, current, _previous=None) -> None:
        if self._value_box is not None and current is not None:
            self._value_box.setValue(int(current.data(0, _ID_ROLE)))

    def _select_id(self, id_: int) -> None:
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            if row.data(0, _ID_ROLE) == id_:
                self._tree.setCurrentItem(row)
                self._tree.scrollToItem(row)
                return

    def selected_id(self) -> int | None:
        if self._value_box is not None:  # the typed value wins — any number is valid
            return self._value_box.value()
        row = self._tree.currentItem()
        if row is None or row.isHidden():
            return None
        return row.data(0, _ID_ROLE)
