"""A searchable id/name picker — choose a feat or spell to add to a character.

Lists ``(id, name)`` rows with a live text filter; ids in ``mark_ids`` get a
suffix (e.g. ``— PRC``) because editing them may not persist in-game.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

_ID_ROLE = Qt.ItemDataRole.UserRole


class IdPickerDialog(QDialog):
    """Pick an id from ``[(id, name)]`` with a search box."""

    def __init__(
        self,
        title: str,
        items: Iterable[tuple[int, str]],
        *,
        mark_ids: frozenset[int] = frozenset(),
        mark_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 480)
        layout = QVBoxLayout(self)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Search…")
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._list = QListWidget()
        for id_, name in sorted(items, key=lambda pair: pair[1].lower()):
            suffix = f"  — {mark_label}" if id_ in mark_ids and mark_label else ""
            item = QListWidgetItem(f"{name}  [{id_}]{suffix}")
            item.setData(_ID_ROLE, id_)
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _i: self.accept())
        layout.addWidget(self._list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_filter(self, text: str) -> None:
        needle = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(needle not in item.text().lower())

    def selected_id(self) -> int | None:
        item = self._list.currentItem()
        return item.data(_ID_ROLE) if item is not None else None
