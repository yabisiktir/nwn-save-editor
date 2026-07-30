"""The Backups & Diff screen.

Lists the saves an overwrite archived, restores one, and diffs a backup against
the save currently selected — resource by resource, then field by field.

Restoring copies the backup into a *new* save folder rather than moving it over
the original: recovering from a mistake should not be able to create a second one.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.backups import list_backups, restore
from vaultkeeper.game.save_diff import diff_saves
from vaultkeeper.ui.save_editor import tokens as t
from vaultkeeper.ui.save_editor import widgets as w

#: A diff of a whole save can run to thousands of fields; show a workable slice.
DIFF_LIMIT = 200


class BackupsScreen(QWidget):
    """The Backups & Diff section."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._selected = None  # the chosen Backup
        self._diff = None
        self.setStyleSheet(f"background:{t.APP_BG};")

        outer = QHBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(16)

        left = QWidget()
        left.setFixedWidth(320)
        left.setStyleSheet("background:transparent;")
        self._left = QVBoxLayout(left)
        self._left.setContentsMargins(0, 0, 0, 0)
        self._left.setSpacing(10)
        outer.addWidget(left)

        right = QWidget()
        right.setStyleSheet("background:transparent;")
        self._right = QVBoxLayout(right)
        self._right.setContentsMargins(0, 0, 0, 0)
        self._right.setSpacing(10)
        outer.addWidget(right, 1)

        self.refresh()

    # -- data --------------------------------------------------------------- #
    def _backup_dir(self):
        save = self._window.save
        if save is None:
            return None
        return save.folder.parent.parent / "vaultkeeper_backups"

    def backups(self) -> list:
        return list_backups(self._backup_dir())

    # -- rebuilding --------------------------------------------------------- #
    def refresh(self) -> None:
        _clear(self._left)
        _clear(self._right)
        backups = self.backups()

        self._left.addWidget(w.heading("Backups"))
        if not backups:
            self._left.addWidget(w.body(
                "No backups yet. Overwriting a save with the backup box ticked "
                "archives the previous version here.",
                t.TEXT_3, 12.5,
            ))
            self._left.addStretch(1)
            self._right.addStretch(1)
            return
        self._left.addWidget(w.body(str(self._backup_dir()), t.TEXT_3, 11))

        if self._selected is None or not any(
            b.folder == self._selected.folder for b in backups
        ):
            self._selected = backups[0]

        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        for backup in backups:
            column.addWidget(self._backup_row(backup))
        column.addStretch(1)
        self._left.addWidget(_scroll(holder), 1)

        actions = QHBoxLayout()
        restore_button = w.ghost_button("Restore…")
        restore_button.clicked.connect(self._restore_selected)
        actions.addWidget(restore_button)
        diff_button = w.gold_button("Diff against current save")
        diff_button.clicked.connect(self._run_diff)
        actions.addWidget(diff_button)
        self._left.addLayout(actions)

        self._build_diff_panel()

    def _backup_row(self, backup) -> QWidget:
        from PySide6.QtWidgets import QFrame

        row = QFrame()
        row.setObjectName("BackupRow")
        selected = self._selected is not None and backup.folder == self._selected.folder
        row.setStyleSheet(
            f"#BackupRow{{background:{t.gold_tint(0.15) if selected else t.INSET};"
            f"border:1px solid "
            f"{t.gold_border(0.5) if selected else t.hairline(0.06)};"
            f"border-radius:8px;}}"
        )
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        column = QVBoxLayout(row)
        column.setContentsMargins(12, 9, 12, 9)
        column.setSpacing(2)
        name = w.body(backup.original_name, t.TEXT, 12.5)
        name.setStyleSheet(name.styleSheet() + "font-weight:600;")
        column.addWidget(name)
        taken = backup.taken.strftime("%Y-%m-%d %H:%M:%S") if backup.taken else "unknown time"
        column.addWidget(w.body(f"{taken}  ·  {backup.size / (1 << 20):.0f} MB", t.TEXT_3, 11))
        row.mousePressEvent = _left_click(lambda b=backup: self._choose(b))
        return row

    def _build_diff_panel(self) -> None:
        self._right.addWidget(w.heading("Differences"))
        save = self._window.save
        if self._diff is None:
            self._right.addWidget(w.body(
                "Pick a backup and choose “Diff against current save” to compare "
                "them field by field.",
                t.TEXT_3, 12.5,
            ))
            self._right.addStretch(1)
            return

        if self._diff.is_empty:
            self._right.addWidget(w.body(
                f"This backup is identical to {save.name if save else 'the current save'}.",
                t.TEXT_2, 12.5,
            ))
            self._right.addStretch(1)
            return

        self._right.addWidget(w.body(
            f"{self._diff.total_fields} field(s) across "
            f"{len(self._diff.resources)} resource(s) differ.",
            t.TEXT_2, 12.5,
        ))
        holder = QWidget()
        holder.setStyleSheet("background:transparent;")
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 6, 0)
        column.setSpacing(10)
        for resource in self._diff.resources:
            column.addWidget(self._resource_block(resource))
        for name in self._diff.only_in_a:
            column.addWidget(w.body(f"Only in the backup: {name}", t.TEXT_3, 12))
        for name in self._diff.only_in_b:
            column.addWidget(w.body(f"Only in the current save: {name}", t.TEXT_3, 12))
        column.addStretch(1)
        self._right.addWidget(_scroll(holder), 1)

    def _resource_block(self, resource) -> QWidget:
        panel = w.Panel(padding=12)
        body = panel.body_layout()
        body.addWidget(w.cap_label(f"{resource.name}  ({resource.count})"))
        if resource.opaque:
            body.addWidget(w.body(
                "This resource differs but is not a GFF, so it cannot be compared "
                "field by field.",
                t.TEXT_3, 11.5,
            ))
            return panel
        for change in resource.fields[:60]:
            body.addWidget(self._field_row(change))
        if resource.count > 60:
            body.addWidget(w.body(f"… and {resource.count - 60} more", t.TEXT_3, 11))
        return panel

    def _field_row(self, change) -> QWidget:
        row = QWidget()
        row.setStyleSheet(f"background:transparent;border-bottom:1px solid {t.hairline(0.06)};")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 4, 0, 4)
        line.setSpacing(10)
        line.addWidget(w.mono(change.path, t.TEXT_2, 11), 1)
        line.addWidget(w.mono(change.text(change.before), t.TEXT_3, 11))
        line.addWidget(w.body("→", t.TEXT_3, 11))
        line.addWidget(w.mono(change.text(change.after), t.TEXT, 11))
        return row

    # -- actions ------------------------------------------------------------ #
    def _choose(self, backup) -> None:
        self._selected = backup
        self._diff = None
        self.refresh()

    def _run_diff(self) -> None:
        save = self._window.save
        if save is None or self._selected is None:
            return
        try:
            self._diff = diff_saves(self._selected.save, save, limit=DIFF_LIMIT)
        except Exception as exc:
            QMessageBox.critical(self, "Diff failed", str(exc))
            return
        self.refresh()

    def _restore_selected(self) -> None:
        save = self._window.save
        if save is None or self._selected is None:
            return
        saves_dir = save.folder.parent
        confirm = QMessageBox.question(
            self, "Restore backup",
            f"Copy “{self._selected.original_name}” back into your saves folder?\n\n"
            "It is restored as a new save — nothing currently in the folder is "
            "replaced, and the backup itself is kept.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            restored = restore(self._selected, saves_dir)
        except OSError as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        QMessageBox.information(
            self, "Restored", f"Restored as “{restored.name}”."
        )
        self._window.add_save(restored)


def _scroll(body: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setStyleSheet(w.scroll_area_qss())
    area.setWidget(body)
    return area


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            w.retire(widget)
        elif item.layout() is not None:
            _clear(item.layout())

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
