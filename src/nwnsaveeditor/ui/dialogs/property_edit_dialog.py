"""A tiny dialog to edit one magical-property value (a magnitude or uses/day).

Kept deliberately generic: it shows the property's description and a single spin
box, and :meth:`value` returns the number. The caller decides whether that number
is a ``+N`` magnitude or a Cast Spell's uses/day and stages the right edit.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class PropertyEditDialog(QDialog):
    """Edit a single integer value for a property (magnitude or uses/day)."""

    def __init__(
        self,
        description: str,
        caption: str,
        current: int,
        *,
        minimum: int = 0,
        maximum: int = 255,
        special_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Property")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>{description}</b>"))
        form = QFormLayout()
        layout.addLayout(form)
        self._spin = QSpinBox()
        self._spin.setRange(minimum, maximum)
        if special_text:
            self._spin.setSpecialValueText(special_text)  # shown at the minimum value
        self._spin.setValue(max(minimum, min(maximum, current)))
        form.addRow(caption, self._spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> int:
        return self._spin.value()
