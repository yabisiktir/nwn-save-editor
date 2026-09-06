"""Applying appearance decisions (nwnsaveeditor.appearance_fix)."""
from __future__ import annotations

import json

from nwnfile.icon_reconcile import CopyOp, ExtractPlan, FieldSet, ItemReport
from nwnsaveeditor.appearance_fix import Decision, apply_decisions


class FakeEditor:
    def __init__(self):
        self.calls = []

    def set_raw_field(self, target, path, value, *, where=""):
        self.calls.append((path, value))


class FakeSource:
    def __init__(self, raw):
        self.raw = raw

    def read(self, resref, res_type):
        return self.raw.get((resref, res_type))


def _report(resref, *, match=None, extract=None):
    return ItemReport(
        resref=resref, slot="equip", appearance=None, original_image=None,
        current_image=None, broken=True, match_fields=match or [], extract=extract)


_PATH = (("Mod_PlayerList", 0), ("Equip_ItemList", 3))


def test_keep_changes_nothing(tmp_path):
    ed = FakeEditor()
    dec = [Decision(_PATH, _report("x"), "keep")]
    summary = apply_decisions(ed, FakeSource({}), dec, tmp_path)
    assert ed.calls == [] and summary.edited == 0 and summary.files_written == 0


def test_match_stages_a_field_edit(tmp_path):
    ed = FakeEditor()
    rep = _report("ring", match=[FieldSet("ModelPart1", 14)])
    apply_decisions(ed, FakeSource({}), [Decision(_PATH, rep, "match")], tmp_path)
    assert (_PATH + (("ModelPart1", None),), 14) in ed.calls


def test_extract_writes_override_art_and_manifest_and_repoints(tmp_path):
    ed = FakeEditor()
    plan = ExtractPlan(
        slot=250,
        copies=[CopyOp("iit_ring_130", 3, "iit_ring_250")],
        fields=[FieldSet("ModelPart1", 250)],
    )
    rep = _report("ring", extract=plan)
    src = FakeSource({("iit_ring_130", 3): b"ARTBYTES"})
    summary = apply_decisions(ed, src, [Decision(_PATH, rep, "extract")], tmp_path)

    art = tmp_path / "iit_ring_250.tga"
    assert art.read_bytes() == b"ARTBYTES"
    assert (_PATH + (("ModelPart1", None),), 250) in ed.calls
    assert summary.files_written == 1
    manifest = json.loads((tmp_path / "vk_appearance_manifest.json").read_text())
    assert "iit_ring_250.tga" in manifest["files"]


def test_extract_syncs_the_armour_x_mirror(tmp_path):
    ed = FakeEditor()
    plan = ExtractPlan(
        slot=250,
        copies=[CopyOp("ipm_robe171", 3, "ipm_robe250")],
        fields=[FieldSet("ArmorPart_Robe", 250)],
    )
    src = FakeSource({("ipm_robe171", 3): b"ROBE"})
    apply_decisions(ed, src, [Decision(_PATH, _report("robe", extract=plan), "extract")],
                    tmp_path)
    values = {path[-1][0]: val for path, val in ed.calls}
    assert values["ArmorPart_Robe"] == 250
    assert values["xArmorPart_Robe"] == 250  # mirror kept in step


# -- collect_reports over a player struct ------------------------------------ #
def test_collect_reports_walks_worn_and_carried_and_skips_prc(tmp_path):
    from nwnfile.formats.gff import GffField, GffList, GffStruct, GffType
    from nwnsaveeditor.appearance_fix import collect_reports

    def item(base, resref):
        return GffStruct(struct_type=0, fields={
            "BaseItem": GffField(GffType.INT, base),
            "TemplateResRef": GffField(GffType.CRESREF, resref),
            "ModelPart1": GffField(GffType.BYTE, 1),
        })

    player = GffStruct(struct_type=0, fields={
        "Gender": GffField(GffType.BYTE, 0),
        "Equip_ItemList": GffField(GffType.LIST, GffList([
            item(52, "ring"), item(73, "base_prc_skin"),  # skin is skipped
        ])),
        "ItemList": GffField(GffType.LIST, GffList([item(21, "belt")])),
    })

    class Rec:
        def report(self, resref, slot, ap):
            from nwnfile.icon_reconcile import ItemReport
            broken = resref == "ring"  # only the ring is "broken"
            return ItemReport(resref, slot, ap, None, None, broken)

    reports = collect_reports(Rec(), player, female=False)
    assert [r.resref for _p, r in reports] == ["ring"]
    (path, _rep) = reports[0]
    assert path == (("Mod_PlayerList", 0), ("Equip_ItemList", 0))


