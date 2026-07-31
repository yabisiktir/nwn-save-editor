"""Add a magical property to an item — pick a type, a subtype and a magnitude.

Driven by the game's own ``iprp_*`` tables when they can be read: every property
type the game defines is offered, and its subtype / value / param choices come
from that property's tables, so anything you can build is something the engine
recognises. This is the same source the property *editor* uses, so adding
"Bonus Feat: Whirlwind Attack" now offers every feat rather than a handful.

Without a readable game folder there are no tables, so it falls back to the
curated set in :func:`vaultkeeper.game.item_properties.addable_properties` —
properties whose ``CostValue`` is the literal magnitude, which can be built from
a plain number alone.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from vaultkeeper.game.item_properties import PropertyTemplate, addable_properties

_PICKER_THRESHOLD = 200  # above this many subtype options, use a searchable picker


class AddPropertyDialog(QDialog):
    """Build one item property from a type + optional subtype / value / param."""

    def __init__(self, parent: QWidget | None = None, tables=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Property")
        self._tables = tables if (tables is not None and tables.available) else None
        self._templates: list[PropertyTemplate] = (
            [] if self._tables else addable_properties()
        )
        self._subtype_value = 0

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._type = QComboBox()
        for label, data in self._type_options():
            self._type.addItem(label, data)
        form.addRow("Property:", self._type)

        self._subtype_label = QLabel("Subtype:")
        self._subtype = QComboBox()
        form.addRow(self._subtype_label, self._subtype)

        # Feat and spell subtype lists run to thousands of rows; a combo box that
        # long cannot be searched, which is what made them unusable.
        self._subtype_btn = QPushButton()
        self._subtype_btn.clicked.connect(self._pick_subtype)
        self._picker_label = QLabel("Subtype:")
        form.addRow(self._picker_label, self._subtype_btn)

        self._value_label = QLabel("Value:")
        self._value = QComboBox()
        form.addRow(self._value_label, self._value)

        self._magnitude_label = QLabel("Magnitude:")
        self._magnitude = QSpinBox()
        form.addRow(self._magnitude_label, self._magnitude)

        self._param_label = QLabel("Param:")
        self._param = QComboBox()
        form.addRow(self._param_label, self._param)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._type.currentIndexChanged.connect(self._on_type_changed)
        self._on_type_changed()

    # -- what to offer ------------------------------------------------------ #
    def _type_options(self) -> list[tuple[str, int]]:
        if self._tables is None:
            return [(tpl.label, i) for i, tpl in enumerate(self._templates)]
        named = [
            (self._tables.property_name_label(pid) or f"#{pid}", pid)
            for pid in self._tables.property_ids()
        ]
        return sorted(named, key=lambda pair: pair[0].lower())

    def _property_id(self) -> int:
        data = self._type.currentData()
        return data if self._tables is not None else self._templates[data].property_name

    def _subtype_options(self) -> dict[int, str]:
        if self._tables is None:
            return dict(self._templates[self._type.currentData()].subtypes)
        return self._tables.subtype_options(self._property_id()) or {}

    def _cost_table(self) -> int | None:
        if self._tables is None:
            return self._templates[self._type.currentData()].cost_table
        return self._tables.cost_table_for(self._property_id())

    # -- reacting ------------------------------------------------------------ #
    def _on_type_changed(self) -> None:
        subtypes = self._subtype_options()
        as_picker = bool(subtypes) and len(subtypes) > _PICKER_THRESHOLD
        as_combo = bool(subtypes) and not as_picker

        self._subtype_label.setVisible(as_combo)
        self._subtype.setVisible(as_combo)
        if as_combo:
            self._subtype.clear()
            for subtype_id, name in sorted(subtypes.items(), key=lambda p: p[1].lower()):
                self._subtype.addItem(name, subtype_id)

        self._picker_label.setVisible(as_picker)
        self._subtype_btn.setVisible(as_picker)
        if as_picker:
            self._subtype_value = min(subtypes)
            self._subtype_btn.setText(self._subtype_button_text(subtypes))

        if self._tables is None:
            self._show_template_magnitude()
        else:
            self._show_table_values()

    def _show_template_magnitude(self) -> None:
        self._value_label.setVisible(False)
        self._value.setVisible(False)
        self._param_label.setVisible(False)
        self._param.setVisible(False)
        template = self._templates[self._type.currentData()]
        has_magnitude = template.magnitude is not None
        self._magnitude_label.setVisible(has_magnitude)
        self._magnitude.setVisible(has_magnitude)
        if has_magnitude:
            low, high = template.magnitude
            self._magnitude.setRange(low, high)
            self._magnitude.setValue(low)

    def _show_table_values(self) -> None:
        self._magnitude_label.setVisible(False)
        self._magnitude.setVisible(False)
        values = self._tables.cost_options(self._cost_table()) or {}
        self._value_label.setVisible(bool(values))
        self._value.setVisible(bool(values))
        self._value.clear()
        for row, name in sorted(values.items()):
            self._value.addItem(str(name), row)

        params = self._tables.param1_options(self._property_id()) or {}
        self._param_label.setVisible(bool(params))
        self._param.setVisible(bool(params))
        self._param.clear()
        for row, name in sorted(params.items()):
            self._param.addItem(str(name), row)

    def _subtype_button_text(self, subtypes: dict[int, str]) -> str:
        return f"{subtypes.get(self._subtype_value, self._subtype_value)}   (change…)"

    def _pick_subtype(self) -> None:
        from vaultkeeper.ui.dialogs.id_picker_dialog import IdPickerDialog

        subtypes = self._subtype_options()
        dialog = IdPickerDialog("Choose Subtype", sorted(subtypes.items()), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_id() is not None:
            self._subtype_value = dialog.selected_id()
            self._subtype_btn.setText(self._subtype_button_text(subtypes))

    # -- the answer ---------------------------------------------------------- #
    def _chosen_subtype(self) -> tuple[int, str]:
        subtypes = self._subtype_options()
        if not subtypes:
            return 0, ""
        if len(subtypes) > _PICKER_THRESHOLD:
            return self._subtype_value, str(subtypes.get(self._subtype_value, ""))
        return self._subtype.currentData(), self._subtype.currentText()

    def result_property(self) -> dict:
        """The chosen property as kwargs for :meth:`SaveEditor.add_item_property`."""
        subtype, subtype_name = self._chosen_subtype()
        if self._tables is None:
            template = self._templates[self._type.currentData()]
            cost = self._magnitude.value() if template.magnitude is not None else 0
            label = template.label
            if subtype_name:
                label += f": {subtype_name}"
            if template.magnitude is not None:
                label += f" +{cost}"
            return {
                "property_name": template.property_name, "subtype": subtype,
                "cost_value": cost, "cost_table": template.cost_table, "label": label,
            }

        has_value = bool(self._tables.cost_options(self._cost_table()) or {})
        has_param = bool(self._tables.param1_options(self._property_id()) or {})
        label = self._type.currentText()
        if subtype_name:
            label += f": {subtype_name}"
        if has_value:
            label += f" {self._value.currentText()}"
        return {
            "property_name": self._property_id(), "subtype": subtype,
            "cost_value": (self._value.currentData() or 0) if has_value else 0,
            "cost_table": self._cost_table() or 0,
            "param1": self._param.currentData() if has_param else None,
            "label": label,
        }
