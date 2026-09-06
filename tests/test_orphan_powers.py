"""Detecting and rescuing orphaned scripted item powers (nwnsaveeditor.orphan_powers).

All fixtures are synthetic ERFs built with ``build_hak``; nothing here needs real
game files, so the suite stays green on any machine.
"""
from __future__ import annotations

from types import SimpleNamespace

from nwnfile.formats.bic_reader import ItemProperty
from nwnfile.formats.erf_reader import ErfReader
from nwnfile.formats.erf_writer import build_hak
from nwnsaveeditor import orphan_powers as op

_NCS, _NSS = 2010, 2009


# --- small fakes -------------------------------------------------------------
class _Struct:
    """A minimal gff-struct stand-in exposing ``.get``."""

    def __init__(self, d):
        self._d = d

    def get(self, k):
        return self._d.get(k)


def _module_root(varname, value):
    vt = SimpleNamespace(value=SimpleNamespace(
        structs=[_Struct({"Name": varname, "Value": value})]))
    return SimpleNamespace(fields={"VarTable": vt})


def _prop(property_name, subtype):
    return ItemProperty(property_name, subtype, 0, 0, 255, 255)


def _item(tag, *props, path=(("Equip_ItemList", 0),), name="Item"):
    properties = [SimpleNamespace(index=i, prop=p) for i, p in enumerate(props)]
    return SimpleNamespace(tag=tag, name=name, path=path, properties=properties)


def _hak(tmp_path, name, entries):
    path = tmp_path / f"{name}.hak"
    path.write_bytes(build_hak(entries))
    return path


class FakeEditor:
    def __init__(self):
        self.haks = []

    def add_module_hak(self, name, *, where=""):
        self.haks.append(name)
        return True


# --- script name / switch ----------------------------------------------------
def test_script_name_for_tag_lowercases_and_truncates():
    assert op.script_name_for_tag("RobesOfSesustris") == "robesofsesustris"
    assert op.script_name_for_tag("a_very_long_tag_name_beyond_limit") == "a_very_long_tag_"


def test_tagbased_scripting_enabled_reads_the_switch():
    assert op.tagbased_scripting_enabled(
        _module_root("X2_SWITCH_ENABLE_TAGBASED_SCRIPTS", 1)) is True
    assert op.tagbased_scripting_enabled(
        _module_root("X2_SWITCH_ENABLE_TAGBASED_SCRIPTS", 0)) is False
    assert op.tagbased_scripting_enabled(_module_root("SOMETHING_ELSE", 1)) is False
    assert op.tagbased_scripting_enabled(SimpleNamespace(fields={})) is False


# --- find_orphans ------------------------------------------------------------
_UNIQUE = 335  # ACTIVATE ITEM SELF ("Unique Power (self only)")


def test_find_orphans_flags_unresolved_script_power():
    items = [_item("robesofsesustris", _prop(15, _UNIQUE))]
    orphans = op.find_orphans(items, is_resolved=lambda _n: False)
    assert len(orphans) == 1
    o = orphans[0]
    assert o.tag == "robesofsesustris" and o.script_name == "robesofsesustris"
    assert o.prop_index == 0


_ONHIT_UNIQUE = 125  # IP_CONST_ONHIT_CASTSPELL_ONHIT_UNIQUEPOWER (prop 82)


def test_find_orphans_flags_onhit_unique_power_but_not_a_real_onhit_spell():
    items = [
        _item("has_onhit", _prop(82, _ONHIT_UNIQUE)),   # On Hit: Unique Power (script)
        _item("has_fire", _prop(82, 16)),               # On Hit: Cast real spell (engine)
    ]
    orphans = op.find_orphans(items, is_resolved=lambda _n: False)
    assert [o.tag for o in orphans] == ["has_onhit"]
    assert orphans[0].label == "On Hit: Unique Power"


def test_find_orphans_skips_resolved_and_nonscript_props():
    items = [
        _item("has_script", _prop(15, _UNIQUE)),          # but resolved below
        _item("plain", _prop(1, 0)),                       # AC bonus — not a script power
        _item("", _prop(15, _UNIQUE)),                     # no tag — can't name a script
    ]
    orphans = op.find_orphans(items, is_resolved=lambda name: name == "has_script")
    assert orphans == []


# --- make_resolver -----------------------------------------------------------
def test_make_resolver_sees_scripts_in_haks(tmp_path):
    hak = _hak(tmp_path, "src", [("robesofsesustris", _NCS, b"NCS V1.0xx")])
    resolved = op.make_resolver(None, [hak])
    assert resolved("robesofsesustris") is True
    assert resolved("ROBESOFSESUSTRIS") is True  # case-insensitive
    assert resolved("not_here") is False