def test_remove_override_deletes_only_manifest_files(tmp_path):
    from nwnsaveeditor.appearance_fix import override_manifest, remove_override
    ed = FakeEditor()
    plan = ExtractPlan(250, [CopyOp("a", 3, "iit_ring_250")],
                       [FieldSet("ModelPart1", 250)])
    apply_decisions(ed, FakeSource({("a", 3): b"X"}),
                    [Decision(_PATH, _report("r", extract=plan), "extract")], tmp_path)
    (tmp_path / "unrelated.tga").write_bytes(b"keep")  # not ours
    assert override_manifest(tmp_path) == ["iit_ring_250.tga"]
    removed = remove_override(tmp_path)
    assert removed == 1
    assert not (tmp_path / "iit_ring_250.tga").exists()
    assert (tmp_path / "unrelated.tga").exists()  # untouched
    assert override_manifest(tmp_path) == []


def test_collect_reports_descends_into_bags():
    from nwnfile.formats.gff import GffField, GffList, GffStruct, GffType
    from nwnsaveeditor.appearance_fix import collect_reports

    def item(base, resref, contents=None):
        f = {
            "BaseItem": GffField(GffType.INT, base),
            "TemplateResRef": GffField(GffType.CRESREF, resref),
            "ModelPart1": GffField(GffType.BYTE, 1),
        }
        if contents is not None:
            f["ItemList"] = GffField(GffType.LIST, GffList(contents))
        return GffStruct(0, f)

    ring = item(52, "ring")               # broken, inside a bag
    bag = item(66, "bag", [ring])         # a container carrying the ring
    player = GffStruct(0, {
        "Gender": GffField(GffType.BYTE, 0),
        "ItemList": GffField(GffType.LIST, GffList([bag])),
    })

    class Rec:
        def report(self, resref, slot, ap):
            from nwnfile.icon_reconcile import ItemReport
            return ItemReport(resref, slot, ap, None, None, resref == "ring")

    reports = collect_reports(Rec(), player, female=False)
    assert [r.resref for _p, r in reports] == ["ring"]
    path, _rep = reports[0]
    assert path == (("Mod_PlayerList", 0), ("ItemList", 0), ("ItemList", 0))


def test_extract_rewrites_a_relocated_models_internal_name(tmp_path):
    from nwnfile.icon_reconcile import CopyOp, ExtractPlan, FieldSet
    ed = FakeEditor()
    # a binary .mdl whose internal name (64 bytes at offset 20) is the old resref
    binary = (b"\x00\x00\x00\x00" + b"\x00" * 16 + b"wswsc_b_112".ljust(64, b"\x00")
              + b"and again wswsc_b_112 here")  # name appears twice
    plan = ExtractPlan(254, [CopyOp("wswsc_b_112", 2002, "wswsc_b_254")],
                       [FieldSet("ModelPart1", 254)])
    src = FakeSource({("wswsc_b_112", 2002): binary})
    apply_decisions(ed, src, [Decision(_PATH, _report("godwind", extract=plan), "extract")],
                    tmp_path)
    written = (tmp_path / "wswsc_b_254.mdl").read_bytes()
    assert written[20:84].split(b"\x00")[0] == b"wswsc_b_254"  # renamed to match the file
    assert b"wswsc_b_112" not in written  # every occurrence rewritten
    assert len(written) == len(binary)  # same length, offsets preserved
