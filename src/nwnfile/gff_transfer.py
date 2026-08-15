"""Export part of a save's GFF tree to a standalone GFF file (and, later, back).

A struct (one item, one creature) is written as the file's own root, with a file
type that names what it is — ``UTI`` for an item, ``UTC`` for a creature — so the
export reads like the blueprint the toolset would make. A list (a whole inventory
or equipped set) cannot be a GFF root on its own, so it is wrapped in a root struct
under a ``List`` field, tagged with the ``GLS`` file type the importer looks for.

The bytes are a faithful, deep copy of the subtree, ``ObjectId`` and all — ids are
the *importer's* problem to re-number, not the exporter's.
"""

from __future__ import annotations

import copy

from nwnfile.formats.gff import (
    Gff,
    GffField,
    GffList,
    GffStruct,
    GffType,
    write_gff,
)

#: our file type for a wrapped list export; struct exports use UTI / UTC / GFF.
LIST_FILE_TYPE = "GLS "
_GENERIC_STRUCT_TYPE = "GFF "


def struct_file_type(struct: GffStruct) -> str:
    """The 4-char GFF file type that best names a struct — item, creature, else generic."""
    keys = struct.fields.keys()
    if "BaseItem" in keys:
        return "UTI "
    if "FirstName" in keys and ("Equip_ItemList" in keys or "FeatList" in keys):
        return "UTC "
    return _GENERIC_STRUCT_TYPE


def export_bytes(value, kind: str) -> bytes:
    """Serialise a ``struct`` or ``list`` node's value to standalone GFF bytes."""
    if kind == "struct":
        if not isinstance(value, GffStruct):
            raise ValueError("a struct export needs a GffStruct")
        return write_gff(Gff(struct_file_type(value), "V3.2", copy.deepcopy(value)))
    if kind == "list":
        if not isinstance(value, GffList):
            raise ValueError("a list export needs a GffList")
        root = GffStruct(struct_type=0xFFFFFFFF, fields={
            "List": GffField(GffType.LIST, copy.deepcopy(value)),
        })
        return write_gff(Gff(LIST_FILE_TYPE, "V3.2", root))
    raise ValueError(f"cannot export a {kind!r} node")


def export_extension(value, kind: str) -> str:
    """A sensible file extension for an export, by what it holds."""
    if kind == "list":
        return ".gff"
    return {"UTI ": ".uti", "UTC ": ".utc"}.get(struct_file_type(value), ".gff")