# --- search: Tier 1 (standalone compiled script) -----------------------------
def test_search_tier1_copies_standalone_script_and_missing_deps(tmp_path):
    # root script embeds two ExecuteScript targets: "helper" (in-source, missing)
    # and "prc_forcerest" (resolvable in the target -> must NOT be bundled).
    root = b"NCS V1.0" + b"...helper...prc_forcerest..."
    hak = _hak(tmp_path, "src", [
        ("robesofsesustris", _NCS, root),
        ("helper", _NCS, b"NCS V1.0 helper"),
        ("prc_forcerest", _NCS, b"NCS V1.0 forcerest"),
    ])
    match = op.search_sources(
        "robesofsesustris", [hak],
        is_resolved=lambda n: n == "prc_forcerest")
    assert match.tier == 1 and match.auto_rescuable
    names = {resref for (resref, _t) in match.scripts}
    assert names == {"robesofsesustris", "helper"}  # dep pulled, resolvable one skipped


def test_search_source_only_needs_compile(tmp_path):
    hak = _hak(tmp_path, "src", [("robesofsesustris", _NSS, b"void main(){}")])
    match = op.search_sources("robesofsesustris", [hak], is_resolved=lambda _n: False)
    assert match.tier == 1 and match.needs_compile and not match.auto_rescuable


# --- search: Tier 2 (dispatcher branch) --------------------------------------
def test_search_tier2_finds_dispatcher_branch(tmp_path):
    dispatcher = (
        'void main(){\n'
        '  object item=GetItemActivated();\n'
        '  if (GetTag(item)=="robesofsesustris")\n'
        '    {\n'
        '    PRCForceRest(oPC);\n'
        '    return;\n'
        '    }\n'
        '}\n')
    hak = _hak(tmp_path, "sof", [("activateitem3", _NSS, dispatcher.encode())])
    match = op.search_sources("robesofsesustris", [hak], is_resolved=lambda _n: False)
    assert match.tier == 2 and not match.auto_rescuable
    assert match.dispatcher == "activateitem3"
    assert "PRCForceRest" in match.branch_source


def test_search_none_when_absent(tmp_path):
    hak = _hak(tmp_path, "src", [("something_else", _NCS, b"NCS V1.0")])
    match = op.search_sources("robesofsesustris", [hak], is_resolved=lambda _n: False)
    assert match.tier == 0 and not match.auto_rescuable


# --- batched search (single pass over sources) -------------------------------
def test_search_many_matches_per_tag_search_in_one_pass(tmp_path):
    dispatcher = (
        'void main(){ object o=GetItemActivated();\n'
        '  if (GetTag(o)=="dispatchtag"){return;} }')
    hak = _hak(tmp_path, "src", [
        ("standalone", _NCS, b"NCS V1.0 body"),   # tier 1
        ("srconly", _NSS, b"void main(){}"),       # source only
        ("activateitem", _NSS, dispatcher.encode()),  # tier 2 branch for dispatchtag
        ("other", _NCS, b"NCS V1.0"),
    ])
    tags = ["standalone", "srconly", "dispatchtag", "missing"]
    many = op.search_sources_many(tags, [hak], is_resolved=lambda _n: False)
    # every tag resolves to exactly what a per-tag search_sources would return
    for tag in tags:
        one = op.search_sources(tag, [hak], is_resolved=lambda _n: False)
        assert many[tag].tier == one.tier
        assert many[tag].dispatcher == one.dispatcher
        assert set(many[tag].scripts) == set(one.scripts)
    assert many["standalone"].tier == 1 and many["standalone"].auto_rescuable
    assert many["srconly"].needs_compile
    assert many["dispatchtag"].tier == 2 and many["dispatchtag"].dispatcher == "activateitem"
    assert many["missing"].tier == 0


def test_search_reads_only_the_named_script_not_every_ncs(tmp_path):
    """Regression: the search must not read the bytes of every compiled script in a
    source (it once read hundreds of MB per orphan). Only the matched script and its
    dependency closure are read."""
    hak = _hak(tmp_path, "src", [
        ("wanted", _NCS, b"NCS V1.0 dep"),
        ("dep", _NCS, b"NCS V1.0 leaf"),
        ("unrelated1", _NCS, b"NCS V1.0 x" * 100),
        ("unrelated2", _NCS, b"NCS V1.0 y" * 100),
    ])
    reader = ErfReader()
    reads: list[str] = []
    real = reader.read_resource_bytes
    reader.read_resource_bytes = lambda path, res: (reads.append(res.resref), real(path, res))[1]
    match = op.search_sources("wanted", [hak], is_resolved=lambda _n: False, reader=reader)
    assert match.tier == 1
    # "wanted" (matched) and "dep" (in its byte closure) are read; the unrelated
    # scripts are never read — proving the search is name-indexed, not brute-force.
    assert set(reads) == {"wanted", "dep"}


