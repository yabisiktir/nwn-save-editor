"""Item rules (itemprops.2da): what the game strips on load, and the per-save fix."""
from __future__ import annotations

from nwnfile.formats.erf_reader import ErfReader
from nwnfile.item_property_tables import parse_2da
from nwnsaveeditor import item_rules as ir
from nwnsaveeditor import stripped_items as si

_ITEMPROPS = """2DA V2.0

   0_Melee  20_Torch StringRef Label
0  1        ****     649       Ability
12 1        ****     662       Bonus_Feat
44 "1"      1        714       Light
"""
_BASEITEMS = {15: {"label": "torch", "PropColumn": "20"},
              0: {"label": "shortsword", "PropColumn": "0"}}


def _rules(text=_ITEMPROPS):
    return ir.ItemRules(_BASEITEMS, parse_2da(text)[1])


def test_a_torch_keeps_only_what_its_column_allows():
    rules = _rules()
    assert rules.column(15) == "20_Torch"
    assert rules.allows(15, 44) and not rules.allows(15, 12)
    assert rules.allows(0, 12)
    assert rules.allows(15, 999) and rules.allows(99, 12)  # unknown -> never flagged
    assert rules.base_item_label(15) == "Torch"


def test_patch_switches_on_only_the_named_cells():
    patched = ir.patch_itemprops(_ITEMPROPS, {(12, "20_Torch")})
    before, after = parse_2da(_ITEMPROPS)[1], parse_2da(patched)[1]
    assert after[12]["20_Torch"] == "1"
    after[12]["20_Torch"] = "****"
    assert after == before  # nothing else moved
    assert _rules(patched).allows(15, 12)


def test_rules_hak_holds_just_itemprops(tmp_path):
    path = tmp_path / "vk_x.hak"
    path.write_bytes(ir.build_rules_hak(_ITEMPROPS))
    reader = ErfReader()
    [res] = reader.list_resources(path)
    assert (res.resref, res.res_type) == ("itemprops", 2017)
    assert reader.read_resource_bytes(path, res).decode("latin-1") == _ITEMPROPS


def test_items_carrying_blocked_properties_are_at_risk():
    feat, light = si.PropFields(12, 5, 0, 0, 255, 0), si.PropFields(44, 0, 18, 4, 9, 1)
    torch = si.ItemFacts(path=(("ItemList", 0),), name="Symbol", tag="t", resref="s",
                         base_item=15, description="", props=[feat, light])
    sword = si.ItemFacts(path=(("ItemList", 1),), name="Sword", tag="w", resref="w",
                         base_item=0, description="", props=[feat])
    [risk] = si.find_at_risk([torch, sword], _rules())
    assert risk.item is torch and risk.blocked == [feat] and risk.blueprint is None
    assert not si.find_at_risk([torch], _rules(), skip=[torch.path])
