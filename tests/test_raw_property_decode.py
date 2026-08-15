"""Decoding a raw PropertiesList entry for the reference panel (raw screen)."""

from __future__ import annotations

from nwnfile.formats.gff import GffField, GffStruct, GffType
from nwnsaveeditor.ui.editor.screens.raw import _item_property_from_struct


def _struct(**fields):
    return GffStruct(struct_type=0, fields={
        k: GffField(GffType.INT, v) for k, v in fields.items()
    })


def test_builds_an_item_property_from_a_raw_struct():
    prop = _item_property_from_struct(_struct(
        PropertyName=37, Subtype=2, CostTable=1, CostValue=3,
        Param1=255, Param1Value=255,
    ))
    assert prop.property_name == 37
    assert prop.subtype == 2
    assert prop.cost_table == 1
    assert prop.cost_value == 3
    assert prop.param1_value == 255


def test_missing_fields_default_to_zero():
    prop = _item_property_from_struct(_struct(PropertyName=6))
    assert prop.property_name == 6
    assert prop.subtype == 0 and prop.cost_value == 0
