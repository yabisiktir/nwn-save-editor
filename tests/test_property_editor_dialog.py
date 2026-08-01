"""Editing an existing item property from its own iprp_* tables."""

from __future__ import annotations


class _FakeTables:
    available = True

    def subtype_options(self, pn):
        return {0: "Str", 1: "Dex", 2: "Con"} if pn == 0 else None

    def cost_options(self, ct):
        return {1: "+1", 2: "+2", 5: "+5", 7: "+7"}

    def param1_options(self, pn):
        return None

    def property_name_label(self, pn):
        return "Ability Bonus"


class _FakeLook:
    def appearance_options(self):
        return {6: "Human", 1: "Elf", 2: "Gnome"}

    def appearance_name(self, i):
        return self.appearance_options().get(i, f"#{i}")

    def portrait_resrefs(self):
        return ["po_hu_m_11_", "po_el_f_02_", "po_dw_m_03_"]


def test_property_editor_dialog_builds_edits(qtbot):
    from nwnfile.formats.bic_reader import ItemProperty
    from nwnsaveeditor.ui.dialogs.property_editor_dialog import PropertyEditorDialog

    prop = ItemProperty(
        property_name=0, subtype=0, cost_table=1, cost_value=2, param1=255, param1_value=0
    )
    dialog = PropertyEditorDialog(prop, _FakeTables(), 255)
    qtbot.addWidget(dialog)
    dialog._subtype_combo.setCurrentIndex(dialog._subtype_combo.findData(2))  # Con
    dialog._cost_combo.setCurrentIndex(dialog._cost_combo.findData(5))  # +5
    result = dialog.edits()
    assert result == {"subtype": 2, "cost_value": 5}


