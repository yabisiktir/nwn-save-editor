"""Applying appearance decisions (nwnsaveeditor.appearance_fix)."""
from __future__ import annotations

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.icon_reconcile import CopyOp, ExtractPlan, FieldSet, ItemReport
from nwnsaveeditor.appearance_fix import (
    Decision,
    apply_decisions,
    hak_manifest,
    hak_name_for,
    remove_haks,
)

_HAK = "vk_test"


class FakeEditor:
    def __init__(self):
        self.calls = []
        self.haks = []

    def set_raw_field(self, target, path, value, *, where=""):
        self.calls.append((path, value))

    def add_module_hak(self, name, *, where=""):
        self.haks.append(name)
        return True


class FakeSource:
    def __init__(self, raw):
        self.raw = raw

    def read(self, resref, res_type):
        return self.raw.get((resref, res_type))


def _report(resref, *, match=None, extract=None):
    return ItemReport(
        resref=resref, slot="equip", appearance=None, original_image=None,
        current_image=None, broken=True, match_fields=match or [], extract=extract)


def _hak_contents(path):
    reader = ErfReader()
    return {(r.resref.lower(), r.res_type): reader.read_resource_bytes(path, r)
            for r in reader.list_resources(path)}


_PATH = (("Mod_PlayerList", 0), ("Equip_ItemList", 3))


def test_keep_changes_nothing(tmp_path):
    ed = FakeEditor()
    dec = [Decision(_PATH, _report("x"), "keep")]
    summary = apply_decisions(ed, FakeSource({}), dec, tmp_path, hak_name=_HAK)
    assert ed.calls == [] and summary.edited == 0 and summary.files_written == 0
    assert not (tmp_path / f"{_HAK}.hak").exists() and ed.haks == []


def test_match_stages_a_field_edit(tmp_path):
    ed = FakeEditor()
    rep = _report("ring", match=[FieldSet("ModelPart1", 14)])
    apply_decisions(ed, FakeSource({}), [Decision(_PATH, rep, "match")], tmp_path,
                    hak_name=_HAK)
    assert (_PATH + (("ModelPart1", None),), 14) in ed.calls
    assert ed.haks == []  # a match needs no hak


def test_extract_bundles_original_art_and_adds_the_hak_without_repointing(tmp_path):
    ed = FakeEditor()
    # the plan still carries a relocated dst slot, but apply bundles at the ORIGINAL
    # resref (src) and does not repoint the item — high slots don't render.
    plan = ExtractPlan(
        slot=250,
        copies=[CopyOp("iit_ring_130", 3, "iit_ring_250")],
        fields=[FieldSet("ModelPart1", 250)],
    )
    rep = _report("ring", extract=plan)
    src = FakeSource({("iit_ring_130", 3): b"ARTBYTES"})
    summary = apply_decisions(ed, src, [Decision(_PATH, rep, "extract")], tmp_path,
                              hak_name=_HAK)

    hak = _hak_contents(tmp_path / f"{_HAK}.hak")
    assert hak[("iit_ring_130", 3)] == b"ARTBYTES"  # bundled at the original number
    assert ("iit_ring_250", 3) not in hak            # not the relocated slot
    assert ed.calls == []                            # item is NOT repointed
    assert ed.haks == [_HAK]                          # added to the save's Mod_HakList
    assert summary.files_written == 1
    assert hak_manifest(tmp_path) == [f"{_HAK}.hak"]


def test_extract_deduplicates_shared_source_art(tmp_path):
    ed = FakeEditor()
    p1 = ExtractPlan(250, [CopyOp("shared_tex", 2033, "x")], [])
    p2 = ExtractPlan(251, [CopyOp("shared_tex", 2033, "y")], [])
    src = FakeSource({("shared_tex", 2033): b"TEX"})
    summary = apply_decisions(
        ed, src,
        [Decision(_PATH, _report("a", extract=p1), "extract"),
         Decision(_PATH, _report("b", extract=p2), "extract")],
        tmp_path, hak_name=_HAK)
    assert _hak_contents(tmp_path / f"{_HAK}.hak") == {("shared_tex", 2033): b"TEX"}
    assert summary.files_written == 1  # one entry, not two


def test_hak_name_is_stable_and_within_limit():
    name = hak_name_for("000021 - ben2")
    assert name == hak_name_for("000021 - ben2")  # deterministic
    assert name != hak_name_for("000022 - other")  # distinct per save
    assert name.startswith("vk_") and len(name) <= 16


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


def test_remove_haks_deletes_only_manifest_haks(tmp_path):
    ed = FakeEditor()
    plan = ExtractPlan(250, [CopyOp("a", 3, "iit_ring_250")],
                       [FieldSet("ModelPart1", 250)])
    apply_decisions(ed, FakeSource({("a", 3): b"X"}),
                    [Decision(_PATH, _report("r", extract=plan), "extract")], tmp_path,
                    hak_name=_HAK)
    (tmp_path / "unrelated.hak").write_bytes(b"keep")  # not ours
    assert hak_manifest(tmp_path) == [f"{_HAK}.hak"]
    removed = remove_haks(tmp_path)
    assert removed == 1
    assert not (tmp_path / f"{_HAK}.hak").exists()
    assert (tmp_path / "unrelated.hak").exists()  # untouched
    assert hak_manifest(tmp_path) == []


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


def test_extract_bundles_the_model_unchanged_at_its_original_resref(tmp_path):
    ed = FakeEditor()
    # a binary .mdl whose internal name (64 bytes at offset 20) is its own resref
    binary = (b"\x00\x00\x00\x00" + b"\x00" * 16 + b"wswsc_b_112".ljust(64, b"\x00")
              + b"and again wswsc_b_112 here")
    plan = ExtractPlan(254, [CopyOp("wswsc_b_112", 2002, "wswsc_b_254")],
                       [FieldSet("ModelPart1", 254)])
    src = FakeSource({("wswsc_b_112", 2002): binary})
    apply_decisions(ed, src, [Decision(_PATH, _report("godwind", extract=plan), "extract")],
                    tmp_path, hak_name=_HAK)
    hak = _hak_contents(tmp_path / f"{_HAK}.hak")
    # bundled at the original resref, byte-for-byte (no rename — the name already
    # matches the file, and the item keeps ModelPart 112).
    assert hak[("wswsc_b_112", 2002)] == binary
    assert ("wswsc_b_254", 2002) not in hak
    assert ed.calls == []
