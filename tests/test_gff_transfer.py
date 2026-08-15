"""Exporting a struct or list subtree to standalone GFF bytes (nwnfile/gff_transfer)."""

from __future__ import annotations

import pytest

from nwnfile.formats.gff import GffField, GffList, GffStruct, GffType, read_gff
from nwnfile.gff_transfer import (
    export_bytes,
    export_extension,
    import_payload,
    struct_file_type,
)


def _item(base=5, tag="MySword"):
    return GffStruct(struct_type=0, fields={
        "BaseItem": GffField(GffType.INT, base),
        "Tag": GffField(GffType.CEXOSTRING, tag),
        "ObjectId": GffField(GffType.DWORD, 7116),
    })


def test_a_struct_exports_as_its_own_gff_root():
    data = export_bytes(_item(), "struct")
    gff = read_gff(data)
    assert gff.file_type.strip() == "UTI"  # detected as an item
    assert gff.root.fields["Tag"].value == "MySword"
    assert gff.root.fields["BaseItem"].value == 5


def test_a_creature_is_typed_utc():
    creature = GffStruct(struct_type=0, fields={
        "FirstName": GffField(GffType.CEXOSTRING, "Morcan"),
        "FeatList": GffField(GffType.LIST, GffList([])),
    })
    assert struct_file_type(creature).strip() == "UTC"


def test_a_plain_struct_is_generic():
    plain = GffStruct(struct_type=0, fields={"X": GffField(GffType.INT, 1)})
    assert struct_file_type(plain).strip() == "GFF"


def test_a_list_is_wrapped_under_a_List_field():
    items = GffList([_item(tag="a"), _item(tag="b")])
    gff = read_gff(export_bytes(items, "list"))
    assert gff.file_type.strip() == "GLS"
    payload = gff.root.fields["List"].value.structs
    assert [s.fields["Tag"].value for s in payload] == ["a", "b"]


def test_extensions_match_the_content():
    assert export_extension(_item(), "struct") == ".uti"
    assert export_extension(GffList([]), "list") == ".gff"


def test_a_deep_copy_is_exported():
    item = _item()
    data = export_bytes(item, "struct")
    item.fields["Tag"].value = "changed after export"
    assert read_gff(data).root.fields["Tag"].value == "MySword"


def test_a_scalar_cannot_be_exported():
    with pytest.raises(ValueError):
        export_bytes(GffField(GffType.INT, 1), "scalar")


def test_import_payload_reads_a_struct_and_a_list():
    kind, structs = import_payload(export_bytes(_item(tag="s"), "struct"))
    assert kind == "struct" and len(structs) == 1 and structs[0].fields["Tag"].value == "s"

    items = GffList([_item(tag="a"), _item(tag="b")])
    kind, structs = import_payload(export_bytes(items, "list"))
    assert kind == "list" and [s.fields["Tag"].value for s in structs] == ["a", "b"]
