"""The Raw Data (GFF) screen — the escape hatch.

Browse the decoded struct/field tree of a save's resources directly, edit scalar
leaves, and grow or shrink a list of structs. This bypasses every friendly
editor, so its edits are marked ``raw`` in the ledger and it refuses anything
that would change a field's type — a raw edit should be able to break the
*rules*, not the *file*.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
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

from nwnfile.formats.gff import GffList, GffStruct
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

_ROLE = Qt.ItemDataRole.UserRole
#: Nodes are built lazily; a save's tree is far too large to expand eagerly.
_LAZY = "…"

_REFERENCE_SHOW = "Property reference ›"
_REFERENCE_HIDE = "‹ Hide reference"


def _combo_qss() -> str:
    """The resource picker's chrome, rebuilt per call so it follows the theme."""
    return (
        f"QComboBox{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.22)};"
        f"border-radius:5px;color:{t.TEXT};font-family:{t.MONO_FAMILY};"
        f"font-size:12px;padding:5px 8px;}}"
        f"QComboBox QAbstractItemView{{background:{t.INPUT_BG};color:{t.TEXT};"
        f"selection-background-color:{t.gold_tint(0.5)};selection-color:{t.GOLD};}}"
    )


def _tree_qss() -> str:
    """The GFF tree's chrome, rebuilt per call so it follows the theme."""
    return f"""
QTreeWidget {{
    background:{t.INSET}; border:1px solid {t.hairline(0.06)};
    border-radius:{t.RADIUS_PANEL}px; color:{t.TEXT};
    font-family:{t.MONO_FAMILY}; font-size:12px; outline:none;
}}
QTreeWidget::item {{ padding:3px 4px; border:none; }}
QTreeWidget::item:selected {{ background:{t.gold_tint(0.22)}; color:{t.GOLD}; }}
QTreeWidget::item:hover {{ background:{t.hairline(0.05)}; }}
/* ::branch is deliberately NOT styled: styling it makes Qt stop drawing the
   expand/collapse arrow, so a collapsed node looks like a leaf. The blue
   selection stripe it would otherwise leave is handled by apply_tree_palette. */
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
        self._target_box.setStyleSheet(_combo_qss())
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
            f"QLineEdit{{background:{t.INPUT_BG};border:1px solid {t.hairline(0.18)};"
            f"border-radius:5px;color:{t.TEXT};font-family:{t.UI_FAMILY};"
            f"font-size:12px;padding:6px 9px;}}"
        )
        self._filter.textChanged.connect(self._apply_filter)
        outer.addWidget(self._filter)

        split = QHBoxLayout()
        split.setSpacing(14)
        outer.addLayout(split, 1)

        self._tree = QTreeWidget()
        self._tree.setColumnCount(3)
        self._tree.setHeaderLabels(["Field", "Type", "Value"])
        self._tree.setStyleSheet(_tree_qss() + w.scrollbar_qss())
        w.apply_tree_palette(self._tree)
        self._tree.itemExpanded.connect(self._on_expand)
        self._tree.currentItemChanged.connect(self._on_select)
        # A GFF path is a long way down; making people find it again after every
        # edit is what made the tree tiring to use.
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        self._tree.setColumnWidth(0, 340)
        self._tree.setColumnWidth(1, 110)
        split.addWidget(self._tree, 1)

        # The property reference used to be its own sidebar section, so looking up
        # what CostValue 6 means cost you the tree you were reading. It sits here
        # instead, folded away until asked for.
        from vaultkeeper.ui.save_editor.screens.property_reference import (
            PropertyReferenceScreen,
        )

        self._reference = PropertyReferenceScreen(window, self)
        self._reference.setFixedWidth(620)
        self._reference.setVisible(False)
        split.addWidget(self._reference)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._path_label = w.mono("", t.TEXT_3, 11)
        row.addWidget(self._path_label, 1)
        self._reference_button = w.ghost_button(_REFERENCE_SHOW)
        self._reference_button.setToolTip(
            "What each item property means, its valid values, and which of your "
            "items carry it — beside the tree, not instead of it"
        )
        self._reference_button.clicked.connect(self._toggle_reference)
        row.addWidget(self._reference_button)
        self._buttons: dict[str, object] = {}
        for key, text, handler in (
            ("blank", "Add blank entry", self._add_blank),
            ("duplicate", "Duplicate entry", self._duplicate),
            ("remove", "Remove entry…", self._remove_selected),
            ("edit", "Edit value…", self._edit_selected),
        ):
            button = w.ghost_button(text)
            button.setEnabled(False)
            button.clicked.connect(handler)
            row.addWidget(button)
            self._buttons[key] = button
        self._edit_button = self._buttons["edit"]  # the value editor, kept by name
        outer.addLayout(row)

        #: what the last structural edit did — a new entry is copied or seeded, and
        #: which one it was is the difference between valid and useless.
        self._note = w.body("", t.TEXT_3, 11.5)
        outer.addWidget(self._note)

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
        was_open, was_current, was_scrolled = self._tree_state()
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
        self._note.setText("")
        for button in self._buttons.values():
            button.setEnabled(False)

        tree = self._tree_for(self._target)
        if tree is None:
            self._tree.addTopLevelItem(
                QTreeWidgetItem([f"({self._target} is not part of this save)", "", ""])
            )
            return
        for label, entry in tree.root.fields.items():
            self._tree.addTopLevelItem(self._node(label, entry, ((label, None),)))
        self._restore_tree_state(was_open, was_current, was_scrolled)
        if not self._reference.isHidden():
            self._reference.refresh()

    # -- keeping your place ------------------------------------------------- #
    def _tree_state(self) -> tuple[set, tuple | None, int]:
        """Which nodes are open, which is selected, and where the view sits.

        ``refresh`` rebuilds the whole tree, so without this every edit collapsed
        it and threw you back to the top — with the field you just changed several
        expansions away.
        """
        opened: set = set()

        def walk(node: QTreeWidgetItem) -> None:
            role = node.data(0, _ROLE)
            if node.isExpanded() and role is not None:
                opened.add(role[1])
            for index in range(node.childCount()):
                walk(node.child(index))

        for index in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(index))
        current = self._tree.currentItem()
        role = current.data(0, _ROLE) if current is not None else None
        selected = role[1] if role is not None else None
        return opened, selected, self._tree.verticalScrollBar().value()

    def _restore_tree_state(self, opened: set, current: tuple | None, scrolled: int) -> None:
        if not opened and current is None:
            return
        found: list[QTreeWidgetItem] = []

        def walk(node: QTreeWidgetItem) -> None:
            role = node.data(0, _ROLE)
            path = role[1] if role is not None else None
            if path is not None and path == current:
                found.append(node)
            if path in opened:
                # Children are built lazily on expand, so this has to go top-down.
                node.setExpanded(True)
            for index in range(node.childCount()):
                walk(node.child(index))

        for index in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(index))
        if found:
            self._tree.setCurrentItem(found[0])
        # After the layout settles, or the bar has not yet grown to this extent.
        QTimer.singleShot(0, lambda: self._tree.verticalScrollBar().setValue(scrolled))

    def _on_double_click(self, node: QTreeWidgetItem, _column: int = 0) -> None:
        """Edit a scalar in place; a container just toggles, as Qt already does."""
        role = node.data(0, _ROLE)
        if role is not None and role[0] == "scalar":
            self._tree.setCurrentItem(node)
            self._edit_selected()

    def _toggle_reference(self) -> None:
        """Show or hide the property reference beside the tree.

        ``isHidden`` rather than ``isVisible``: the latter is false whenever an
        ancestor is hidden, which would flip the panel's own state on a screen
        the stack is not currently showing.
        """
        showing = self._reference.isHidden()
        self._reference.setVisible(showing)
        self._reference_button.setText(_REFERENCE_HIDE if showing else _REFERENCE_SHOW)
        if showing:
            self._reference.refresh()

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
            for button in self._buttons.values():
                button.setEnabled(False)
            return
        kind, path, _value = role
        self._path_label.setText(_render_path(path))
        editing = self._window.editing
        context = self._list_context(current)
        entry = context is not None and context[1] is not None
        self._buttons["edit"].setEnabled(kind == "scalar" and editing)
        self._buttons["blank"].setEnabled(editing and context is not None)
        self._buttons["duplicate"].setEnabled(editing and context is not None and context[2] > 0)
        self._buttons["remove"].setEnabled(editing and entry)

    @staticmethod
    def _list_context(item: QTreeWidgetItem | None) -> tuple[tuple, int | None, int] | None:
        """``(list path, selected entry index or None, entry count)``, or ``None``.

        A list node and one of its entries act on the same list; the entry only
        adds *which* one Duplicate and Remove mean.
        """
        role = item.data(0, _ROLE) if item is not None else None
        if role is None:
            return None
        kind, path, value = role
        if kind == "list":
            return path, None, len(value.structs)
        if kind == "struct" and path and path[-1][1] is not None:
            # The entry's parent node carries the list itself, so the count and the
            # list's own path come from there rather than being rebuilt by hand.
            parent = item.parent()
            parent_role = parent.data(0, _ROLE) if parent is not None else None
            if parent_role is not None and parent_role[0] == "list":
                return parent_role[1], path[-1][1], len(parent_role[2].structs)
        return None

    def _add_blank(self) -> None:
        self._add(None)

    def _duplicate(self) -> None:
        context = self._list_context(self._tree.currentItem())
        if context is None:
            return
        _path, index, count = context
        # On the list itself, "duplicate" means its last entry — the newest sibling.
        self._add(index if index is not None else count - 1)

    def _add(self, source_index: int | None) -> None:
        context = self._list_context(self._tree.currentItem())
        if context is None:
            return
        path, _index, _count = context
        label = _render_path(path)
        try:
            index = self._window.session().add_raw_struct(
                self._target, path, source_index=source_index,
                where=f"{self._target}: {label}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Raw edit failed", str(exc))
            return
        self._window.notify_changed()  # rebuilds the tree: the indices just moved
        self._reveal(path[:-1] + ((path[-1][0], index),))
        self._note.setText(
            f"Added {label}[{index}] as a copy of [{source_index}]."
            if source_index is not None else
            f"Added {label}[{index}], seeded with its siblings' fields at zero — "
            f"fill them in, or duplicate an entry instead."
        )

    def _remove_selected(self) -> None:
        context = self._list_context(self._tree.currentItem())
        if context is None or context[1] is None:
            return
        path, index, count = context
        label = _render_path(path)
        confirm = QMessageBox.question(
            self, "Remove entry",
            f"Remove entry [{index}] of {count} from {label}?\n\n"
            f"Every entry after it moves up one place. Nothing checks that the "
            f"game can still read the result.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            self._window.session().remove_raw_struct(
                self._target, path, index, where=f"{self._target}: {label}"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Raw edit failed", str(exc))
            return
        self._window.notify_changed()
        self._reveal(path)
        self._note.setText(f"Removed {label}[{index}] — the entries after it moved up one.")

    def _reveal(self, path: tuple) -> None:
        """Expand down to ``path`` and select it, after a rebuild.

        A structural edit renumbers entries, so the tree is rebuilt from scratch
        rather than patched; without this the user would be dropped back at the
        root every time they add a row.
        """
        node = None
        siblings = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        for label, index in path:
            node = _named(siblings, label)
            if node is None:
                return
            self._tree.expandItem(node)
            if index is not None:
                node = _named(_children(node), f"[{index}]")
                if node is None:
                    return
                self._tree.expandItem(node)
            siblings = _children(node)
        if node is not None:
            self._tree.setCurrentItem(node)
            # Centred, not merely visible: a new entry lands at the end of a long
            # list, and the default scroll leaves it clipped against the bottom.
            self._tree.scrollToItem(node, QTreeWidget.ScrollHint.PositionAtCenter)

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
            dialog = w.style_dialog(PropertyEditDialog(
                label, f"{path[-1][0]}:", int(entry.value),
                minimum=-2_147_483_648, maximum=2_147_483_647,
                title="Edit Value", parent=self,
            ))
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


def _children(node: QTreeWidgetItem) -> list[QTreeWidgetItem]:
    return [node.child(i) for i in range(node.childCount())]


def _named(items: list[QTreeWidgetItem], label: str) -> QTreeWidgetItem | None:
    return next((item for item in items if item.text(0) == label), None)


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
    return w.prompt_text(parent, "Edit Value", title, current)
