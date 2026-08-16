"""Tests for the full GFF tree reader+writer (core/formats/gff.py)."""

from __future__ import annotations

import math
import struct
from pathlib import Path

import pytest

from nwnfile.formats.gff import (
    Gff,
    GffField,
    GffList,
    GffStruct,
    GffType,
    LocString,
    read_gff,
    write_gff,
)


def _sample_tree() -> Gff:
    """A tree exercising every GFF field type, nesting and an empty struct."""
    root = GffStruct(
        struct_type=0xFFFFFFFF,
        fields={
            "B": GffField(GffType.BYTE, 200),
            "C": GffField(GffType.CHAR, -5),
            "W": GffField(GffType.WORD, 40000),
            "S": GffField(GffType.SHORT, -12345),
            "D": GffField(GffType.DWORD, 3_000_000_000),
            "I": GffField(GffType.INT, -2_000_000_000),
            "D64": GffField(GffType.DWORD64, 10**18),
            "I64": GffField(GffType.INT64, -(10**18)),
            "F": GffField(GffType.FLOAT, 1.5),
            "DB": GffField(GffType.DOUBLE, 3.141592653589793),
            "Str": GffField(GffType.CEXOSTRING, "hello wörld"),
            "Res": GffField(GffType.CRESREF, "nw_it_ring001"),
            "Loc": GffField(
                GffType.CEXOLOCSTRING,
                LocString(strref=1234, substrings=[(0, "English"), (2, "Deutsch")]),
            ),
            "Void": GffField(GffType.VOID, b"\x00\x01\x02binary"),
            "Sub": GffField(
                GffType.STRUCT,
                GffStruct(struct_type=5, fields={"x": GffField(GffType.INT, 7)}),
            ),
            "Lst": GffField(
                GffType.LIST,
                GffList(structs=[
                    GffStruct(struct_type=0, fields={"a": GffField(GffType.INT, 1)}),
                    GffStruct(struct_type=1, fields={}),  # an empty struct
                ]),
            ),
        },
    )
    return Gff("GFF ", "V3.2", root)


def test_roundtrip_all_field_types():
    tree = _sample_tree()
    reparsed = read_gff(write_gff(tree))
    assert reparsed == tree  # dataclass deep-equality across every type + nesting


def test_writer_is_deterministic():
    data = write_gff(_sample_tree())
    assert write_gff(read_gff(data)) == data  # idempotent


def test_empty_struct_uses_sentinel_offset():
    # A 0-field struct stores 0xffffffff in DataOrDataOffset (BioWare convention).
    data = write_gff(_sample_tree())
    struct_off, struct_count = struct.unpack_from("<II", data, 8)
    empties = [
        struct.unpack_from("<3I", data, struct_off + i * 12)
        for i in range(struct_count)
    ]
    empty = [s for s in empties if s[2] == 0]  # field count 0
    assert empty and all(s[1] == 0xFFFFFFFF for s in empty)


def test_edit_scalar_roundtrips():
    tree = _sample_tree()
    tree.root.set_scalar("I", GffType.INT, 42)
    tree.root.fields["Str"].value = "edited"
    reparsed = read_gff(write_gff(tree))
    assert reparsed.root.get("I") == 42
    assert reparsed.root.get("Str") == "edited"


def test_unsupported_version_rejected():
    bad = b"GFF V1.0" + b"\x00" * 48
    with pytest.raises(ValueError, match="Unsupported GFF version"):
        read_gff(bad)


# -- real save/character files (skipped when absent) ------------------------- #
_BIC = Path.home() / "Documents" / "Neverwinter Nights" / "localvault" / "morcanfaenoble17.bic"
_SAVES = Path.home() / "Documents" / "Neverwinter Nights" / "saves"


def _tree_equal(a, b) -> bool:
    """Deep tree equality that treats two NaN floats as equal (NaN != NaN)."""
    if a.struct_type != b.struct_type or a.fields.keys() != b.fields.keys():
        return False
    for label, fa in a.fields.items():
        fb = b.fields[label]
        if fa.type != fb.type:
            return False
        if fa.type == GffType.STRUCT:
            if not _tree_equal(fa.value, fb.value):
                return False
        elif fa.type == GffType.LIST:
            if len(fa.value.structs) != len(fb.value.structs):
                return False
            pairs = zip(fa.value.structs, fb.value.structs, strict=False)
            if not all(_tree_equal(x, y) for x, y in pairs):
                return False
        elif fa.type in (GffType.FLOAT, GffType.DOUBLE):
            if not (fa.value == fb.value or (math.isnan(fa.value) and math.isnan(fb.value))):
                return False
        elif fa.value != fb.value:
            return False
    return True


@pytest.mark.skipif(not _BIC.is_file(), reason="no local .bic on this box")
def test_real_bic_roundtrips_byte_identical():
    data = _BIC.read_bytes()
    # A Leto-written .bic reproduces byte-for-byte, proving faithful serialisation.
    assert write_gff(read_gff(data)) == data


@pytest.mark.skipif(not _SAVES.is_dir(), reason="no local NWN saves on this box")
def test_real_save_gff_no_data_loss():
    from nwnfile.formats.erf_reader import ErfReader

    er = ErfReader()
    sav = next(iter(_SAVES.glob("*/*.sav")), None)
    if sav is None:
        pytest.skip("the real saves folder holds no saves")
    # module.ifo (the character + module state we would edit) round-trips losslessly
    # and deterministically; game-written files aren't always byte-identical (their
    # field-index ordering differs from Leto's) but carry identical data.
    res = er.find_resource(sav, "module", res_type=2014)
    data = er.read_resource_bytes(sav, res)
    once = write_gff(read_gff(data))
    assert _tree_equal(read_gff(once).root, read_gff(data).root)  # no data loss
    assert write_gff(read_gff(once)) == once  # idempotent
