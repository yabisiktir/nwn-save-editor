"""Add a magical property to an item — pick a type, a subtype and a magnitude.

Offers only the curated, well-understood properties from
:func:`vaultkeeper.game.item_properties.addable_properties`, so the built property
is always valid. Subtype/magnitude inputs appear only for property types that use
them; flag properties (Haste, Keen …) need neither.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.item_properties import PropertyTemplate, addable_properties


class AddPropertyDialog(QDialog):
    """Build one item property from a type + optional subtype + optional magnitude."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Property")
        self._templates = addable_properties()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._type = QComboBox()
        for i, template in enumerate(self._templates):
            self._type.addItem(template.label, i)
        self._type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Property:", self._type)

        self._subtype_label = QLabel("Subtype:")
        self._subtype = QComboBox()
        form.addRow(self._subtype_label, self._subtype)

        self._magnitude_label = QLabel("Magnitude:")
        self._magnitude = QSpinBox()
        form.addRow(self._magnitude_label, self._magnitude)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._on_type_changed()

    def _template(self) -> PropertyTemplate:
        return self._templates[self._type.currentData()]

    def _on_type_changed(self) -> None:
        template = self._template()
        has_subtype = bool(template.subtypes)
        self._subtype_label.setVisible(has_subtype)
        self._subtype.setVisible(has_subtype)
        if has_subtype:
            self._subtype.clear()
            for subtype_id, name in sorted(template.subtypes.items(), key=lambda p: p[1]):
                self._subtype.addItem(name, subtype_id)
        has_magnitude = template.magnitude is not None
        self._magnitude_label.setVisible(has_magnitude)
        self._magnitude.setVisible(has_magnitude)
        if has_magnitude:
            low, high = template.magnitude
            self._magnitude.setRange(low, high)
            self._magnitude.setValue(low)

    def result_property(self) -> dict:
        """The chosen property as kwargs for :meth:`SaveEditor.add_item_property`."""
        template = self._template()
        subtype = self._subtype.currentData() if template.subtypes else 0
        cost = self._magnitude.value() if template.magnitude is not None else 0
        label = template.label
        if template.subtypes:
            label += f": {self._subtype.currentText()}"
        if template.magnitude is not None:
            label += f" +{cost}"
        return {
            "property_name": template.property_name,
            "subtype": subtype,
            "cost_value": cost,
            "cost_table": template.cost_table,
            "label": label,
        }
