"""The appearance wizard dialog (choice collection + defaults)."""
from __future__ import annotations

from nwnfile.icon_reconcile import CopyOp, ExtractPlan, FieldSet, ItemReport
from nwnsaveeditor.ui.dialogs.appearance_wizard_dialog import AppearanceWizardDialog


class FImg:
    has_alpha = True

    def __init__(self, size=8):
        self.width = self.height = size
        self._rgba = bytes((200, 50, 50, 255)) * (size * size)

    def to_rgba(self):
        return self._rgba


def _report(resref, *, match=False, extract=True):
    return ItemReport(
        resref=resref, slot="equip", appearance=None,
        original_image=FImg(), current_image=FImg(),
        broken=True,
        match_number=14 if match else None,
        match_image=FImg() if match else None,
        match_score=0.94 if match else None,
        match_fields=[FieldSet("ModelPart1", 14)] if match else [],
        extract=ExtractPlan(250, [CopyOp("iit_ring_130", 3, "iit_ring_250")],
                            [FieldSet("ModelPart1", 250)]) if extract else None,
    )


_P1 = (("Mod_PlayerList", 0), ("Equip_ItemList", 3))
_P2 = (("Mod_PlayerList", 0), ("Equip_ItemList", 4))


def test_defaults_to_extract_then_match_then_keep(qtbot):
    entries = [(_P1, _report("ring", match=True, extract=True)),
               (_P2, _report("robe", match=False, extract=True))]
    dlg = AppearanceWizardDialog(entries)
    qtbot.addWidget(dlg)
    decisions = dlg.decisions()
    assert [d.choice for d in decisions] == ["extract", "extract"]
    assert decisions[0].item_path == _P1


def test_selecting_match_is_reflected(qtbot):
    entries = [(_P1, _report("ring", match=True, extract=True))]
    dlg = AppearanceWizardDialog(entries)
    qtbot.addWidget(dlg)
    dlg._groups[0][2].button(1).setChecked(True)  # the "closest match" radio
    assert dlg.decisions()[0].choice == "match"


def test_keep_only_when_no_match_or_extract(qtbot):
    entries = [(_P1, _report("belt", match=False, extract=False))]
    dlg = AppearanceWizardDialog(entries)
    qtbot.addWidget(dlg)
    assert dlg.decisions()[0].choice == "keep"


def test_set_all_bulk_applies_where_available(qtbot):
    entries = [(_P1, _report("ring", match=True, extract=True)),
               (_P2, _report("robe", match=False, extract=True))]
    dlg = AppearanceWizardDialog(entries)
    qtbot.addWidget(dlg)
    dlg._set_all("keep")
    assert [d.choice for d in dlg.decisions()] == ["keep", "keep"]
    dlg._set_all("match")  # robe has no match option, so it stays put
    assert [d.choice for d in dlg.decisions()] == ["match", "keep"]


def test_toggling_full_body_requests_a_rescan(qtbot):
    dlg = AppearanceWizardDialog([(_P1, _report("ring", extract=True))], full_body=False)
    qtbot.addWidget(dlg)
    assert dlg.retoggle_full is None
    # flip the "All body types" checkbox
    from PySide6.QtWidgets import QCheckBox
    box = next(c for c in dlg.findChildren(QCheckBox))
    box.setChecked(True)
    assert dlg.retoggle_full is True
    assert dlg.result() == dlg.DialogCode.Rejected  # closed to re-scan
