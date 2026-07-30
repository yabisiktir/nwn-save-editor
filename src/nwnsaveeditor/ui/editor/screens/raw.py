"""The Raw Data (GFF) screen — the escape hatch.

Browse the decoded struct/field tree of a save's resources directly, and edit
scalar leaves. This bypasses every friendly editor, so its edits are marked
``raw`` in the ledger and it refuses anything that would change a field's type —
a raw edit should be able to break the *rules*, not the *file*.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.core.formats.gff import GffList, GffStruct
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

_ROLE = Qt.ItemDataRole.UserRole
#: Nodes are built lazily; a save's tree is far too large to expand eagerly.
_LAZY = "…"

_COMBO_QSS = (
    f"QComboBox{{background:#1e1713;border:1px solid {t.hairline(0.22)};"
    f"border-radius:5px;color:{t.TEXT};font-family:{t.MONO_FAMILY};"
    f"font-size:12px;padding:5px 8px;}}"
    f"QComboBox QAbstractItemView{{background:#1e1713;color:{t.TEXT};"
    f"selection-background-color:{t.gold_tint(0.5)};selection-color:{t.GOLD};}}"
)

_TREE_QSS = f"""
QTreeWidget {{
    background:{t.INSET}; border:1px solid {t.hairline(0.06)};
    border-radius:{t.RADIUS_PANEL}px; color:{t.TEXT};
    font-family:{t.MONO_FAMILY}; font-size:12px; outline:none;
}}
QTreeWidget::item {{ padding:3px 4px; border:none; }}
QTreeWidget::item:selected {{ background:{t.gold_tint(0.22)}; color:{t.GOLD}; }}
QTreeWidget::item:hover {{ background:{t.hairline(0.05)}; }}
QTreeWidget::branch {{ background:transparent; }}
QTreeWidget::branch:selected {{ background:{t.gold_tint(0.22)}; }}
QHeaderView::section {{
    background:{t.SURFACE}; color:{t.TEXT_2}; border:none;
    border-bottom:1px solid {t.hairline(0.08)}; padding:6px 8px;
    font-family:{t.UI_FAMILY}; font-size:11px; font-weight:600;
}}
"""


class RawScreen(QWidget):
    """The Raw Data (GFF) section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._target = "module.ifo"
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(12)

        outer.addWidget(w.heading("Raw Data (GFF)"))
        outer.addWidget(w.body(
            "The save's decoded structure. Edits made here skip the friendly "
            "editors and are marked “raw” in the ledger — a field's type is always "
            "preserved, so a raw edit can break the game's rules but not the file.",
            t.TEXT_2, 12.5,
        ))

        picker = QHBoxLayout()
        picker.setSpacing(8)
        picker.addWidget(w.cap_label("Resource"))
        self._target_box = QComboBox()
        self._target_box.setStyleSheet(_COMBO_QSS)
        self._target_box.setMinimumWidth(260)
        for target in self._targets():
            self._target_box.addItem(target)
        self._target_box.currentTextChanged.connect(self._choose_target)
        picker.addWidget(self._target_box)
        self._resource_count = w.body("", t.TEXT_3, 11.5)
        picker.addWidget(self._resource_count)
        picker.addStretch(1)
        outer.addLayout(picker)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter top-level fields by name…")
        self._filter.setStyleSheet(
            f"QLineEdit{{background:#1e1713;border:1px solid {t.hairline(0.18)};"
            f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};"
            f"font-size:12px;padding:6px 9px;}}"
        )
        self._filter.textChanged.connect(self._apply_filter)
        outer.addWidget(self._filter)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Field", "Type", "Value"])
        self._tree.setStyleSheet(_TREE_QSS + w.SCROLLBAR_QSS)
        w.apply_tree_palette(self._tree)
        self._tree.itemExpanded.connect(self._on_expand)
        self._tree.currentItemChanged.connect(self._on_select)
        self._tree.setColumnWidth(0, 340)
        self._tree.setColumnWidth(1, 110)
        outer.addWidget(self._tree, 1)

        row = QHBoxLayout()
        self._path_label = w.mono("", t.TEXT_3, 11)
        row.addWidget(self._path_label, 1)
        self._edit_button = w.ghost_button("Edit value…")
        self._edit_button.setEnabled(False)
        self._edit_button.clicked.connect(self._edit_selected)
        row.addWidget(self._edit_button)
        outer.addLayout(row)

        self.refresh()

    def _targets(self) -> list[str]:
        session = self._window._session
        if session is None:
            try:
                session = self._window.session()
            except Exception:
                from vaultkeeper.game.save_editor import SaveEditor

                return list(SaveEditor.RAW_TARGETS)
        try:
            return session.raw_targets()
        except Exception:
            return []

    # -- rebuilding -------------------------------------------------------- #
    def refresh(self) -> None:
        targets = self._targets()
        if [self._target_box.itemText(i) for i in range(self._target_box.count())] != targets:
            self._target_box.blockSignals(True)
            self._target_box.clear()
            self._target_box.addItems(targets)
            self._target_box.blockSignals(False)
        if self._target not in targets and targets:
            self._target = targets[0]
        self._target_box.blockSignals(True)
        self._target_box.setCurrentText(self._target)
        self._target_box.blockSignals(False)
        self._resource_count.setText(f"{len(targets)} resource(s) in this save")
        self._tree.clear()
        self._path_label.setText("")
        self._edit_button.setEnabled(False)

        tree = self._tree_for(self._target)
        if tree is None:
            self._tree.addTopLevelItem(
                QTreeWidgetItem([f"({self._target} is not part of this save)", "", ""])
            )
            return
        for label, entry in tree.root.fields.items():
            self._tree.addTopLevelItem(self._node(label, entry, ((label, None),)))

    def _tree_for(self, target: str):
        session = self._window._session
        if session is None:
            try:
                session = self._window.session()
            except Exception:
                return None
        try:
            return session.raw_tree(target)
        except Exception:
            return None

    def _node(self, label: str, entry, path: tuple) -> QTreeWidgetItem:
        value = entry.value
        if isinstance(value, GffList):
            node = QTreeWidgetItem([label, "list", f"{len(value.structs)} struct(s)"])
            node.setData(0, _ROLE, ("list", path, value))
            if value.structs:
                node.addChild(QTreeWidgetItem([_LAZY, "", ""]))
        elif isinstance(value, GffStruct):
            node = QTreeWidgetItem([label, "struct", f"{len(value.fields)} field(s)"])
            node.setData(0, _ROLE, ("struct", path, value))
            if value.fields:
                node.addChild(QTreeWidgetItem([_LAZY, "", ""]))
        else:
            node = QTreeWidgetItem([label, entry.type.name.lower(), _short(value)])
            node.setData(0, _ROLE, ("scalar", path, entry))
        return node

    def _on_expand(self, node: QTreeWidgetItem) -> None:
        if node.childCount() != 1 or node.child(0).text(0) != _LAZY:
            return  # already populated
        role = node.data(0, _ROLE)
        node.takeChildren()
        if role is None:
            return
        kind, path, value = role
        if kind == "list":
            for index, child in enumerate(value.structs):
                label = f"[{index}]"
                item = QTreeWidgetItem([label, "struct", f"{len(child.fields)} field(s)"])
                item.setData(0, _ROLE, ("struct", path[:-1] + ((path[-1][0], index),), child))
                if child.fields:
                    item.addChild(QTreeWidgetItem([_LAZY, "", ""]))
                node.addChild(item)
        elif kind == "struct":
            for label, entry in value.fields.items():
                node.addChild(self._node(label, entry, path + ((label, None),)))

    # -- selection + editing ----------------------------------------------- #
    def _on_select(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        role = current.data(0, _ROLE) if current is not None else None
        if role is None:
            self._path_label.setText("")
            self._edit_button.setEnabled(False)
            return
        kind, path, _value = role
        self._path_label.setText(_render_path(path))
        self._edit_button.setEnabled(kind == "scalar" and self._window.editing)

    def _edit_selected(self) -> None:
        from vaultkeeper.ui.dialogs.property_edit_dialog import PropertyEditDialog

        current = self._tree.currentItem()
        role = current.data(0, _ROLE) if current is not None else None
        if role is None or role[0] != "scalar":
            return
        _kind, path, entry = role
        label = _render_path(path)

        if isinstance(entry.value, str):
            text, ok = _get_text(self, label, entry.value)
            if not ok:
                return
            new_value = text
        else:
            dialog = PropertyEditDialog(
                label, f"{path[-1][0]}:", int(entry.value),
                minimum=-2_147_483_648, maximum=2_147_483_647, parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            new_value = dialog.value()

        try:
            self._window.session().set_raw_field(
                self._target, path, new_value, where=f"{self._target}: {label}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Raw edit failed", str(exc))
            return
        self._window.notify_changed()

    def _choose_target(self, target: str) -> None:
        self._target = target
        self.refresh()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self._tree.topLevelItemCount()):
            node = self._tree.topLevelItem(index)
            node.setHidden(needle not in node.text(0).lower())


def _render_path(path: tuple) -> str:
    parts = []
    for label, index in path:
        parts.append(label if index is None else f"{label}[{index}]")
    return "/".join(parts)


def _short(value, limit: int = 80) -> str:
    substrings = getattr(value, "substrings", None)
    if substrings is not None:
        text = getattr(value, "text", None)
        value = text() if callable(text) else str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _get_text(parent, title: str, current: str):
    from PySide6.QtWidgets import QInputDialog

    return QInputDialog.getText(parent, "Edit value", title, text=current)
