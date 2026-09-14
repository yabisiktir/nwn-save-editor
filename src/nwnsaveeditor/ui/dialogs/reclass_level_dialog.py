"""Pick which already-taken level to re-class, and how.

Re-classing changes the class recorded at *one* character level — both the class
totals (``ClassList``) and the per-level history (``LvlStatList``). This front-end
picks the level; the target class and its choices come next (an id picker, then
the level-up wizard). In Free rule mode it also offers the "break it" path — keep
the previous class's benefits while gaining the new class's level, an over-powered
build the game still loads.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QVBoxLayout,
    QWidget,
)


class ReclassLevelDialog(QDialog):
    """Choose the character level to re-class (and, in Free, whether to break it)."""

    def __init__(
        self,
        levels: Sequence[tuple[int, str]],  # (history index, "Level N — Class")
        *,
        allow_keep_previous: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        from nwnsaveeditor.ui.editor import tokens as t
        from nwnsaveeditor.ui.editor import widgets as w

        self.setWindowTitle("Change a level's class")
        self.resize(440, 200)
        self.setStyleSheet(w.dialog_qss())  # wear the editor's theme, not the OS palette
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        layout.addWidget(w.body(
            "Pick the level to re-class. Its class will be swapped everywhere the "
            "save records it — the class totals and the level-by-level history.",
            t.TEXT_2, 12.5,
        ))
        self._combo = QComboBox()
        for index, label in levels:
            self._combo.addItem(label, index)
        layout.addWidget(self._combo)

        self._keep_box: QCheckBox | None = None
        if allow_keep_previous:
            self._keep_box = QCheckBox("Keep the previous class's benefits (break it)")
            layout.addWidget(self._keep_box)
            note = w.body(
                "Free mode only. The level counts still move, but the old class's "
                "attack, saves, hit points and feats are not removed — so the sheet "
                "keeps the previous class's advantages and gains the new class's on "
                "top. This is a deliberately over-powered, non-legal build.",
                t.TEXT_3, 11.5,
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        layout.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_index(self) -> int | None:
        """The chosen history index, or ``None`` if the picker was empty."""
        data = self._combo.currentData(Qt.ItemDataRole.UserRole)
        return int(data) if data is not None else None

    def keep_previous(self) -> bool:
        """Whether the Free-mode "keep the previous class's benefits" box is ticked."""
        return self._keep_box is not None and self._keep_box.isChecked()
