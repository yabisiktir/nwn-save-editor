"""Finding player items that lost properties versus their blueprint
(nwnsaveeditor.stripped_items). Synthetic .uti blueprints in built haks — no real
game files needed."""
from __future__ import annotations

from nwnfile.formats.erf_writer import build_hak
from nwnfile.formats.gff import Gff, GffField, GffList, GffStruct, GffType, LocString, write_gff
from nwnsaveeditor import stripped_items as si

_UTI = 2025
P = si.PropFields
LIGHT = P(44, 0, 18, 4, 9, 1)
LORE = P(52, 7, 25, 10, 255, 0)
FEAT = P(12, 5, 0, 0, 255, 0)
CLERIC_ONLY = P(63, 2, 0, 0, 255, 0)


def _loc(text):
    return GffField(GffType.CEXOLOCSTRING, LocString(strref=-1, substrings=[(0, text)]))


def _uti(tag, props, *, name="Symbol", desc="", base=15):
    structs = [GffStruct(struct_type=i, fields={
        f: GffField(GffType.WORD if f in ("PropertyName", "Subtype", "CostValue")
                    else GffType.BYTE, v)
        for f, v in zip(si._KEY_FIELDS, (p.property_name, p.subtype, p.cost_table,
                                         p.cost_value, p.param1, p.param1_value),
                        strict=True)}) for i, p in enumerate(props)]
    root = GffStruct(struct_type=0xFFFFFFFF, fields={
        "Tag": GffField(GffType.CEXOSTRING, tag),
        "BaseItem": GffField(GffType.INT, base),
        "LocalizedName": _loc(name),
        "DescIdentified": _loc(desc),
        "PropertiesList": GffField(GffType.LIST, GffList(structs)),
    })
    return write_gff(Gff("UTI ", "V3.2", root))


def _mod(tmp_path, name, entries):
    path = tmp_path / f"{name}.mod"
    path.write_bytes(build_hak(entries))
    return path


def _facts(props, *, tag="thoth", resref="symbol", desc="", name="Symbol", base=15):
    return si.ItemFacts(path=(("ItemList", 0),), name=name, tag=tag, resref=resref,
                        base_item=base, description=desc, props=list(props))


def test_reads_blueprint_properties_from_installed_modules(tmp_path):
    mod = _mod(tmp_path, "sof3", [("symbol", _UTI, _uti("thoth", [FEAT, LIGHT]))])
    bps = si.find_blueprints({"symbol", "absent"}, [mod])
    assert set(bps) == {"symbol"}
    assert bps["symbol"][0].props == [FEAT, LIGHT]
    assert bps["symbol"][0].origin == "sof3.mod"


def test_a_stripped_item_lists_what_its_blueprint_has_and_it_lacks(tmp_path):
    mod = _mod(tmp_path, "sof3", [("symbol", _UTI, _uti("thoth", [FEAT, LIGHT, LORE]))])
    found = si.find_stripped([_facts([LIGHT])], si.find_blueprints({"symbol"}, [mod]))
    assert len(found) == 1
    assert found[0].missing == [FEAT, LORE]  # blueprint order, Light kept


def test_intact_changed_or_mismatched_items_are_not_flagged(tmp_path):
    mod = _mod(tmp_path, "m", [("symbol", _UTI, _uti("thoth", [FEAT, LIGHT]))])
    bps = si.find_blueprints({"symbol"}, [mod])
    assert not si.find_stripped([_facts([FEAT, LIGHT])], bps)          # intact
    assert not si.find_stripped([_facts([LIGHT, LORE])], bps)          # upgraded: has extra
    assert not si.find_stripped([_facts([LIGHT], tag="other")], bps)   # different tag
    assert not si.find_stripped([_facts([], base=73)], bps)            # creature hide


def test_an_item_missing_only_restrictions_is_not_flagged(tmp_path):
    # a player unlocking a wand looks exactly like this — not lost power
    mod = _mod(tmp_path, "m", [("symbol", _UTI, _uti("thoth", [FEAT, CLERIC_ONLY]))])
    bps = si.find_blueprints({"symbol"}, [mod])
    assert not si.find_stripped([_facts([FEAT])], bps)
    found = si.find_stripped([_facts([])], bps)
    assert [p.limiting for p in found[0].missing] == [False, True]
    assert found[0].lost_powers == [FEAT]


def test_the_blueprint_with_the_matching_description_wins(tmp_path):
    # SoF2 and SoF3 both ship "zep_holysymbo001"; the item's own text picks SoF3
    sof2 = _mod(tmp_path, "sof2", [("symbol", _UTI, _uti("thoth", [LIGHT, FEAT], desc="old"))])
    sof3 = _mod(tmp_path, "sof3", [("symbol", _UTI, _uti(
        "thoth", [LIGHT, FEAT, LORE, P(15, 326, 3, 13, 255, 0)], desc="new"))])
    bps = si.find_blueprints({"symbol"}, [sof2, sof3])
    found = si.find_stripped([_facts([LIGHT], desc="new")], bps)
    assert found[0].blueprint.origin == "sof3.mod"
    assert [a.origin for a in found[0].alternatives] == ["sof2.mod"]
    # with nothing to tell them apart, the smaller restore is the conservative pick
    found = si.find_stripped([_facts([LIGHT], desc="")], bps)
    assert found[0].blueprint.origin == "sof2.mod"


def test_dialog_ticks_powers_and_leaves_restrictions_off(qtbot):
    from PySide6.QtWidgets import QDialogButtonBox

    from nwnsaveeditor.ui.dialogs.restore_items_dialog import RestoreItemsDialog

    bp = si.Blueprint(origin="sof3.mod", resref="symbol", tag="thoth", name="Symbol",
                      description="", props=[FEAT, LIGHT, CLERIC_ONLY])
    entry = si.StrippedItem(item=_facts([LIGHT]), blueprint=bp,
                            missing=[FEAT, CLERIC_ONLY])
    dlg = RestoreItemsDialog([entry])
    qtbot.addWidget(dlg)
    dlg.show()
    assert [(e is entry, props) for e, props in dlg.selected()] == [(True, [FEAT])]
    for _e, _p, box in dlg._checks:
        box.setChecked(False)
    assert dlg.selected() == []
    assert not dlg._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
