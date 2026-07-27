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
    QHeaderView,
    QLineEdit,
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 520)
        layout = QVBoxLayout(self)

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
        layout.addWidget(self._tree, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        needle = text.lower()
        first_visible = None
        for i in range(self._tree.topLevelItemCount()):
            row = self._tree.topLevelItem(i)
            haystack = f"{row.text(0)} {row.text(1)}".lower()  # matches id or name
            hidden = needle not in haystack
            row.setHidden(hidden)
            if not hidden and first_visible is None:
                first_visible = row
        if first_visible is not None:  # keep a visible row selected for OK/Enter
            self._tree.setCurrentItem(first_visible)

    def selected_id(self) -> int | None:
        row = self._tree.currentItem()
        if row is None or row.isHidden():
            return None
        return row.data(0, _ID_ROLE)
