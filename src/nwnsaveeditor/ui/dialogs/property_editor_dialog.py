"""Edit an existing item property's subtype / value / param from valid options.

Every editable field is a dropdown (or a searchable picker, for the huge feat/spell
subtype lists) populated from the property's ``iprp_*`` tables via
:class:`vaultkeeper.game.item_property_tables.ItemPropertyTables`, so you can only
choose values the game recognises — no free-form number that could corrupt the item.
The property *type* itself is fixed (change it by removing + adding a property).
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

from vaultkeeper.core.formats.bic_reader import ItemProperty
from vaultkeeper.game.item_property_tables import ItemPropertyTables

_PICKER_THRESHOLD = 200  # above this many subtype options, use a searchable picker
_USES_PROPERTIES = {15, 82}  # Cast Spell / On Hit Cast Spell -> uses/day is meaningful


class PropertyEditorDialog(QDialog):
    """Edit a property's subtype, cost value, param and (for cast spells) uses/day."""

    def __init__(
        self, prop: ItemProperty, tables: ItemPropertyTables, uses_per_day: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Property")
        self._prop = prop
        self._subtypes = tables.subtype_options(prop.property_name)
        self._subtype_value = prop.subtype
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        type_label = (
            tables.property_name_label(prop.property_name) or f"Property {prop.property_name}"
        )
        form.addRow("Property:", QLabel(f"<b>{type_label}</b>"))

        self._subtype_combo: QComboBox | None = None
        self._subtype_btn: QPushButton | None = None
        if self._subtypes:
            if len(self._subtypes) <= _PICKER_THRESHOLD:
                self._subtype_combo = self._combo(self._subtypes, prop.subtype, by_name=True)
                form.addRow("Subtype:", self._subtype_combo)
            else:
                self._subtype_btn = QPushButton(self._subtype_button_text())
                self._subtype_btn.clicked.connect(self._pick_subtype)
                form.addRow("Subtype:", self._subtype_btn)

        self._cost_combo: QComboBox | None = None
        costs = tables.cost_options(prop.cost_table)
        if len(costs) > 1:
            self._cost_combo = self._combo(costs, prop.cost_value, by_name=False)
            form.addRow("Value:", self._cost_combo)

        self._param_combo: QComboBox | None = None
        params = tables.param1_options(prop.property_name)
        if params:
            self._param_combo = self._combo(params, prop.param1, by_name=False)
            form.addRow("Param:", self._param_combo)

        self._uses: QSpinBox | None = None
        if prop.property_name in _USES_PROPERTIES:
            self._uses = QSpinBox()
            self._uses.setRange(0, 255)
            self._uses.setValue(uses_per_day)
            form.addRow("Uses/day (255 = unlimited):", self._uses)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _combo(options: dict[int, str], current: int, *, by_name: bool) -> QComboBox:
        combo = QComboBox()
        key = (lambda p: p[1].lower()) if by_name else (lambda p: p[0])
        for row_id, name in sorted(options.items(), key=key):
            combo.addItem(name, row_id)
        index = combo.findData(current)
        if index < 0:  # current value not in the table -> keep it as an explicit choice
            combo.insertItem(0, f"(current: {current})", current)
            index = 0
        combo.setCurrentIndex(index)
        return combo

    def _subtype_button_text(self) -> str:
        name = self._subtypes.get(self._subtype_value, f"(id {self._subtype_value})")
        return f"{name}   (change…)"

    def _pick_subtype(self) -> None:
        from vaultkeeper.ui.dialogs.id_picker_dialog import IdPickerDialog

        dialog = IdPickerDialog(
            "Choose Subtype", list(self._subtypes.items()), parent=self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_id() is not None:
            self._subtype_value = dialog.selected_id()
            self._subtype_btn.setText(self._subtype_button_text())

    def edits(self) -> dict[str, int]:
        """Chosen edits as kwargs for :meth:`SaveEditor.set_property`.

        Deliberately not called ``result()``: that is ``QDialog``'s own method for
        the accepted/rejected code, and overriding it to return a dict shadowed
        what Qt's accept/reject/exec machinery reads — pressing Cancel handed a
        dict to code expecting an int and took the whole editor down.
        """
        edits: dict[str, int] = {}
        if self._subtype_combo is not None:
            edits["subtype"] = self._subtype_combo.currentData()
        elif self._subtype_btn is not None:
            edits["subtype"] = self._subtype_value
        if self._cost_combo is not None:
            edits["cost_value"] = self._cost_combo.currentData()
        if self._param_combo is not None:
            edits["param1"] = self._param_combo.currentData()
        if self._uses is not None:
            edits["uses_per_day"] = self._uses.value()
        return edits