# --- apply / manifest / removal ----------------------------------------------
def test_apply_rescue_bundles_scripts_adds_hak_and_records_manifest(tmp_path):
    match = op.SourceMatch(
        tag="robesofsesustris", script_name="robesofsesustris", tier=1,
        scripts={("robesofsesustris", _NCS): b"NCS V1.0 body",
                 ("helper", _NCS): b"NCS V1.0 helper"})
    ed = FakeEditor()
    summary = op.apply_rescue(ed, [match], tmp_path, hak_name="vk_test")

    assert summary.powers == 1 and summary.scripts == 2 and summary.hak == "vk_test.hak"
    assert ed.haks == ["vk_test"]
    hak_path = tmp_path / "vk_test.hak"
    reader = ErfReader()
    contents = {r.resref.lower(): r.res_type for r in reader.list_resources(hak_path)}
    assert contents == {"robesofsesustris": _NCS, "helper": _NCS}

    assert op.hak_manifest(tmp_path) == ["vk_test.hak"]
    assert op.remove_haks(tmp_path) == 1
    assert not hak_path.exists() and op.hak_manifest(tmp_path) == []


def test_apply_rescue_skips_non_tier1(tmp_path):
    tier2 = op.SourceMatch(tag="x", script_name="x", tier=2, dispatcher="d")
    ed = FakeEditor()
    summary = op.apply_rescue(ed, [tier2], tmp_path, hak_name="vk_test")
    assert summary.powers == 0 and summary.scripts == 0 and ed.haks == []
    assert not (tmp_path / "vk_test.hak").exists()
    assert any("not auto-rescuable" in n for n in summary.notes)


# --- dialog ------------------------------------------------------------------
def _orphan(tag, label="Unique Power"):
    return op.OrphanPower(
        item_path=(("Equip_ItemList", 0),), item_name="Robe", tag=tag,
        script_name=op.script_name_for_tag(tag), prop_index=0, label=label)


def _tier1(tag):
    return op.SourceMatch(tag=tag, script_name=tag, tier=1, origin="src.hak",
                          scripts={(tag, _NCS): b"NCS V1.0"})


def test_dialog_offers_tier1_checked_and_previews_tier2(qtbot):
    from PySide6.QtWidgets import QDialogButtonBox

    from nwnsaveeditor.ui.dialogs.rescue_power_dialog import RescuePowerDialog

    m2 = op.SourceMatch(tag="othertag", script_name="othertag", tier=2, origin="sof.mod",
                        dispatcher="activateitem3", branch_source="PRCForceRest(oPC);")
    dlg = RescuePowerDialog(
        [_orphan("robesofsesustris"), _orphan("othertag")],
        {"robesofsesustris": _tier1("robesofsesustris"), "othertag": m2},
        tagbased=True)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.selected_tags() == ["robesofsesustris"]  # tier-1 ticked; tier-2 has no box
    assert dlg._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()


def test_dialog_offers_compile_for_tier2_when_a_compiler_exists(qtbot):
    from nwnsaveeditor.ui.dialogs.rescue_power_dialog import RescuePowerDialog

    m2 = op.SourceMatch(tag="robesofsesustris", script_name="robesofsesustris", tier=2,
                        origin="sof.mod", dispatcher="activateitem3",
                        branch_source="PRCForceRest(oPC);")
    dlg = RescuePowerDialog(
        [_orphan("robesofsesustris")], {"robesofsesustris": m2},
        tagbased=True, can_compile=True)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.selected_tags() == []  # no standalone script to copy
    assert dlg.selected_compile_tags() == ["robesofsesustris"]  # compile ticked by default


def test_dialog_disables_rescue_without_tagbased(qtbot):
    from PySide6.QtWidgets import QDialogButtonBox

    from nwnsaveeditor.ui.dialogs.rescue_power_dialog import RescuePowerDialog

    dlg = RescuePowerDialog(
        [_orphan("robesofsesustris")], {"robesofsesustris": _tier1("robesofsesustris")},
        tagbased=False)
    qtbot.addWidget(dlg)
    dlg.show()
    assert dlg.selected_tags() == []  # box present but unchecked + disabled
    assert not dlg._buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
